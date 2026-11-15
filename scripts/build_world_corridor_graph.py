#!/usr/bin/env python3
"""Build FlightTempo's compact worldwide airport-to-airway graph.

Input: imported legacy AWY640 segment CSV plus the existing airport reference.
Output: navigation/graph/world_corridor_graph.bin and graph metadata.

The graph is a development route-preview graph. It is not an operational route
or procedure database. Airport connectors are generated straight-line links to
nearby airway nodes; they are not SIDs, STARs or ATC clearances.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import math
import struct
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AIRWAYS = ROOT / "navigation/airways/flightgear_airway_segments.csv"
AIRPORTS = ROOT / "airports/airports.csv"
OUT_DIR = ROOT / "navigation/graph"
OUT_BIN = OUT_DIR / "world_corridor_graph.bin"
OUT_META = OUT_DIR / "meta.json"

HEADER = struct.Struct("<4sHHIIII")
NODE = struct.Struct("<iiIHH")
EDGE = struct.Struct("<IIIHBBII")
MAGIC = b"FTWG"
VERSION = 1
CELL_DEG = 2.0
CONNECTOR_RADIUS_NM = 150.0
CONNECTORS_PER_AIRPORT = 3


def valid_coord(lat, lon):
    return math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180


def haversine_nm(a_lat, a_lon, b_lat, b_lon):
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3440.065 * 2 * math.asin(min(1.0, math.sqrt(h)))


def cell(lat, lon):
    return (math.floor((lat + 90.0) / CELL_DEG), math.floor((lon + 180.0) / CELL_DEG))


def read_airways(path):
    segments = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                a_lat, a_lon = float(row["from_latitude"]), float(row["from_longitude"])
                b_lat, b_lon = float(row["to_latitude"]), float(row["to_longitude"])
                level = str(row.get("level_code", ""))
                min_alt = int(float(row.get("minimum_altitude_ft") or 0))
                max_alt = int(float(row.get("maximum_altitude_ft") or 0))
            except (KeyError, TypeError, ValueError):
                continue
            if not valid_coord(a_lat, a_lon) or not valid_coord(b_lat, b_lon):
                continue
            if level not in {"1", "2"}:
                continue
            segments.append({
                "from_ident": row.get("from_ident", "").strip().upper(),
                "to_ident": row.get("to_ident", "").strip().upper(),
                "from": (round(a_lat * 1e7), round(a_lon * 1e7)),
                "to": (round(b_lat * 1e7), round(b_lon * 1e7)),
                "airway": row.get("airway_names", "").strip(),
                "level": int(level),
                "min_alt": max(0, min_alt),
                "max_alt": max(0, max_alt),
            })
    if not segments:
        raise RuntimeError("No valid low/high airway segments were found; graph not built")
    return segments


def read_airports(path):
    airports = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        # FlightTempo CSVs may begin with a #version directive; skip it so
        # DictReader sees the actual column header.
        lines = (line for line in f if not line.lstrip().startswith("#version") and not line.lstrip().lower().startswith("sep="))
        reader = csv.DictReader(lines)
        for row in reader:
            icao = (row.get("icao") or "").strip().upper()
            try:
                lat, lon = float(row["latitude"]), float(row["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            if len(icao) != 4 or not valid_coord(lat, lon):
                continue
            airports.append({
                "icao": icao,
                "name": (row.get("name") or "").strip(),
                "lat": round(lat * 1e7),
                "lon": round(lon * 1e7),
            })
    return airports


def route_smoke_test(start_icao, end_icao, airport_node_ids, node_rows, edge_rows, strings):
    start = airport_node_ids.get(start_icao)
    goal = airport_node_ids.get(end_icao)
    if start is None or goal is None:
        return {"from": start_icao, "to": end_icao, "status": "airport_not_in_graph"}

    adjacency = defaultdict(list)
    for edge in edge_rows:
        a, b, name_off, name_len, level, kind, min_alt, max_alt = edge
        a_lat, a_lon = node_rows[a][0] / 1e7, node_rows[a][1] / 1e7
        b_lat, b_lon = node_rows[b][0] / 1e7, node_rows[b][1] / 1e7
        distance = haversine_nm(a_lat, a_lon, b_lat, b_lon)
        name = strings[name_off:name_off + name_len].decode("utf-8", errors="replace")
        adjacency[a].append((b, distance, name, kind))
        adjacency[b].append((a, distance, name, kind))

    goal_lat, goal_lon = node_rows[goal][0] / 1e7, node_rows[goal][1] / 1e7
    def heuristic(node_id):
        lat, lon = node_rows[node_id][0] / 1e7, node_rows[node_id][1] / 1e7
        return haversine_nm(lat, lon, goal_lat, goal_lon)

    queue = [(heuristic(start), 0.0, start)]
    best = {start: 0.0}
    previous = {}
    expanded = 0
    while queue and expanded < 300000:
        _, cost, current = heapq.heappop(queue)
        if cost != best.get(current):
            continue
        if current == goal:
            names = []
            cursor = goal
            while cursor != start:
                parent, name, kind = previous[cursor]
                if kind == 0 and name and name not in names:
                    names.append(name)
                cursor = parent
            names.reverse()
            return {
                "from": start_icao, "to": end_icao, "status": "path_found",
                "distanceNm": round(cost, 1), "nodeCount": len(previous) + 1,
                "airwayNames": names[:100], "expandedNodes": expanded
            }
        expanded += 1
        for neighbour, distance, name, kind in adjacency.get(current, []):
            candidate = cost + distance
            if candidate < best.get(neighbour, float("inf")):
                best[neighbour] = candidate
                previous[neighbour] = (current, name, kind)
                heapq.heappush(queue, (candidate + heuristic(neighbour), candidate, neighbour))
    return {
        "from": start_icao, "to": end_icao,
        "status": "no_path" if not queue else "search_limit_reached",
        "expandedNodes": expanded
    }


def build_graph(segments, airports):
    # Airway nodes are keyed by exact source coordinates, so adjacent legacy
    # segments sharing a coordinate join even when identifiers are homonyms.
    node_index = {}
    node_rows = []
    edge_rows = []
    strings = bytearray()

    def add_string(value):
        raw = (value or "").encode("utf-8")
        offset = len(strings)
        strings.extend(raw)
        return offset, len(raw)

    def add_node(lat_e7, lon_e7, ident, flags):
        key = (lat_e7, lon_e7, flags)
        existing = node_index.get(key)
        if existing is not None:
            return existing
        ident_off, ident_len = add_string(ident)
        idx = len(node_rows)
        node_rows.append((lat_e7, lon_e7, ident_off, ident_len, flags))
        node_index[key] = idx
        return idx

    airway_node_ids = set()
    for seg in segments:
        a = add_node(*seg["from"], seg["from_ident"], 0)
        b = add_node(*seg["to"], seg["to_ident"], 0)
        airway_node_ids.add(a)
        airway_node_ids.add(b)
        name_off, name_len = add_string(seg["airway"])
        # Edge kind 0 = published source airway segment; direction 0 = both.
        edge_rows.append((a, b, name_off, name_len, seg["level"], 0,
                          seg["min_alt"], seg["max_alt"]))

    # Spatial buckets make nearest-airway airport connectors practical to build
    # without a quadratic airport x waypoint scan.
    grid = defaultdict(list)
    airway_coords = {}
    for idx in airway_node_ids:
        lat = node_rows[idx][0] / 1e7
        lon = node_rows[idx][1] / 1e7
        grid[cell(lat, lon)].append(idx)
        airway_coords[idx] = (lat, lon)

    connector_count = 0
    airport_node_ids = {}
    for airport in airports:
        airport_idx = add_node(airport["lat"], airport["lon"], airport["icao"], 1)
        airport_node_ids[airport["icao"]] = airport_idx
        lat, lon = airport["lat"] / 1e7, airport["lon"] / 1e7
        lat_cell, lon_cell = cell(lat, lon)
        lat_span = math.ceil((CONNECTOR_RADIUS_NM / 60.0) / CELL_DEG) + 1
        cos_lat = max(0.08, abs(math.cos(math.radians(lat))))
        lon_span = min(90, math.ceil((CONNECTOR_RADIUS_NM / 60.0 / cos_lat) / CELL_DEG) + 1)
        candidates = set()
        for y in range(max(0, lat_cell - lat_span), min(90, lat_cell + lat_span) + 1):
            for x in range(max(0, lon_cell - lon_span), min(179, lon_cell + lon_span) + 1):
                candidates.update(grid.get((y, x), ()))
        nearest = []
        for node_id in candidates:
            nlat, nlon = airway_coords[node_id]
            distance = haversine_nm(lat, lon, nlat, nlon)
            if distance <= CONNECTOR_RADIUS_NM:
                nearest.append((distance, node_id))
        nearest.sort()
        for distance, node_id in nearest[:CONNECTORS_PER_AIRPORT]:
            # Edge kind 1 = generated airport-to-airway connector, not a SID/STAR.
            name_off, name_len = add_string(f"DIRECT_CONNECTOR:{airport['icao']}:{distance:.1f}NM")
            edge_rows.append((airport_idx, node_id, name_off, name_len, 0, 1, 0, 0))
            connector_count += 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_BIN.open("wb") as f:
        f.write(HEADER.pack(MAGIC, VERSION, 0, len(node_rows), len(edge_rows), len(strings), len(airport_node_ids)))
        for row in node_rows:
            f.write(NODE.pack(*row))
        for row in edge_rows:
            f.write(EDGE.pack(*row))
        f.write(strings)

    raw = OUT_BIN.read_bytes()
    smoke_tests = [
        route_smoke_test("EBBR", "RJAA", airport_node_ids, node_rows, edge_rows, strings),
        route_smoke_test("EBBR", "EDDM", airport_node_ids, node_rows, edge_rows, strings),
        route_smoke_test("LFPG", "EDDM", airport_node_ids, node_rows, edge_rows, strings),
    ]
    meta = {
        "schemaVersion": 1,
        "format": "FlightTempo World Corridor Graph",
        "file": OUT_BIN.name,
        "magic": MAGIC.decode("ascii"),
        "formatVersion": VERSION,
        "byteOrder": "little_endian",
        "headerStruct": HEADER.format,
        "nodeStruct": NODE.format,
        "edgeStruct": EDGE.format,
        "nodeCount": len(node_rows),
        "airwayNodeCount": len(airway_node_ids),
        "airportNodeCount": len(airport_node_ids),
        "airwayEdgeCount": len(segments),
        "airportConnectorEdgeCount": connector_count,
        "edgeCount": len(edge_rows),
        "lowAirwayEdgeCount": sum(x["level"] == 1 for x in segments),
        "highAirwayEdgeCount": sum(x["level"] == 2 for x in segments),
        "source": "ptsmonteiro/x-plane-navdata legacy AWY640, with FlightTempo OurAirports airport connectors",
        "sourceCycleToken": "2012.08",
        "airacCycle": None,
        "licenceStatus": "GPL-3.0_derived_data; source attribution and full GPL notice retained",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sizeBytes": len(raw),
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "routeSmokeTests": smoke_tests,
        "connectorPolicy": {
            "maxDistanceNm": CONNECTOR_RADIUS_NM,
            "connectorsPerAirport": CONNECTORS_PER_AIRPORT,
            "meaning": "Generated direct links from airport reference coordinates to nearby airway graph nodes; not published SID/STAR procedure geometry."
        },
        "limitations": [
            "Legacy snapshot from 2012.08; not current AIRAC.",
            "AWY640 has no one-way direction field; airway edges are treated as bidirectional for route-preview only.",
            "No vertical airspace, FIR restriction, NOTAM or operator-rule checks are embedded in this graph.",
            "Airport connectors are synthetic graph links and must never be displayed as published procedures or ATC clearances.",
            "The graph is for development route previews only, not operational flight planning or navigation."
        ]
    }
    OUT_META.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--airways", type=Path, default=AIRWAYS)
    parser.add_argument("--airports", type=Path, default=AIRPORTS)
    args = parser.parse_args()
    build_graph(read_airways(args.airways), read_airports(args.airports))


if __name__ == "__main__":
    main()
