#!/usr/bin/env python3
"""Read-only FTWG graph diagnostics for an ADS-B benchmark artifact.

Loads the same RepositoryNavDatabase and compiled FTWG binary as the benchmark.
Does not modify navigation files, graph data, or benchmark artifacts.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any
import sys

# Ensure repository-root imports work when this file is executed as a script in CI.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIVE_LETTER_RE = re.compile(r"^[A-Z]{5}$")
CODED_FIX_RE = re.compile(r"^[A-Z]{2,4}\d{1,3}$")
FTWG_HEADER = struct.Struct("<4sHHII")
FTWG_NODE = struct.Struct("<8siiB3x")
FTWG_EDGE = struct.Struct("<IIH6s")
DEFAULT_NAMED_FIXES = [
    "EKPEK", "LIZUM", "ROKIB", "LAMPO", "NIBAN", "TUSET", "VELIP",
    "OBALA", "LAMGO", "LIRSU", "NOSPA", "NTM01",
]


def normalize(value: Any) -> str:
    return str(value or "").strip().upper()


def classify_ident(ident: str) -> str:
    if FIVE_LETTER_RE.fullmatch(ident):
        return "five_letter_fix"
    if CODED_FIX_RE.fullmatch(ident):
        return "coded_alphanumeric"
    return "other_identifier"


def load_json_prefix(path: Path) -> tuple[Any, str]:
    raw = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    value, end = decoder.raw_decode(raw.lstrip())
    trailing = raw.lstrip()[end:].strip()
    return value, trailing


def read_ftwg_header(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"present": False, "path": str(path)}
    with path.open("rb") as stream:
        header = stream.read(FTWG_HEADER.size)
    if len(header) != FTWG_HEADER.size:
        return {"present": True, "path": str(path), "file_bytes": path.stat().st_size,
                "header_error": "truncated_header"}
    magic, version, flags, nodes, edges = FTWG_HEADER.unpack(header)
    return {
        "present": True, "path": str(path), "file_bytes": path.stat().st_size,
        "magic": magic.decode("ascii", errors="replace"), "version": version,
        "flags": flags, "physical_node_count": nodes, "physical_edge_count": edges,
        "expected_file_bytes": FTWG_HEADER.size + nodes * FTWG_NODE.size + edges * FTWG_EDGE.size,
        "size_matches_header": path.stat().st_size == FTWG_HEADER.size + nodes * FTWG_NODE.size + edges * FTWG_EDGE.size,
    }


def iter_edges(raw: Any) -> list[tuple[str, float | None, str | None]]:
    edges: list[tuple[str, float | None, str | None]] = []
    if isinstance(raw, dict):
        for target, meta in raw.items():
            dst = normalize(target)
            distance = airway = None
            if isinstance(meta, dict):
                value = meta.get("distance", meta.get("dist", meta.get("weight")))
                if isinstance(value, (int, float)):
                    distance = float(value)
                airway_value = meta.get("airway")
                airway = str(airway_value) if airway_value is not None else None
            elif isinstance(meta, (int, float)):
                distance = float(meta)
            if dst:
                edges.append((dst, distance, airway))
    elif isinstance(raw, (list, tuple, set)):
        for item in raw:
            if isinstance(item, (list, tuple)) and item:
                dst = normalize(item[0])
                distance = float(item[1]) if len(item) > 1 and isinstance(item[1], (int, float)) else None
                airway = str(item[2]) if len(item) > 2 and item[2] is not None else None
                if dst:
                    edges.append((dst, distance, airway))
            elif item is not None:
                dst = normalize(item)
                if dst:
                    edges.append((dst, None, None))
    return edges


def graph_metrics(adj: dict[str, Any]) -> tuple[dict[str, int], dict[str, int], dict[str, set[str]], int]:
    indegree: dict[str, int] = defaultdict(int)
    outdegree: dict[str, int] = defaultdict(int)
    undirected: dict[str, set[str]] = defaultdict(set)
    edge_count = 0
    for raw_src, raw_targets in adj.items():
        src = normalize(raw_src)
        if not src:
            continue
        undirected.setdefault(src, set())
        indegree.setdefault(src, 0)
        outdegree.setdefault(src, 0)
        edges = iter_edges(raw_targets)
        outdegree[src] += len(edges)
        edge_count += len(edges)
        for dst, _, _ in edges:
            indegree[dst] += 1
            undirected[src].add(dst)
            undirected[dst].add(src)
            outdegree.setdefault(dst, 0)
    return dict(indegree), dict(outdegree), dict(undirected), edge_count


def weak_components(undirected: dict[str, set[str]]) -> tuple[dict[str, int], dict[int, int]]:
    ids: dict[str, int] = {}
    sizes: dict[int, int] = {}
    component = 0
    for start in sorted(undirected):
        if start in ids:
            continue
        component += 1
        queue = deque([start])
        ids[start] = component
        size = 0
        while queue:
            node = queue.popleft()
            size += 1
            for nxt in undirected.get(node, ()):
                if nxt not in ids:
                    ids[nxt] = component
                    queue.append(nxt)
        sizes[component] = size
    return ids, sizes


def probe_astar(nav: Any, adj: dict[str, Any], start: str | None, goal: str | None,
                label: str, start_coord: tuple[float,float] | None = None,
                goal_coord: tuple[float,float] | None = None) -> dict[str, Any]:
    result = {"probe": label, "start": start, "goal": goal, "attempted": False,
              "connected": False, "path": None, "cost_nm": None, "reason": None}
    if not start or not goal:
        result["reason"] = "missing_endpoint"
        return result
    result["start_in_ident_adj"] = start in adj
    result["goal_in_ident_adj"] = goal in adj
    if start not in adj or goal not in adj:
        result["reason"] = "endpoint_not_in_identifier_adjacency"
        return result
    result["attempted"] = True
    try:
        raw = nav.a_star_connected(start, goal, start_coord, goal_coord)
    except Exception as exc:
        result["reason"] = f"astar_exception:{type(exc).__name__}:{exc}"
        return result
    if raw is None:
        result["reason"] = "no_directed_path"
        return result
    if isinstance(raw, tuple) and len(raw) == 2:
        path, cost = raw
        if isinstance(path, (list, tuple)):
            result["path"] = list(path)
            result["connected"] = bool(path)
            result["physical_path"] = getattr(nav,"last_route_physical_path",None)
            result["endpoint_resolution"] = getattr(nav,"last_route_endpoint_resolution",None)
        result["cost_nm"] = cost
        result["reason"] = None if result["connected"] else "astar_returned_unrecognized_path"
    else:
        result["reason"] = f"unexpected_astar_return_type:{type(raw).__name__}"
        result["return_value_type"] = type(raw).__name__
    return result


def extract_legs(result_payload: Any) -> list[dict[str, Any]]:
    if not isinstance(result_payload, dict):
        return []
    rows = result_payload.get("traceResults")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def extract_fixes(leg: dict[str, Any]) -> list[str]:
    fixes = leg.get("matchedFixes")
    if not isinstance(fixes, list):
        return []
    return [normalize(item) for item in fixes if item is not None and normalize(item)]


def diagnostics_by_leg(evidence: Any) -> dict[str, dict[str, Any]]:
    raw = evidence.get("leg_diagnostics", []) if isinstance(evidence, dict) else []
    out: dict[str, dict[str, Any]] = {}
    if isinstance(raw, list):
        for row in raw:
            if not isinstance(row, dict):
                continue
            key = str(row.get("leg") if row.get("leg") is not None else row.get("leg_index", ""))
            if key:
                out[key] = row
    elif isinstance(raw, dict):
        out = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    return out


def build_report(result_payload: Any, evidence_payload: Any, nav: Any,
                 binary_header: dict[str, Any], evidence_trailing_text: str) -> dict[str, Any]:
    coords_raw = getattr(nav, "fix_coords_by_ident", {})
    adj_raw = getattr(nav, "adj", {})
    coords = {normalize(k): v for k, v in coords_raw.items()} if isinstance(coords_raw, dict) else {}
    adj = {normalize(k): v for k, v in adj_raw.items()} if isinstance(adj_raw, dict) else {}
    indegree, outdegree, undirected, edge_count = graph_metrics(adj)
    wcc_ids, wcc_sizes = weak_components(undirected)
    legs = extract_legs(result_payload)
    diag_map = diagnostics_by_leg(evidence_payload)

    if not legs:
        raise RuntimeError("No traceResults legs parsed from benchmark result; refusing empty diagnostic report")

    fix_rows: list[dict[str, Any]] = []
    leg_rows: list[dict[str, Any]] = []
    occurrences: list[str] = []
    legs_present: Counter[str] = Counter()

    for leg_index, leg in enumerate(legs, 1):
        leg_number = leg.get("legNumber", leg_index)
        diag = diag_map.get(str(leg_number), diag_map.get(str(leg_index), {}))
        origin = leg.get("origin")
        destination = leg.get("destination")
        route = f"{origin or '?'}->{destination or '?'}"
        fixes = extract_fixes(leg)
        occurrences.extend(fixes)
        legs_present.update(set(fixes))

        in_coords = [f for f in fixes if f in coords]
        in_adj = [f for f in fixes if f in adj]
        usable = [f for f in in_adj if indegree.get(f, 0) + outdegree.get(f, 0) > 0]

        for seq, fix in enumerate(fixes):
            component = wcc_ids.get(fix)
            fix_rows.append({
                "leg_index": leg_index, "leg_number": leg_number, "route": route,
                "sequence_index": seq, "ident": fix, "ident_type": classify_ident(fix),
                "graph_coordinate": coords.get(fix),
                "in_fix_coords_by_ident": fix in coords, "in_ident_adjacency": fix in adj,
                "ident_in_degree": indegree.get(fix, 0), "ident_out_degree": outdegree.get(fix, 0),
                "ident_wcc_id": component, "ident_wcc_size": wcc_sizes.get(component, 0) if component is not None else 0,
            })

        first, last = fixes[0] if fixes else None, fixes[-1] if fixes else None
        first_adj, last_adj = (in_adj[0] if in_adj else None), (in_adj[-1] if in_adj else None)
        first_usable, last_usable = (usable[0] if usable else None), (usable[-1] if usable else None)
        matched_details=leg.get("matchedFixDetails",[])
        details_by_fix={}
        if isinstance(matched_details,list):
            for row in matched_details:
                if isinstance(row,dict) and row.get("fix"):
                    try: details_by_fix.setdefault(normalize(row["fix"]),[]).append((float(row["lat"]),float(row["lon"])))
                    except (TypeError,ValueError,KeyError): pass
        raw_start_coord=details_by_fix.get(first,[None])[0] if first else None
        raw_goal_coord=details_by_fix.get(last,[None])[-1] if last else None
        adj_start_coord=details_by_fix.get(first_adj,[None])[0] if first_adj else None
        adj_goal_coord=details_by_fix.get(last_adj,[None])[-1] if last_adj else None
        selected_coords=diag.get("selected_endpoint_coordinates",[]) if isinstance(diag,dict) else []
        selected_start_coord=tuple(selected_coords[0]) if len(selected_coords)>0 and selected_coords[0] else None
        selected_goal_coord=tuple(selected_coords[1]) if len(selected_coords)>1 and selected_coords[1] else None
        leg_rows.append({
            "leg_index": leg_index, "leg_number": leg_number, "route": route,
            "excluded": bool(leg.get("excluded", False)), "matched_count": len(fixes),
            "in_fix_coords_count": len(in_coords), "in_ident_adjacency_count": len(in_adj),
            "usable_adjacency_count": len(usable), "benchmark_diagnostic_snapshot": diag,
            "raw_observed_endpoints": [first, last],
            "first_last_adjacency_endpoints_skipping_non_adj_fixes": [first_adj, last_adj],
            "first_last_usable_endpoints_skipping_non_adj_or_degree_zero_fixes": [first_usable, last_usable],
            "astar_raw_endpoints": probe_astar(nav, adj, first, last, "raw_observed_endpoints", raw_start_coord, raw_goal_coord),
            "astar_first_last_adjacency_endpoints": probe_astar(nav, adj, first_adj, last_adj, "skips_non_adjacency_fixes", adj_start_coord, adj_goal_coord),
            "astar_first_last_usable_endpoints": probe_astar(nav, adj, first_usable, last_usable, "skips_non_adjacency_and_degree_zero_fixes", selected_start_coord, selected_goal_coord),
        })

    unique = sorted(set(occurrences))
    coord_only = [ident for ident in unique if ident in coords and ident not in adj]
    absent_both = [ident for ident in unique if ident not in coords and ident not in adj]
    repeated = []
    for ident, count_legs in legs_present.most_common():
        if count_legs < 2:
            continue
        repeated.append({
            "ident": ident, "ident_type": classify_ident(ident), "legs_present": count_legs,
            "total_occurrences": occurrences.count(ident), "in_fix_coords_by_ident": ident in coords,
            "in_ident_adjacency": ident in adj, "coord_map_only": ident in coords and ident not in adj,
            "absent_from_both": ident not in coords and ident not in adj,
            "ident_in_degree": indegree.get(ident, 0), "ident_out_degree": outdegree.get(ident, 0),
            "ident_wcc_id": wcc_ids.get(ident),
        })

    named = sorted(set(DEFAULT_NAMED_FIXES) | set(unique))
    named_rows = [{
        "ident": ident, "in_matched_traces": ident in unique, "trace_occurrences": occurrences.count(ident),
        "in_fix_coords_by_ident": ident in coords, "in_ident_adjacency": ident in adj,
        "ident_in_degree": indegree.get(ident, 0), "ident_out_degree": outdegree.get(ident, 0),
        "ident_wcc_id": wcc_ids.get(ident), "ident_wcc_size": wcc_sizes.get(wcc_ids.get(ident), 0),
    } for ident in named]

    graph_source = getattr(nav, "graph_source", "UNKNOWN")
    return {
        "status": "complete", "read_only": True, "graph_source": graph_source,
        "loader_used": "RepositoryNavDatabase() + _load_airways(); same repository FTWG binary as benchmark",
        "representation_note": "Coverage degrees/WCCs remain identifier-keyed legacy metrics. Route probes use physical FTWG node indices and matched coordinates to disambiguate duplicate identifiers; WCCs are weak (edges treated undirected), while route search is directed.",
        "benchmark_result_parse": {"traceResults_legs_parsed": len(legs), "matched_fix_occurrences": len(occurrences)},
        "benchmark_evidence_parse": {"leg_diagnostics_entries": len(diag_map), "trailing_non_json_text_present": bool(evidence_trailing_text)},
        "1_graph_provenance_and_counts": {
            "binary_header": binary_header, "graph_source": graph_source,
            "fix_coords_by_ident_key_count": len(coords), "ident_adjacency_key_count": len(adj),
            "physical_node_count": len(getattr(nav,"physical_nodes",[])),
            "physical_adjacency_node_count": len(getattr(nav,"physical_adj",{})),
            "physical_directed_edge_count": sum(len(v) for v in getattr(nav,"physical_adj",{}).values()),
            "duplicate_identifier_count": sum(1 for v in getattr(nav,"nodes_by_ident",{}).values() if len(v)>1),
            "admissible_heuristic_scale": getattr(nav,"heuristic_scale",0.0),
            "identifier_directed_edge_count": edge_count, "identifier_wcc_node_count": len(undirected),
            "identifier_wcc_count": len(wcc_sizes), "largest_identifier_wcc_size": max(wcc_sizes.values(), default=0),
            "benchmark_graph_summary": (result_payload.get("summary", {}) if isinstance(result_payload, dict) else {}),
            "recorder_summary": (evidence_payload.get("summary", {}) if isinstance(evidence_payload, dict) else {}),
        },
        "2_per_fix_audit": fix_rows,
        "3_per_leg_probes": leg_rows,
        "4_repeated_identifier_diagnostics": {
            "total_matched_occurrences": len(occurrences), "unique_matched_identifiers": len(unique),
            "unique_coord_map_only_count": len(coord_only), "unique_coord_map_only": coord_only,
            "unique_absent_from_both_count": len(absent_both), "unique_absent_from_both": absent_both,
            "repeated_across_multiple_legs": repeated,
        },
        "5_named_fix_audit": named_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only FTWG benchmark diagnostics")
    parser.add_argument("--benchmark-result", type=Path, required=True, help="Builder result JSON containing traceResults")
    parser.add_argument("--benchmark-evidence", type=Path, required=True, help="Recorder evidence JSON containing leg_diagnostics")
    parser.add_argument("--ftwg-bin", type=Path, default=Path("navigation/graph/ftwg_navgraph.bin"))
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args()

    result_payload, _ = load_json_prefix(args.benchmark_result)
    evidence_payload, trailing = load_json_prefix(args.benchmark_evidence)
    header = read_ftwg_header(args.ftwg_bin)

    from pipeline.build_corridors import RepositoryNavDatabase
    nav = RepositoryNavDatabase()
    nav._load_airways()
    if not str(getattr(nav, "graph_source", "")).startswith("FTWG_BINARY"):
        raise RuntimeError(f"Refusing diagnostic against fallback/unavailable graph: graph_source={nav.graph_source}")
    if not header.get("present") or not header.get("size_matches_header"):
        raise RuntimeError(f"Compiled FTWG binary header/file size validation failed: {header}")

    report = build_report(result_payload, evidence_payload, nav, header, trailing)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")
    print(f"FTWG diagnostic complete: legs={report['benchmark_result_parse']['traceResults_legs_parsed']}, fixes={report['benchmark_result_parse']['matched_fix_occurrences']}, output={args.out_json}")


if __name__ == "__main__":
    main()
