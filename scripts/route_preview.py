#!/usr/bin/env python3
"""Offline route preview using FlightTempo's FTWG binary graph.

This is a development/learning route generator, not operational flight planning.
It preserves source airway labels and generated airport connectors separately.
"""
from __future__ import annotations
import argparse, heapq, json, math, struct
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "navigation/graph/world_corridor_graph.bin"
HEADER = struct.Struct("<4sHHIIII")
NODE = struct.Struct("<iiIHH")
EDGE = struct.Struct("<IIIHBBII")

def distance_nm(a, b):
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2-lat1, lon2-lon1
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 3440.065 * 2 * math.asin(min(1.0, math.sqrt(h)))

def load_graph(path):
    raw = path.read_bytes()
    if len(raw) < HEADER.size:
        raise ValueError("Graph file is truncated")
    magic, version, flags, n_nodes, n_edges, string_size, airport_count = HEADER.unpack_from(raw)
    if magic != b"FTWG" or version != 1:
        raise ValueError("Unsupported FTWG graph format")
    pos = HEADER.size
    nodes_raw = [NODE.unpack_from(raw, pos+i*NODE.size) for i in range(n_nodes)]
    pos += n_nodes*NODE.size
    edges_raw = [EDGE.unpack_from(raw, pos+i*EDGE.size) for i in range(n_edges)]
    pos += n_edges*EDGE.size
    strings = raw[pos:pos+string_size]
    if len(strings) != string_size:
        raise ValueError("Graph string table is truncated")
    nodes = []
    airport_ids = {}
    for i, (lat, lon, off, length, node_flags) in enumerate(nodes_raw):
        ident = strings[off:off+length].decode("utf-8", "replace").upper()
        nodes.append((lat/1e7, lon/1e7, ident, node_flags))
        if node_flags == 1:
            airport_ids[ident] = i
    adjacency = defaultdict(list)
    for a,b,off,length,level,kind,min_alt,max_alt in edges_raw:
        name = strings[off:off+length].decode("utf-8", "replace")
        adjacency[a].append((b,name,level,kind,min_alt,max_alt))
        adjacency[b].append((a,name,level,kind,min_alt,max_alt))
    return nodes, airport_ids, adjacency, {
        "version":version,"nodeCount":n_nodes,"edgeCount":n_edges,
        "airportCount":airport_count,"stringBytes":string_size
    }

def find_route(nodes, airport_ids, adjacency, origin, destination, altitude_ft):
    origin, destination = origin.upper(), destination.upper()
    if origin not in airport_ids or destination not in airport_ids:
        missing = [x for x in (origin,destination) if x not in airport_ids]
        raise ValueError("Airport(s) absent from graph: " + ", ".join(missing))
    start, goal = airport_ids[origin], airport_ids[destination]
    goal_pos = nodes[goal][:2]
    def heuristic(i): return distance_nm(nodes[i][:2], goal_pos)
    queue = [(heuristic(start), 0.0, start)]
    best, previous = {start:0.0}, {}
    while queue:
        _, cost, cur = heapq.heappop(queue)
        if cost != best.get(cur): continue
        if cur == goal: break
        for nxt,name,level,kind,min_alt,max_alt in adjacency.get(cur,[]):
            if kind == 0 and ((min_alt and altitude_ft < min_alt) or (max_alt and altitude_ft > max_alt)):
                continue
            step = distance_nm(nodes[cur][:2], nodes[nxt][:2])
            new_cost = cost + step
            if new_cost < best.get(nxt, float("inf")):
                best[nxt] = new_cost
                previous[nxt] = (cur,name,level,kind)
                heapq.heappush(queue,(new_cost+heuristic(nxt),new_cost,nxt))
    if goal not in best: raise RuntimeError("No path found in current graph at requested altitude")
    chain, cur = [], goal
    while cur != start:
        parent,name,level,kind = previous[cur]
        chain.append({"from":nodes[parent][2],"to":nodes[cur][2],
                      "edge":name,"edgeType":"source_airway" if kind == 0 else "synthetic_airport_connector",
                      "levelCode":level})
        cur = parent
    chain.reverse()
    return {
        "origin":origin,"destination":destination,"altitudeFt":altitude_ft,
        "distanceNm":round(best[goal],1),
        "routeClass":"generated_candidate","status":"candidate",
        "nodes":[nodes[start][2]]+[x["to"] for x in chain],
        "legs":chain,
        "warning":"Legacy graph preview only; not current AIRAC, not checked for NOTAMs, airspace restrictions, procedures, one-way rules or operational suitability."
    }

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("origin", help="Origin ICAO")
    p.add_argument("destination", help="Destination ICAO")
    p.add_argument("--altitude-ft",type=int,default=35000)
    p.add_argument("--graph",type=Path,default=GRAPH)
    args=p.parse_args()
    nodes,airports,adj,meta=load_graph(args.graph)
    result=find_route(nodes,airports,adj,args.origin,args.destination,args.altitude_ft)
    result["graph"]=meta
    print(json.dumps(result,indent=2))
if __name__ == "__main__": main()
