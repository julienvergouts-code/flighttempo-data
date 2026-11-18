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
        points.append({"t": epoch + sec, "lat": lat, "lon": lon,
                       "ground": bool(flags & 2)})
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

def process_trace(path, airports, fixes, graph_airports):
    meta, points = read_points(path)
    if len(points) < 2:
        raise ValueError(f"{path}: fewer than two valid trace points")
    origin, destination = anchor_airports(points, airports)
    if not origin or not destination:
        def nearest_summary(window):
            samples = []
            for point in window:
                if not airports:
                    continue
                distance, ident = min(
                    (distance_nm((point["lat"], point["lon"]), (lat, lon)), ident)
                    for ident, lat, lon in airports
                )
                samples.append((distance, ident))
            if not samples:
                return "no-airport-reference"
            distance, ident = min(samples)
            return f"{ident}:{distance:.1f}NM"
        raise ValueError(
            f"{path}: unable to establish both airport anchors "
            f"(origin={origin or 'none'}, destination={destination or 'none'}, "
            f"ground_samples={sum(1 for point in points if point['ground'])}, "
            f"nearest_start={nearest_summary(points[:10])}, "
            f"nearest_end={nearest_summary(list(reversed(points[-10:])))})"
        )
    if any(a.startswith(EXCLUDED_AIRPORT_PREFIXES) for a in (origin, destination)):
        return {"excluded": True, "reason": "US/territory airport prefix", "origin": origin, "destination": destination}
    if origin not in graph_airports or destination not in graph_airports:
        raise ValueError(f"{path}: airport missing from FTWG graph: {origin}/{destination}")
    matches = match_fixes(points, fixes)
    return {"excluded": False, "origin": origin, "destination": destination,
            "positionCount": len(points), "matchedFixes": [m["fix"] for m in matches],
            "matchCount": len(matches), "geometry": [[round(p["lat"], 4), round(p["lon"], 4)] for p in points[::max(1, len(points)//100)]],
            "candidateLinks": candidate_links(matches),
            "graphComparison": "pending"}

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
            try: fixes.append((row["id"], float(row["latitude"]), float(row["longitude"])))
            except (KeyError, ValueError): continue
    results, routes = [], []
    for trace in args.trace:
        result = process_trace(trace, airports, fixes, graph_airports)
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
