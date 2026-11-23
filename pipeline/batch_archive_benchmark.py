#!/usr/bin/env python3
"""Streaming multi-aircraft ADSB.lol batch benchmark. Evidence only; no nav promotion."""
from __future__ import annotations
import argparse, csv, gzip, io, json, re, resource, sys, tempfile, time, zlib
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "scripts"))
import build_corridors as archive_pipeline
import route_preview
import adsb_learning.build_corridors as builder

EUROPE_AIRLINE_PREFIXES = {
    "RYR","WZZ","EZY","BAW","DLH","AFR","KLM","SAS","LOT","TAP","VLG","AUA",
    "SWR","EWG","TUI","FIN","THY","PGT","TRA","NAX","NOZ","JAF","FHY","AEE",
    "CFG","CLH","OAL","LGL","DAT","BTI","AKN","BCS","DHL","EXS","TOM","TVF",
    "IBE","IBS","AEA","BEL","ITY","AZA","VIR","BEE","CFE","EIN","ENT","FCA",
    "FPO","GWI","HYS","KZR","MJT","MLD","MSR","NEE","NLY","NVD","RUK","SXS",
    "SUI","TCX","TFL","THA","VKG","VOE","VLM","VTI","XLF","XSR","ZB"
}
EU_BOUNDS = (32.0, 72.0, -20.0, 45.0)
MAX_TRACE_MEMBER_BYTES = 50 * 1024 * 1024

def trace_member_size_is_readable(size: int) -> bool:
    """Bound memory use without dropping otherwise valid small traces."""
    return 0 < size <= MAX_TRACE_MEMBER_BYTES
TARGET_AIRCRAFT = 50
CONFIDENCE_THRESHOLDS = {"LOW": [1, 2], "MEDIUM": [3, 4], "HIGH": [5]}
FORBIDDEN_ARTIFACT_KEYS = {
    "id", "icao24", "icao_24", "hex", "aircraft_id", "aircraft_hex",
    "registration", "registration_id", "registration_number",
    "callsign", "call_sign", "flight", "flight_number",
    "trace", "raw_trace", "trace_data", "trace_points", "trace_endpoints",
    "_observed_trace_endpoints", "observed_trace_endpoints", "geometry",
    "positions", "position_data", "timestamp", "timestamps",
}

def confidence_for_sample_count(count):
    if count >= CONFIDENCE_THRESHOLDS["HIGH"][0]:
        return "HIGH"
    if count >= CONFIDENCE_THRESHOLDS["MEDIUM"][0]:
        return "MEDIUM"
    return "LOW"

def eu_coord(coord):
    lat, lon = coord
    return EU_BOUNDS[0] <= lat <= EU_BOUNDS[1] and EU_BOUNDS[2] <= lon <= EU_BOUNDS[3]

def strict_write(path, payload):
    assert_privacy_safe(payload)
    Path(path).write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    with Path(path).open(encoding="utf-8") as f:
        json.load(f, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))

def assert_privacy_safe(payload):
    """Reject aircraft identity and raw trace fields from serialized artifacts."""
    def walk(value, path="$"):
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).casefold().replace("-", "_")
                if normalized in FORBIDDEN_ARTIFACT_KEYS:
                    raise ValueError(f"Privacy audit failed: forbidden artifact field {path}.{key}")
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")
    walk(payload)

def airport_metadata(path):
    coords, cities = {}, {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ident=(row.get("ident") or row.get("icao") or "").strip().upper()
            try:
                lat=float(row.get("latitude_deg") or row.get("latitude"))
                lon=float(row.get("longitude_deg") or row.get("longitude"))
            except (TypeError,ValueError):
                continue
            if len(ident)==4:
                coords[ident]=(lat,lon)
                city=(row.get("municipality") or row.get("city") or "").strip()
                cities[ident]=city or ident
    return coords,cities

def read_fixes(path):
    fixes=[]
    with open(path,newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ident=(row.get("ident") or row.get("id") or row.get("fix_id") or
                   row.get("navaid_id") or row.get("name") or "").strip().upper()
            try:
                lat=float(row.get("lat") or row.get("latitude") or row.get("latitude_deg"))
                lon=float(row.get("lon") or row.get("longitude") or row.get("longitude_deg"))
            except (TypeError,ValueError):
                continue
            if ident and len(ident)<=8 and -90<=lat<=90 and -180<=lon<=180:
                fixes.append((ident,lat,lon))
    return fixes

def flight_prefix(doc):
    """Return an allowed airline prefix from a readsb trace, if present.

    Historical trace files store callsign under each point's nested aircraft
    object (trace row index 8); it is not normally a top-level field. Keep
    compatibility with older exports while scanning nested observations.
    Only the transient prefix is returned; no callsign is serialized.
    """
    def values():
        yield doc.get("flight")
        yield doc.get("callsign")
        trace=doc.get("trace",[])
        if isinstance(trace,list):
            for row in trace:
                if isinstance(row,(list,tuple)) and len(row)>8 and isinstance(row[8],dict):
                    aircraft=row[8]
                    yield aircraft.get("flight")
                    yield aircraft.get("callsign")

    first_prefix=""
    for value in values():
        if isinstance(value,list):
            value="".join(str(x) for x in value)
        normalized=re.sub(r"[^A-Z0-9]","",str(value or "").upper())
        prefix=normalized[:3] if len(normalized)>=4 else ""
        if not prefix:
            continue
        if not first_prefix:
            first_prefix=prefix
        if prefix in EUROPE_AIRLINE_PREFIXES:
            return prefix
    return first_prefix

PREFIX_COMPRESSED_BYTES = 16 * 1024
PREFIX_DECODED_BYTES = 256 * 1024


def partial_callsign_prefixes(data: bytes, compressed: bool) -> tuple[bool, set[str]]:
    """Inspect a bounded trace prefix for callsign prefixes without full JSON decoding."""
    if compressed:
        try:
            decoded = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(
                data, PREFIX_DECODED_BYTES
            )
        except zlib.error:
            decoded = b""
    else:
        decoded = data[:PREFIX_DECODED_BYTES]
    text = decoded.decode("utf-8", errors="replace")
    values = re.findall(r'"(?:flight|callsign)"\s*:\s*("(?:\\.|[^"\\])*")', text, re.I)
    prefixes = set()
    for raw in values:
        try:
            value = json.loads(raw)
        except Exception:
            continue
        if isinstance(value, list):
            value = "".join(str(x) for x in value)
        normalized = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
        if len(normalized) >= 4:
            prefixes.add(normalized[:3])
    return bool(values), prefixes


def load_trace_member(tar, member):
    """Prefix-screen non-European traces, then read/decode only likely candidates."""
    source = tar.extractfile(member)
    if source is None:
        return None, None, "unreadable_member"
    try:
        compressed = source.read(min(member.size, PREFIX_COMPRESSED_BYTES))
        is_gzip = compressed[:2] == b"\x1f\x8b"
        has_callsign, prefixes = partial_callsign_prefixes(compressed, is_gzip)
        if has_callsign and not (prefixes & EUROPE_AIRLINE_PREFIXES):
            return None, None, "non_european_commercial_callsign"
        reader = getattr(tar, "fileobj", None)
        original_block_size = getattr(reader, "CACHE_BLOCK_BYTES", None)
        if original_block_size is not None:
            reader.CACHE_BLOCK_BYTES = 128 * 1024
            reader.cache.clear()
        source.seek(0)
        raw = source.read(MAX_TRACE_MEMBER_BYTES + 1)
        if len(raw) > MAX_TRACE_MEMBER_BYTES:
            return None, None, "oversize_trace"
        if is_gzip:
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as gz:
                    payload = gz.read(MAX_TRACE_MEMBER_BYTES + 1)
            except (OSError, EOFError, zlib.error):
                return None, None, "invalid_gzip"
        else:
            payload = raw
        if len(payload) > MAX_TRACE_MEMBER_BYTES:
            return None, None, "oversize_decoded_trace"
        try:
            doc = json.loads(payload)
        except Exception:
            return None, None, "invalid_json"
        if flight_prefix(doc) not in EUROPE_AIRLINE_PREFIXES:
            return None, None, "non_european_commercial_callsign"
        return payload, doc, None
    finally:
        source.close()
        if "reader" in locals() and original_block_size is not None:
            reader.CACHE_BLOCK_BYTES = original_block_size
            reader.cache.clear()


def diag_leg(leg, nav):
    observed=leg.get("_observed_trace_endpoints")
    try:
        trace_start=tuple(float(x) for x in observed["start"])
        trace_end=tuple(float(x) for x in observed["end"])
        if len(trace_start)!=2 or len(trace_end)!=2:
            raise ValueError("trace endpoint must contain latitude and longitude")
    except (KeyError, TypeError, ValueError):
        return {"connected":False,"path_distance_nm":None,"start_gap_nm":None,
                "end_gap_nm":None,"covered_fraction":None,
                "status":"MISSING_OBSERVED_TRACE_ENDPOINTS"}
    fixes=leg.get("matchedFixes",[])
    details=leg.get("matchedFixDetails",[])
    matched=[(f,(float(details[i]["lat"]),float(details[i]["lon"])))
             for i,f in enumerate(fixes) if i<len(details) and isinstance(details[i],dict)
             and details[i].get("lat") is not None and details[i].get("lon") is not None]
    starts=[]; goals=[]
    for i,(fix,coord) in enumerate(matched):
        try:
            r=nav.resolve_physical_endpoint(fix,coord,"start")
            if r and (r["offset_nm"] is None or r["offset_nm"]<=5):
                starts.append((i,fix,coord,r))
        except (ValueError,KeyError,TypeError): pass
        try:
            r=nav.resolve_physical_endpoint(fix,coord,"goal")
            if r and (r["offset_nm"] is None or r["offset_nm"]<=5):
                goals.append((i,fix,coord,r))
        except (ValueError,KeyError,TypeError): pass
    result={"connected":False,"path_distance_nm":None,"start_gap_nm":None,
            "end_gap_nm":None,"covered_fraction":None,"status":"UNVERIFIED_ENDPOINTS"}
    if not starts or not goals:
        return result
    start,goal=starts[0],goals[-1]
    start_graph_coord=start[3].get("coord")
    end_graph_coord=goal[3].get("coord")
    sg=archive_pipeline._nm(trace_start,start_graph_coord) if start_graph_coord else None
    eg=archive_pipeline._nm(trace_end,end_graph_coord) if end_graph_coord else None
    if sg is not None: sg=round(sg,2)
    if eg is not None: eg=round(eg,2)
    result.update(start_gap_nm=sg,end_gap_nm=eg)
    try:
        route=nav.a_star_connected(start[1],goal[1],start[2],goal[2])
    except Exception:
        route=None
    if not route:
        result["status"]="GRAPH_GAP"
        return result
    dist=float(route[1])
    denom=dist+sg+eg if sg is not None and eg is not None else None
    result.update(connected=True,status="CONNECTED",path_distance_nm=round(dist,2),
                  covered_fraction=round(dist/denom,4) if denom and denom>0 else None)
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--date",default="2026-11-16")
    ap.add_argument("--max-aircraft",type=int,default=TARGET_AIRCRAFT)
    ap.add_argument("--minimum-aircraft",type=int,default=25)
    ap.add_argument("--evidence-out",default="/tmp/scale_batch_evidence.json")
    ap.add_argument("--summary-out",default="/tmp/scale_batch_summary.json")
    args=ap.parse_args()
    if not (25<=args.minimum_aircraft<=args.max_aircraft<=50):
        raise SystemExit("Batch size must be 25-50 aircraft")
    started=time.perf_counter()
    session=archive_pipeline.requests.Session()
    session.headers.update({"User-Agent":"FlightTempo-ADS-B-scale-benchmark/1.0",
                            "Accept":"application/vnd.github+json"})
    release,asset_specs=archive_pipeline.release_asset_specs(args.date,session)
    airports_path=ROOT/"navigation/airports/ourairports_airports.csv"
    fixes_path=ROOT/"navigation/waypoints/flightgear_fixes.csv"
    airports=builder.load_airports(airports_path)
    airport_coords,cities=airport_metadata(airports_path)
    fixes=read_fixes(fixes_path)
    graph_airports={ident:i for i,(ident,lat,lon) in enumerate(airports)}
    nav=archive_pipeline.RepositoryNavDatabase()
    nav._load_airways()
    if not nav.physical_nodes or not nav.physical_adj:
        raise RuntimeError("Physical FTWG graph unavailable; refusing scale benchmark")
    selected_hex=set()
    aircraft_processed=0
    scanned_trace_members=0
    eligible_legs=0
    segmented_legs=0
    connected_legs=0
    trace_rows=0
    rejected=Counter()
    leg_metrics=[]
    corridor_samples=defaultdict(set)
    corridor_sequences=defaultdict(Counter)
    link_samples=defaultdict(set)
    link_aircraft=defaultdict(set)
    with tempfile.TemporaryDirectory(prefix="flighttempo-scale-") as tmp:
        with archive_pipeline.HTTPRangeConcatReader(asset_specs,session) as raw:
            with __import__("tarfile").open(fileobj=raw,mode="r:") as tar:
                reported_aircraft=0
                while True:
                    member=tar.next()
                    if member is None:
                        break
                    name=member.name.replace("\\","/").rsplit("/",1)[-1].lower()
                    match=re.fullmatch(r"trace_full_([0-9a-f]{6})\.json(?:\.gz)?",name)
                    if not member.isfile() or not match:
                        continue
                    scanned_trace_members+=1
                    hex_id=match.group(1)
                    if hex_id in selected_hex or not trace_member_size_is_readable(member.size):
                        continue
                    payload,doc,reason=load_trace_member(tar,member)
                    if reason:
                        rejected[reason]+=1
                        continue
                    trace_path=Path(tmp)/"trace.json"
                    trace_path.write_bytes(payload)
                    try:
                        legs=builder.process_trace(trace_path,airports,fixes,graph_airports,
                                                   include_observed_endpoints=True)
                    except Exception:
                        rejected["trace_processing_or_anchor_failure"]+=1
                        trace_path.unlink(missing_ok=True)
                        continue
                    eu_legs=[]
                    for leg in legs:
                        if leg.get("excluded"): continue
                        if not (leg.get("origin") in airport_coords and leg.get("destination") in airport_coords):
                            continue
                        if not (eu_coord(airport_coords[leg["origin"]]) and eu_coord(airport_coords[leg["destination"]])):
                            continue
                        eu_legs.append(leg)
                    if not eu_legs:
                        rejected["no_european_eligible_legs"]+=1
                        trace_path.unlink(missing_ok=True)
                        continue
                    selected_hex.add(hex_id)
                    aircraft_processed+=1
                    trace_rows+=len(doc.get("trace",[]))
                    segmented_legs+=len(legs)
                    for leg in eu_legs:
                        eligible_legs+=1
                        graph=diag_leg(leg,nav)
                        connected_legs+=int(graph["connected"])
                        origin,destination=leg["origin"],leg["destination"]
                        city_pair=f"{cities.get(origin,origin)} – {cities.get(destination,destination)}"
                        sample=(hex_id,leg.get("legNumber"))
                        corridor_samples[city_pair].add(sample)
                        corridor_sequences[city_pair][tuple(leg.get("matchedFixes",[]))]+=1
                        for link in leg.get("candidateLinks",[]):
                            edge=(city_pair,link["from"],link["to"])
                            link_samples[edge].add(sample)
                            link_aircraft[edge].add(hex_id)
                        leg_metrics.append({"leg_number":leg.get("legNumber"),"city_pair":city_pair,"airport_pair":f"{origin}-{destination}",
                            "segmentation":leg.get("segmentation"),"position_count":leg.get("positionCount"),
                            "matched_fix_count":leg.get("matchCount",0),**graph})
                    trace_path.unlink(missing_ok=True)
                    if scanned_trace_members%250==0 or aircraft_processed>=reported_aircraft+5:
                        print(
                            f"[benchmark] scanned_trace_members={scanned_trace_members} "
                            f"selected_aircraft={aircraft_processed} "
                            f"range_bytes_downloaded={raw.range_bytes_downloaded} "
                            f"range_requests={raw.range_requests}", flush=True
                        )
                        reported_aircraft=aircraft_processed
                    if aircraft_processed>=args.max_aircraft:
                        break
    runtime=time.perf_counter()-started
    peak_rss=int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # Linux reports ru_maxrss in KiB. Convert to MiB for artifact.
    peak_memory_mb=round(peak_rss/1024,1)
    corridors=[]
    for city_pair,samples in corridor_samples.items():
        seq_counts=corridor_sequences[city_pair]
        dominant=max(seq_counts.values(),default=0)
        corridors.append({"city_pair":city_pair,"independent_samples":len(samples),
                         "corridor_stability":round(dominant/max(1,len(samples)),3),
                         "unique_fix_sequences":len(seq_counts)})
    corridors.sort(key=lambda c:(-c["independent_samples"],c["city_pair"]))
    aggregated_links=[]
    for (city_pair,a,b),samples in link_samples.items():
        n=len(samples)
        confidence=confidence_for_sample_count(n)
        aggregated_links.append({"city_pair":city_pair,"from":a,"to":b,
            "independent_samples":n,"independent_aircraft":len(link_aircraft[(city_pair,a,b)]),
            "confidence":confidence,"promotion":"DISABLED"})
    aggregated_links.sort(key=lambda x:(-x["independent_samples"],x["city_pair"],x["from"],x["to"]))
    medium=sum(x["confidence"]=="MEDIUM" for x in aggregated_links)
    high=sum(x["confidence"]=="HIGH" for x in aggregated_links)
    severe=[x for x in leg_metrics if (x.get("start_gap_nm") or 0)>100 or (x.get("end_gap_nm") or 0)>100]
    summary={"status":"passed" if aircraft_processed>=args.minimum_aircraft else "insufficient_aircraft",
        "source_release":release.get("tag_name"),"archive_date":args.date,
        "aircraft_processed":aircraft_processed,"minimum_aircraft_required":args.minimum_aircraft,
        "trace_members_scanned":scanned_trace_members,"trace_rows":trace_rows,
        "total_legs_segmented":segmented_legs,"eligible_european_legs":eligible_legs,
        "physical_graph_connected_legs":connected_legs,
        "physical_graph_connectivity_rate":round(connected_legs/max(1,eligible_legs),4),
        "runtime_seconds":round(runtime,2),"peak_memory_mb":peak_memory_mb,
        "corridor_count":len(corridors),"top_15_city_pair_corridors":corridors[:15],
        "candidate_link_count":len(aggregated_links),"candidate_links_medium_observation_count":medium,
        "candidate_links_high_observation_count":high,
        "candidate_links_with_3plus_samples":sum(x["independent_samples"]>=3 for x in aggregated_links),
        "candidate_links_with_5plus_samples":sum(x["independent_samples"]>=5 for x in aggregated_links),
        "severe_gap_leg_count":len(severe),"severe_gap_legs":severe,
        "promotion_enabled":False,"trusted_navigation_modified":False,
        "rejection_counts":dict(rejected),
        "archive_range_bytes_downloaded":raw.range_bytes_downloaded,
        "archive_range_requests":raw.range_requests}
    evidence={"schema_version":1,"benchmark_type":"streaming_multi_aircraft_observed_adsb",
        "privacy":"Aircraft identifiers, callsigns, registrations, raw traces, and timestamps are not serialized.",
        "independent_sample_definition":"One distinct aircraft ICAO24 plus segmented leg number within the archive date; each directed candidate link counted once per leg.",
        "confidence_thresholds":CONFIDENCE_THRESHOLDS,
        "summary":summary,"corridors":corridors,"candidate_links":aggregated_links,
        "leg_metrics":leg_metrics}
    strict_write(args.evidence_out,evidence)
    strict_write(args.summary_out,summary)
    print(json.dumps(summary,indent=2,allow_nan=False),flush=True)
    if aircraft_processed<args.minimum_aircraft:
        raise SystemExit(f"Only {aircraft_processed} qualifying aircraft; minimum {args.minimum_aircraft} not reached")
    if not eligible_legs:
        raise SystemExit("Batch produced zero eligible European legs")
if __name__=="__main__":
    main()



