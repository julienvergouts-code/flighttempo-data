#!/usr/bin/env python3
"""Build anonymised, non-US ADS-B corridor evidence against the FTWG graph.

Input: local readsb per-aircraft trace JSON files. Raw traces are never copied to
the output. This is evidence generation only; it never edits the nav graph.
"""
from __future__ import annotations
import argparse, csv, json, math, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import route_preview

# K=contiguous US, P=Pacific US territories, T=US territories (per rollout policy).
EXCLUDED_AIRPORT_PREFIXES = ("K", "P", "T")
AIRPORT_ANCHOR_RADIUS_NM = 8.0
FIX_MATCH_RADIUS_NM = 3.0
MAX_CANDIDATE_GAP_NM = 40.0
MAX_CANDIDATE_GAP_SECONDS = 900.0

def distance_nm(a, b):
    return route_preview.distance_nm(a, b)

def read_points(path):
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    epoch = float(obj.get("timestamp", 0))
    points = []
    for row in obj.get("trace", []):
        if not isinstance(row, list) or len(row) < 3:
            continue
        try:
            sec, lat, lon = map(float, row[:3])
        except (TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        flags = int(row[6]) if len(row) > 6 and row[6] is not None else 0
        altitude_ft = None
        groundspeed_kt = None
        try:
            if len(row) > 3 and row[3] is not None and row[3] != "ground":
                altitude_ft = float(row[3])
        except (TypeError, ValueError):
            pass
        try:
            if len(row) > 4 and row[4] is not None:
                groundspeed_kt = float(row[4])
        except (TypeError, ValueError):
            pass
        points.append({"t": epoch + sec, "lat": lat, "lon": lon,
                       "ground": bool(flags & 2), "altitude_ft": altitude_ft,
                       "groundspeed_kt": groundspeed_kt})
    points.sort(key=lambda p: p["t"])
    return obj, points

def load_airports(path):
    airports = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # Our normalized OurAirports export uses icao/latitude/longitude;
            # the raw OurAirports source uses ident/latitude_deg/longitude_deg.
            ident = (row.get("ident") or row.get("icao") or "").strip().upper()
            try:
                lat = float(row.get("latitude_deg") or row.get("latitude"))
                lon = float(row.get("longitude_deg") or row.get("longitude"))
            except (TypeError, ValueError):
                continue
            if len(ident) == 4 and ident.isalnum():
                airports.append((ident, lat, lon))
    return airports

def nearest_airport(point, airports, radius=AIRPORT_ANCHOR_RADIUS_NM):
    candidates = [(distance_nm((point["lat"], point["lon"]), (lat, lon)), ident)
                  for ident, lat, lon in airports]
    if not candidates:
        return None
    d, ident = min(candidates)
    return ident if d <= radius else None

def anchor_airports(points, airports):
    """Resolve terminal airports from multiple boundary samples, not one ADS-B point."""
    if not points or not airports:
        return None, None

    def resolve_window(window):
        # Count repeated nearest-airport matches; break ties by smallest
        # cumulative distance. This avoids selecting an airport from one noisy point.
        votes = defaultdict(lambda: [0, 0.0])
        for point in window:
            ranked = [(distance_nm((point["lat"], point["lon"]), (lat, lon)), ident)
                      for ident, lat, lon in airports]
            if not ranked:
                continue
            distance, ident = min(ranked)
            if distance <= 25.0:
                votes[ident][0] += 1
                votes[ident][1] += distance
        if not votes:
            return None
        return min(votes, key=lambda ident: (-votes[ident][0], votes[ident][1], ident))

    # Ground evidence is preferred only when it independently anchors both ends.
    ground = [p for p in points if p["ground"]]
    if len(ground) >= 2:
        first = resolve_window(ground[:10])
        last = resolve_window(list(reversed(ground[-10:])))
        if first and last:
            return first, last

    return resolve_window(points[:10]), resolve_window(list(reversed(points[-10:])))

def split_flight_legs(points, max_gap_seconds=1200):
    """Split aircraft-day traces on >20 min gaps and reliable ground transitions."""
    if not points:
        return []
    chunks, current = [], [points[0]]
    for point in points[1:]:
        if point["t"] - current[-1]["t"] > max_gap_seconds:
            chunks.append(current)
            current = [point]
        else:
            current.append(point)
    if current:
        chunks.append(current)
    legs = []
    for chunk in chunks:
        if sum(1 for p in chunk if p["ground"]) < 2:
            # Time-gap-separated segments remain candidates; endpoints may be partial.
            if len(chunk) >= 2:
                legs.append({"points": chunk, "segmentation": "TIME_GAP_OR_NO_GROUND_FLAGS"})
            continue
        in_air, start = False, None
        for i, point in enumerate(chunk):
            if not point["ground"] and not in_air:
                in_air, start = True, i
            elif point["ground"] and in_air:
                airborne = chunk[start:i]
                if len(airborne) >= 2:
                    legs.append({"points": airborne,
                                "before_ground": chunk[max(0, start-10):start],
                                "after_ground": chunk[i:min(len(chunk), i+10)],
                                "segmentation": "GROUND_TRANSITIONS"})
                in_air, start = False, None
        if in_air and start is not None:
            airborne = chunk[start:]
            if len(airborne) >= 2:
                legs.append({"points": airborne, "before_ground": chunk[max(0,start-10):start],
                             "after_ground": [], "segmentation": "GROUND_TRANSITIONS_OPEN_END"})
    return legs or [{"points": points, "segmentation": "NO_USABLE_AIRBORNE_SEGMENTS"}]

def airport_from_ground(window, airports, radius=AIRPORT_ANCHOR_RADIUS_NM):
    if not window or not airports:
        return None
    votes = defaultdict(lambda: [0, 0.0])
    for point in window:
        distance, ident = min((distance_nm((point["lat"], point["lon"]), (lat, lon)), ident)
                              for ident, lat, lon in airports)
        if distance <= radius:
            votes[ident][0] += 1
            votes[ident][1] += distance
    if not votes:
        return None
    return min(votes, key=lambda ident: (-votes[ident][0], votes[ident][1], ident))

def match_fixes(points, fixes, radius=FIX_MATCH_RADIUS_NM):
    matched = []
    for p in points:
        best = None
        for ident, lat, lon in fixes:
            d = distance_nm((p["lat"], p["lon"]), (lat, lon))
            if d <= radius and (best is None or d < best[0]):
                best = (d, ident, lat, lon)
        if best:
            d, ident, lat, lon = best
            item = {"fix": ident, "lat": lat, "lon": lon,
                    "distanceNm": round(d, 2), "t": p["t"]}
            if not matched or matched[-1]["fix"] != ident:
                matched.append(item)
    return matched

def candidate_links(matches):
    links = []
    for a, b in zip(matches, matches[1:]):
        gap = distance_nm((a["lat"], a["lon"]), (b["lat"], b["lon"]))
        dt = b["t"] - a["t"]
        if a["fix"] == b["fix"] or gap <= 0 or gap > MAX_CANDIDATE_GAP_NM or dt <= 0 or dt > MAX_CANDIDATE_GAP_SECONDS:
            continue
        links.append({"from": a["fix"], "to": b["fix"],
                      "observedDistanceNm": round(gap, 1),
                      "elapsedSeconds": round(dt),
                      "evidenceType": "INFERRED_OBSERVATION",
                      "confidence": "low", "independentSamples": 1,
                      "promotion": "requires_repeat_independent_observations_or_explicit_airway_match"})
    return links

def process_trace(path, airports, fixes, graph_airports, *, include_observed_endpoints=False):
    meta, points = read_points(path)
    if len(points) < 2:
        raise ValueError(f"{path}: fewer than two valid trace points")
    segments = split_flight_legs(points)
    results = []
    for leg_no, segment in enumerate(segments, 1):
        leg_points = segment["points"]
        before, after = segment.get("before_ground", []), segment.get("after_ground", [])
        origin = airport_from_ground(before, airports) if before else None
        destination = airport_from_ground(after, airports) if after else None
        if not origin or not destination:
            fallback_origin, fallback_destination = anchor_airports(leg_points, airports)
            origin, destination = origin or fallback_origin, destination or fallback_destination
        if not origin or not destination:
            raise ValueError(f"{path}: leg {leg_no} airport anchors unresolved ({origin or 'none'}->{destination or 'none'}); segmentation={segment['segmentation']}")
        excluded = any(a.startswith(EXCLUDED_AIRPORT_PREFIXES) for a in (origin, destination))
        if excluded:
            results.append({"excluded": True, "legNumber": leg_no, "origin": origin,
                            "destination": destination, "segmentation": segment["segmentation"],
                            "positionCount": len(leg_points)})
            continue
        if origin not in graph_airports or destination not in graph_airports:
            raise ValueError(f"{path}: leg {leg_no} airport missing from graph: {origin}/{destination}")
        duration_minutes = (leg_points[-1]["t"] - leg_points[0]["t"]) / 60.0
        max_distance_from_origin = max(distance_nm((p["lat"], p["lon"]),
                                      next(( (lat, lon) for ident, lat, lon in airports if ident == origin), (p["lat"], p["lon"])))
                                      for p in leg_points)
        max_alt = max((p.get("altitude_ft") or 0 for p in leg_points), default=0)
        max_speed = max((p.get("groundspeed_kt") or 0 for p in leg_points), default=0)
        if max_alt <= 1000 and max_speed <= 80:
            results.append({"excluded": True, "reason": "GROUND_ONLY_OR_LOW_ACTIVITY",
                            "legNumber": leg_no, "origin": origin, "destination": destination,
                            "segmentation": segment["segmentation"], "positionCount": len(leg_points),
                            "maxAltitudeFt": max_alt, "maxGroundspeedKt": max_speed})
            continue
        local_rtb = origin == destination
        if local_rtb and (duration_minutes <= 15 or max_distance_from_origin <= 15):
            results.append({"excluded": True, "reason": "LOCAL_OR_RTB_BELOW_GUARD",
                            "legNumber": leg_no, "origin": origin, "destination": destination,
                            "segmentation": segment["segmentation"], "positionCount": len(leg_points),
                            "durationMinutes": round(duration_minutes, 1),
                            "maxDistanceFromAirportNm": round(max_distance_from_origin, 1)})
            continue
        matches = match_fixes(leg_points, fixes)
        result={"excluded": False, "legNumber": leg_no, "origin": origin,
                        "destination": destination, "segmentation": segment["segmentation"],
                        "routeType": "LOCAL_OR_RTB" if local_rtb else "POINT_TO_POINT",
                        "durationMinutes": round(duration_minutes, 1),
                        "maxDistanceFromAirportNm": round(max_distance_from_origin, 1),
                        "maxAltitudeFt": max_alt, "maxGroundspeedKt": max_speed,
                        "positionCount": len(leg_points), "matchedFixes": [m["fix"] for m in matches],
                        # Coordinates disambiguate same-name physical FTWG fixes during routing.
                        # Do not retain per-point timestamps or raw aircraft trace rows here.
                        "matchedFixDetails": [{"fix": m["fix"], "lat": m["lat"], "lon": m["lon"],
                                              "distanceNm": m["distanceNm"]} for m in matches],
                        "matchCount": len(matches),
                        "geometry": [[round(p["lat"], 4), round(p["lon"], 4)] for p in leg_points[::max(1, len(leg_points)//100)]],
                        "candidateLinks": candidate_links(matches), "graphComparison": "pending"}
        if include_observed_endpoints:
            # Used only in-memory by the scale diagnostic; never serialize trace coordinates.
            result["_observed_trace_endpoints"]={
                "start":[leg_points[0]["lat"],leg_points[0]["lon"]],
                "end":[leg_points[-1]["lat"],leg_points[-1]["lon"]]}
        results.append(result)
    return results

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trace", action="append", required=True, help="Local readsb trace JSON; repeat for independent samples")
    p.add_argument("--output", default="navigation/adsb_learning/corridor_evidence.json")
    p.add_argument("--waypoints", type=Path, default=ROOT/"navigation/waypoints/flightgear_fixes.csv")
    p.add_argument("--airports", type=Path, default=ROOT/"navigation/airports/ourairports_airports.csv")
    p.add_argument("--graph", type=Path, default=ROOT/"navigation/graph/world_corridor_graph.bin")
    p.add_argument("--altitude-ft", type=int, default=35000)
    args = p.parse_args()
    nodes, graph_airports, adjacency, graph_meta = route_preview.load_graph(args.graph)
    airports, fixes = load_airports(args.airports), []
    with open(args.waypoints, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ident = (row.get("ident") or row.get("id") or row.get("fix_id") or
                     row.get("navaid_id") or row.get("name") or "").strip().upper()
            try:
                lat = float(row.get("lat") or row.get("latitude") or row.get("latitude_deg"))
                lon = float(row.get("lon") or row.get("longitude") or row.get("longitude_deg"))
            except (TypeError, ValueError):
                continue
            if ident and len(ident) <= 8 and -90 <= lat <= 90 and -180 <= lon <= 180:
                fixes.append((ident, lat, lon))
    print(f"[ADS-B] Loaded {len(fixes):,} waypoint/fix coordinates from {args.waypoints.name}", flush=True)
    results, routes = [], []
    for trace in args.trace:
        trace_legs = process_trace(trace, airports, fixes, graph_airports)
        print(f"[ADS-B] {Path(trace).name}: segmented into {len(trace_legs)} leg(s): " +
              ", ".join(f'{r.get("origin","?")}-{r.get("destination","?")} ({r.get("positionCount",0)} points, {r.get("matchCount",0)} fixes)' for r in trace_legs), flush=True)
        for result in trace_legs:
            if not result["excluded"]:
                route = route_preview.find_route(nodes, graph_airports, adjacency, result["origin"], result["destination"], args.altitude_ft)
                result["graphComparison"] = {"status": "path_found", "routeClass": route["routeClass"],
                                             "graphDistanceNm": route["distanceNm"],
                                             "graphFixSequence": route["nodes"],
                                             "observedFixSequence": result["matchedFixes"]}
                routes.append((result["origin"], result["destination"]))
            results.append(result)
    # Only aggregate, de-identified outputs are serialised. No hex/reg/callsign or timestamps.
    corridors = defaultdict(lambda: {"samples": 0, "fixSequences": [], "candidateLinks": [], "geometry": []})
    for r in results:
        if r["excluded"]: continue
        key = f'{r["origin"]}-{r["destination"]}'
        c = corridors[key]; c["samples"] += 1
        c["fixSequences"].append(r["matchedFixes"])
        c["candidateLinks"].extend(r["candidateLinks"])
        c["geometry"].append(r["geometry"])
    payload = {"schemaVersion": 2, "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
               "geographicScope": "non-US; airports beginning K, P, or T excluded",
               "source": "ADSB.lol/readsb historical traces",
               "sourceLicense": "ODbL-1.0; assess attribution and share-alike obligations before redistribution",
               "privacy": "No aircraft hex, registration, callsign, raw trace rows, or per-point timestamps retained.",
               "graph": graph_meta, "traceResults": results, "corridors": dict(corridors),
               "limitations": ["ADS-B tracks are observed trajectories, not filed routes or ATC clearances.",
                               "One sample yields low-confidence inferred links only.",
                               "Legacy FTWG graph is stale and not for operational navigation."]}
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"traces": len(results), "accepted": sum(not r["excluded"] for r in results),
                      "excluded": sum(r["excluded"] for r in results),
                      "corridors": len(corridors), "output": str(out)}, indent=2))

if __name__ == "__main__":
    main()


