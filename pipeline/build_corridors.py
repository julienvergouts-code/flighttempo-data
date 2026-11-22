#!/usr/bin/env python3
"""Fetch and validate one real ADSB.lol historical readsb trace.\n\nAirport-anchor failures include nearest terminal distances for diagnosis.

Benchmark-only by design. It never fabricates data and never publishes raw traces.
Global whole-sky ingestion is intentionally gated until this path has been validated.
"""
from __future__ import annotations
import argparse
import gzip
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import Iterator

import requests

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "adsb_learning" / "build_corridors.py"
API = "https://api.github.com/repos/adsblol/globe_history_{year}/releases/tags/{tag}"
CHUNK = 1024 * 1024

import csv
import heapq
import math
import struct

REPO_ROOT = Path(__file__).resolve().parents[1]
PATH_FTWG_BIN = REPO_ROOT / "navigation" / "graph" / "ftwg_navgraph.bin"
PATH_AIRWAYS = REPO_ROOT / "navigation" / "airways" / "flightgear_airway_segments.csv"
PATH_FIXES = REPO_ROOT / "navigation" / "waypoints" / "flightgear_fixes.csv"
FTWG_MAGIC = b"FTWG"
FTWG_HEADER = struct.Struct("<4sHHII")
FTWG_NODE = struct.Struct("<8siiB3x")
FTWG_EDGE = struct.Struct("<IIH6s")
PHYSICAL_FIX_RESOLUTION_RADIUS_NM = 5.0

def _nm(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = math.radians(b[0]-a[0]), math.radians(b[1]-a[1])
    q = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*3440.065*math.atan2(math.sqrt(q), math.sqrt(1-q))

class RepositoryNavDatabase:
    """FTWG v1 reader preserving physical node identity; CSV is a tagged fallback."""
    def __init__(self):
        # Legacy identifier maps are retained for coverage metrics only. Routing uses
        # physical node indices so duplicate names cannot teleport between locations.
        self.fix_coords_by_ident = {}
        self.adj = {}
        self.physical_nodes = []
        self.physical_adj = {}
        self.nodes_by_ident = {}
        self.heuristic_scale = 0.0
        self.last_route_physical_path = []
        self.last_route_endpoint_resolution = {}
        self.physical_in_degree_nodes = set()
        self.graph_source = "UNAVAILABLE"

    def _load_airways(self):
        if PATH_FTWG_BIN.exists():
            try:
                self._load_ftwg_binary(PATH_FTWG_BIN)
                return
            except Exception as exc:
                print(f"[NAV] Warning: invalid FTWG binary ({exc}); falling back to CSV.")
                self.adj.clear()
                self.fix_coords_by_ident.clear()
                self.physical_nodes.clear()
                self.physical_adj.clear()
                self.nodes_by_ident.clear()
                self.physical_in_degree_nodes.clear()
                self.heuristic_scale=0.0
        if not PATH_FIXES.exists() or not PATH_AIRWAYS.exists():
            print("[NAV] FTWG binary and CSV fallback unavailable.")
            return
        with PATH_FIXES.open(newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                ident=(row.get("ident") or row.get("id") or row.get("fix_id") or "").strip().upper()
                try: lat=float(row.get("lat") or row.get("latitude") or row.get("latitude_deg"))
                except (TypeError,ValueError): continue
                try: lon=float(row.get("lon") or row.get("longitude") or row.get("longitude_deg"))
                except (TypeError,ValueError): continue
                if ident: self.fix_coords_by_ident.setdefault(ident,(lat,lon))
        edges=0
        with PATH_AIRWAYS.open(newline="",encoding="utf-8",errors="replace") as f:
            for row in csv.DictReader(f):
                a=(row.get("from_fix") or row.get("start_fix") or row.get("fix1") or "").strip().upper()
                b=(row.get("to_fix") or row.get("end_fix") or row.get("fix2") or "").strip().upper()
                awy=(row.get("airway") or row.get("airway_id") or "").strip().upper()
                if a in self.fix_coords_by_ident and b in self.fix_coords_by_ident:
                    d=_nm(self.fix_coords_by_ident[a],self.fix_coords_by_ident[b])
                    self.adj.setdefault(a,[]).append((b,d,awy))
                    self.adj.setdefault(b,[]).append((a,d,awy))
                    edges+=1
        self.graph_source="CSV_FALLBACK"
        print(f"[NAV] Loaded {edges:,} CSV fallback edges")

    def _load_ftwg_binary(self, bin_path):
        raw=bin_path.read_bytes()
        if len(raw)<FTWG_HEADER.size: raise ValueError("truncated header")
        magic,version,flags,nodes,edges=FTWG_HEADER.unpack_from(raw)
        if magic!=FTWG_MAGIC: raise ValueError(f"bad magic {magic!r}")
        expected=FTWG_HEADER.size+nodes*FTWG_NODE.size+edges*FTWG_EDGE.size
        if len(raw)!=expected: raise ValueError(f"size {len(raw)} != expected {expected}")
        idx=[]; off=FTWG_HEADER.size
        self.physical_nodes=[]; self.physical_adj={}; self.nodes_by_ident={}; self.physical_in_degree_nodes=set()
        for node_index in range(nodes):
            ident,lat,lon,kind=FTWG_NODE.unpack_from(raw,off); off+=FTWG_NODE.size
            name=ident.split(b"\x00",1)[0].decode("ascii","ignore").strip().upper()
            coord=(lat/1e6,lon/1e6)
            idx.append(name)
            self.physical_nodes.append({"ident":name,"coord":coord,"kind":kind})
            if name:
                self.fix_coords_by_ident.setdefault(name,coord)
                self.nodes_by_ident.setdefault(name,[]).append(node_index)
        loaded=0; ratios=[]; incoming=set()
        for _ in range(edges):
            u,v,dist,awy=FTWG_EDGE.unpack_from(raw,off); off+=FTWG_EDGE.size
            if u>=nodes or v>=nodes: raise ValueError("edge index out of range")
            a,b=idx[u],idx[v]
            airway=awy.split(b"\x00",1)[0].decode("ascii","ignore").strip().upper()
            weight=dist/10.0
            if a and b:
                self.adj.setdefault(a,[]).append((b,weight,airway))
                self.physical_adj.setdefault(u,[]).append((v,weight,airway))
                incoming.add(v); loaded+=1
                physical_distance=_nm(self.physical_nodes[u]["coord"],self.physical_nodes[v]["coord"])
                if physical_distance>1e-9:
                    ratios.append(weight/physical_distance)
        self.physical_in_degree_nodes=incoming
        # Scale by the minimum edge-cost/geodesic ratio for an admissible heuristic.
        self.heuristic_scale=min(ratios,default=0.0)
        self.graph_source=f"FTWG_BINARY_V{version}"
        print(f"[NAV] Loaded {nodes:,} physical nodes and {loaded:,} directed edges from {bin_path.name}")

    def resolve_physical_endpoint(self, ident, coord=None, direction="either"):
        name=str(ident or "").strip().upper()
        candidates=self.nodes_by_ident.get(name,[])
        if direction=="start":
            candidates=[i for i in candidates if self.physical_adj.get(i)]
        elif direction=="goal":
            candidates=[i for i in candidates if i in self.physical_in_degree_nodes]
        if not candidates: return None
        if coord is not None:
            candidates.sort(key=lambda i:_nm(self.physical_nodes[i]["coord"],coord))
            chosen=candidates[0]; offset=_nm(self.physical_nodes[chosen]["coord"],coord)
        elif len(candidates)==1:
            chosen=candidates[0]; offset=None
        else:
            raise ValueError(f"Ambiguous physical fix identifier {name}: {len(candidates)} variants; matched coordinate required")
        node=self.physical_nodes[chosen]
        return {"node_index":chosen,"ident":name,"coord":node["coord"],"kind":node["kind"],
                "candidate_count":len(candidates),"matched_coordinate":coord,"offset_nm":offset}

    def a_star_connected(self,start,end,start_coord=None,goal_coord=None):
        start_name=str(start or "").strip().upper(); goal_name=str(end or "").strip().upper()
        self.last_route_physical_path=[]; self.last_route_endpoint_resolution={}
        if self.physical_nodes and self.physical_adj:
            start_res=self.resolve_physical_endpoint(start_name,start_coord,"start")
            goal_res=self.resolve_physical_endpoint(goal_name,goal_coord,"goal")
            if not start_res or not goal_res: return None
            source=start_res["node_index"]; target=goal_res["node_index"]
            self.last_route_endpoint_resolution={"start":start_res,"goal":goal_res}
            goal_position=self.physical_nodes[target]["coord"]
            queue=[(_nm(self.physical_nodes[source]["coord"],goal_position)*self.heuristic_scale,0.0,source)]
            best={source:0.0}; previous={}; closed=set()
            while queue:
                _,cost,node=heapq.heappop(queue)
                if cost!=best.get(node): continue
                if node==target: break
                if node in closed: continue
                closed.add(node)
                for nxt,weight,airway in self.physical_adj.get(node,[]):
                    new_cost=cost+weight
                    if new_cost<best.get(nxt,float("inf")):
                        best[nxt]=new_cost; previous[nxt]=(node,weight,airway)
                        h=_nm(self.physical_nodes[nxt]["coord"],goal_position)*self.heuristic_scale
                        heapq.heappush(queue,(new_cost+h,new_cost,nxt))
            if target not in best: return None
            chain=[target]; edge_chain=[]
            while chain[-1]!=source:
                parent,weight,airway=previous[chain[-1]]
                edge_chain.append((parent,chain[-1],weight,airway))
                chain.append(parent)
            chain.reverse(); edge_chain.reverse()
            route_nodes=[]
            cumulative=0.0
            for i,node_index in enumerate(chain):
                node=dict(self.physical_nodes[node_index])
                row={"node_index":node_index,**node,"step_cost_nm":0.0,"step_geodesic_nm":0.0,
                     "cumulative_cost_nm":0.0,"airway_from_previous":None}
                if i:
                    parent,child,weight,airway=edge_chain[i-1]
                    step_geodesic=_nm(self.physical_nodes[parent]["coord"],self.physical_nodes[child]["coord"])
                    cumulative+=weight
                    row.update(step_cost_nm=weight,step_geodesic_nm=step_geodesic,
                               cumulative_cost_nm=cumulative,airway_from_previous=airway)
                route_nodes.append(row)
            self.last_route_physical_path=route_nodes
            return [self.physical_nodes[i]["ident"] for i in chain],best[target]
        # CSV fallback has identifier-only nodes; use Dijkstra, not an unsafe heuristic.
        if start_name not in self.adj or goal_name not in self.adj: return None
        queue=[(0.0,start_name)]; best={start_name:0.0}; previous={}
        while queue:
            cost,node=heapq.heappop(queue)
            if cost!=best.get(node): continue
            if node==goal_name: break
            for nxt,w,_ in self.adj.get(node,[]):
                nc=cost+w
                if nc<best.get(nxt,float("inf")):
                    best[nxt]=nc; previous[nxt]=node; heapq.heappush(queue,(nc,nxt))
        if goal_name not in best: return None
        chain=[goal_name]
        while chain[-1]!=start_name: chain.append(previous[chain[-1]])
        chain.reverse()
        return chain,best[goal_name]


class ConcatenatedHttpStream(io.RawIOBase):
    """Present multiple ordered release assets as one readable tar stream."""
    def __init__(self, urls: list[str], session: requests.Session):
        self.urls, self.session = urls, session
        self.index = 0
        self.response = None
        self.iterator = None
        self.buffer = bytearray()

    def readable(self):
        return True

    def _next_asset(self):
        if self.response is not None:
            self.response.close()
        if self.index >= len(self.urls):
            return False
        url = self.urls[self.index]
        self.index += 1
        print(f"[archive] streaming asset {self.index}/{len(self.urls)}: {url.rsplit('/', 1)[-1]}", flush=True)
        self.response = self.session.get(url, stream=True, timeout=(30, 180))
        self.response.raise_for_status()
        self.iterator = self.response.iter_content(CHUNK)
        return True

    def readinto(self, target):
        while len(self.buffer) < len(target):
            if self.iterator is None and not self._next_asset():
                break
            try:
                block = next(self.iterator)
                if block:
                    self.buffer.extend(block)
            except StopIteration:
                self.iterator = None
        count = min(len(target), len(self.buffer))
        target[:count] = self.buffer[:count]
        del self.buffer[:count]
        return count

    def close(self):
        if self.response is not None:
            self.response.close()
        super().close()


def release_assets(date: str, session: requests.Session) -> tuple[dict, list[str]]:
    day = datetime.strptime(date, "%Y-%m-%d")
    for channel in ("prod", "staging"):
        tag = f"v{day:%Y.%m.%d}-planes-readsb-{channel}-0"
        url = API.format(year=day.year, tag=tag)
        response = session.get(url, timeout=30)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        release = response.json()
        assets = [a for a in release.get("assets", []) if re.search(r"\.tar\.[a-z]{2}$", a.get("name", ""))]
        assets.sort(key=lambda a: a["name"])
        if assets:
            # GitHub asset names sort lexicographically in split-part order (.aa, .ab, ...).
            return release, [a["browser_download_url"] for a in assets]
    raise RuntimeError(f"No ADSB.lol production or staging archive release found for {date}")


def find_trace(date: str, icao24: str | None, output: Path, auto_pick_4ca: bool = False) -> dict:
    session = requests.Session()
    session.headers.update({"User-Agent": "FlightTempo-ADS-B-corridor-benchmark/1.0",
                            "Accept": "application/vnd.github+json"})
    release, urls = release_assets(date, session)
    wanted = f"trace_full_{icao24.lower()}.json" if icao24 else None
    found = False
    candidates = []
    scanned = 0
    trace_members = 0
    with ConcatenatedHttpStream(urls, session) as raw:
        with io.BufferedReader(raw, buffer_size=CHUNK) as buffered:
            with tarfile.open(fileobj=buffered, mode="r|") as archive:
                for member in archive:
                    member_name = member.name.replace("\\", "/").strip().lower()
                    name = member_name.rsplit("/", 1)[-1]
                    scanned += 1
                    if not member.isfile():
                        continue
                    if name.startswith("trace_full_"):
                        trace_members += 1
                    target = (name == wanted or name == wanted + ".gz") if wanted else (
                        auto_pick_4ca and name.startswith("trace_full_4ca") and
                        (name.endswith(".json") or name.endswith(".json.gz")) and member.size > 100_000)
                    if not target:
                        continue
                    if auto_pick_4ca:
                        candidates.append({"member": member.name, "size": member.size})
                        print(f"[archive] candidate {member.name} size={member.size}", flush=True)
                    source = archive.extractfile(member)
                    if source is None:
                        continue
                    payload = source.read()
                    if payload[:2] == b"\x1f\x8b":
                        payload = gzip.decompress(payload)
                    # Reject malformed/non-readsb payloads before writing a temporary trace.
                    document = json.loads(payload)
                    if not isinstance(document, dict) or not isinstance(document.get("trace"), list):
                        raise RuntimeError(f"Archive member {member.name} is not a readsb trace document")
                    output.write_bytes(payload)
                    found = True
                    if auto_pick_4ca:
                        icao24 = name.split("trace_full_", 1)[-1].split(".", 1)[0]
                        print(f"[archive] AUTO-PICK selected hex={icao24} member={member.name} size={member.size}", flush=True)
                    print(f"[archive] found and parsed {member.name}; {len(document['trace'])} rows", flush=True)
                    break
    print(f"[archive] scan summary: members_scanned={scanned} trace_full_members={trace_members} auto_pick_candidates={len(candidates)}", flush=True)
    if not found:
        if auto_pick_4ca:
            raise RuntimeError(f"No qualifying trace_full_4ca*.json(.gz) member >100000 bytes in {date} archive; scanned={scanned}, trace_full={trace_members}")
        raise RuntimeError(f"ICAO24 {icao24} was not present in the {date} archive")
    return {"release_tag": release.get("tag_name"), "release_url": release.get("html_url")}



def _exception_text(exc: BaseException) -> str:
    tb = exc.__traceback__ or sys.exc_info()[2]
    return "".join(traceback.format_exception(type(exc), exc, tb)) if tb else f"{type(exc).__name__}: {exc}\n"


def _durable_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, allow_nan=False, default=str)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


class BenchmarkRecorder:
    def __init__(self, path: Path, metadata: dict):
        self.path = path
        self.state = {
            "started_at_utc": datetime.utcnow().isoformat() + "Z",
            "status": "running",
            "failure_stage": "initialization",
            "metadata": metadata,
            "stages": {},
            "leg_diagnostics": [],
            "summary": {},
            "error_type": None,
            "error_message": None,
            "traceback": None,
        }
        self.persist()

    def persist(self):
        self.state["updated_at_utc"] = datetime.utcnow().isoformat() + "Z"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".benchmark_evidence_", suffix=".tmp", dir=str(self.path.parent))
        tmp_path = Path(tmp)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, allow_nan=False, default=str)
                f.write("\\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)
        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            # Durable fallback; recorder errors are not allowed to hide pipeline errors.
            _durable_json(self.path, {
                "status": self.state.get("status", "failed"),
                "failure_stage": self.state.get("failure_stage"),
                "error_type": self.state.get("error_type"),
                "error_message": self.state.get("error_message"),
                "serialization_fallback": True,
                "updated_at_utc": datetime.utcnow().isoformat() + "Z",
            })

    def stage(self, name: str):
        self.state["failure_stage"] = name
        self.state["stages"][name] = {"status": "running"}
        self.persist()

    def stage_done(self, name: str, metrics: dict | None = None):
        self.state["stages"][name] = {"status": "completed", **(metrics or {})}
        self.persist()

    def fail(self, stage: str, exc: BaseException):
        self.state.update(status="failed", failure_stage=stage, error_type=type(exc).__name__,
                          error_message=str(exc), traceback=_exception_text(exc))
        self.persist()

    def succeed(self, summary: dict):
        self.state.update(status="passed", failure_stage=None, summary=summary)
        self.persist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="UTC archive date YYYY-MM-DD")
    parser.add_argument("--mode", choices=("benchmark", "global"), default="benchmark")
    parser.add_argument("--icao24", help="Six-character ICAO24 for benchmark mode")
    parser.add_argument("--auto-pick-4ca", action="store_true", help="Select first qualifying Irish Ryanair 4CA trace (>100 KB)")
    parser.add_argument("--trace-file", help="Local extracted trace (raw or gzip-compressed)")
    parser.add_argument("--output", default="adsb/corridors/benchmark_evidence.json")
    parser.add_argument("--evidence-out", default="/tmp/benchmark_evidence.json")
    args = parser.parse_args()

    datetime.strptime(args.date, "%Y-%m-%d")
    if args.mode == "global":
        raise SystemExit("Global ingestion is deliberately locked until real benchmark archive validation passes.")
    if not args.auto_pick_4ca and (not args.icao24 or not re.fullmatch(r"[0-9a-fA-F]{6}", args.icao24)):
        raise SystemExit("Benchmark mode requires --icao24 or --auto-pick-4ca.")
    if args.auto_pick_4ca and args.icao24:
        raise SystemExit("Use --auto-pick-4ca without --icao24.")
    if not BUILDER.is_file():
        raise SystemExit(f"Existing corridor builder not found: {BUILDER}")

    recorder = BenchmarkRecorder(Path(args.evidence_out), {
        "date": args.date, "icao24": args.icao24.lower() if args.icao24 else None,
        "auto_pick_4ca": args.auto_pick_4ca,
    })
    stage = "trace_fetch"
    try:
        with tempfile.TemporaryDirectory(prefix="flighttempo-adsb-") as tmp:
            trace = Path(tmp) / "benchmark_trace.json"
            stage = "trace_fetch"
            recorder.stage(stage)
            if args.trace_file:
                raw = Path(args.trace_file).read_bytes()
                if raw[:2] == b"\\x1f\\x8b":
                    raw = gzip.decompress(raw)
                document = json.loads(raw)
                if not isinstance(document, dict) or not isinstance(document.get("trace"), list):
                    raise RuntimeError(f"Local trace file is not a readsb trace document: {args.trace_file}")
                trace.write_bytes(raw)
                release = {"source": "workflow-local-extraction", "release_tag": f"v{args.date}"}
                trace_rows = len(document["trace"])
                recorder.stage_done(stage, {"trace_rows": trace_rows, "source": "local_extraction"})
                print(f"[archive] local trace loaded: {trace_rows} rows", flush=True)
            else:
                release = find_trace(args.date, args.icao24, trace, args.auto_pick_4ca)
                document = json.loads(trace.read_text(encoding="utf-8"))
                trace_rows = len(document["trace"])
                recorder.stage_done(stage, {"trace_rows": trace_rows, "release_tag": release.get("release_tag")})

            stage = "trace_decode"
            recorder.stage(stage)
            decoded = json.loads(trace.read_text(encoding="utf-8"))
            recorder.stage_done(stage, {"decoded_rows": len(decoded.get("trace", []))})

            stage = "segmentation_and_fix_matching"
            recorder.stage(stage)
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([sys.executable, str(BUILDER), "--trace", str(trace),
                            "--output", str(out)], cwd=ROOT, check=True)
            evidence = json.loads(out.read_text(encoding="utf-8"))
            accepted = [r for r in evidence.get("traceResults", []) if not r.get("excluded")]
            recorder.stage_done(stage, {"total_legs": len(evidence.get("traceResults", [])),
                                        "eligible_legs": len(accepted),
                                        "matched_fixes": sum(len(r.get("matchedFixes", [])) for r in accepted),
                                        "excluded_legs": len(evidence.get("traceResults", [])) - len(accepted)})
            if not accepted:
                raise RuntimeError("Benchmark produced no eligible non-excluded flight legs")

            stage = "node_resolution_and_graph_connectivity"
            recorder.stage(stage)
            nav = RepositoryNavDatabase()
            nav._load_airways()
            comparisons = []
            resolved_total = 0
            identifier_resolved_total = 0
            matched_total = 0
            connected_legs = 0

            # Build identifier-keyed in/out degree metrics matching the A* adjacency representation.
            in_degree = {}
            out_degree = {}
            for source, edges in nav.adj.items():
                out_degree[source] = len(edges)
                for edge in edges:
                    target = edge[0]
                    in_degree[target] = in_degree.get(target, 0) + 1

            for result in accepted:
                observed = [str(f).strip().upper() for f in result.get("matchedFixes", []) if f]
                details = result.get("matchedFixDetails", [])
                detail_by_index = [d for d in details if isinstance(d,dict)] if isinstance(details,list) else []
                matched_total += len(observed)

                def detail_coord(index):
                    if index < len(detail_by_index):
                        d=detail_by_index[index]
                        try: return (float(d["lat"]),float(d["lon"]))
                        except (KeyError,TypeError,ValueError): pass
                    return None

                physical_resolved=[]; physical_unresolved=[]; identifier_resolved=[]
                for i,fix in enumerate(observed):
                    coord=detail_coord(i)
                    if fix in nav.adj: identifier_resolved.append(fix)
                    if nav.physical_nodes:
                        try:
                            r=nav.resolve_physical_endpoint(fix,coord,"either")
                            if r and (r["offset_nm"] is None or r["offset_nm"]<=PHYSICAL_FIX_RESOLUTION_RADIUS_NM):
                                physical_resolved.append({"fix":fix,"match_index":i,"resolution":r})
                            else:
                                physical_unresolved.append(fix)
                        except ValueError:
                            physical_unresolved.append(fix)
                    elif fix in nav.adj:
                        physical_resolved.append({"fix":fix,"match_index":i,"resolution":None})
                    else:
                        physical_unresolved.append(fix)
                resolved=physical_resolved
                resolved_total+=len(resolved)
                identifier_resolved_total+=len(identifier_resolved)

                start_candidates=[]; goal_candidates=[]
                for i,fix in enumerate(observed):
                    coord=detail_coord(i)
                    if nav.physical_nodes:
                        try:
                            r=nav.resolve_physical_endpoint(fix,coord,"start")
                            if r and (r["offset_nm"] is None or r["offset_nm"]<=PHYSICAL_FIX_RESOLUTION_RADIUS_NM):
                                start_candidates.append({"fix":fix,"match_index":i,"coord":coord,"resolution":r})
                        except ValueError as exc:
                            print(f"[NAV] endpoint candidate skipped {fix}: {exc}")
                        try:
                            r=nav.resolve_physical_endpoint(fix,coord,"goal")
                            if r and (r["offset_nm"] is None or r["offset_nm"]<=PHYSICAL_FIX_RESOLUTION_RADIUS_NM):
                                goal_candidates.append({"fix":fix,"match_index":i,"coord":coord,"resolution":r})
                        except ValueError as exc:
                            print(f"[NAV] endpoint candidate skipped {fix}: {exc}")
                    else:
                        if out_degree.get(fix,0)>0 and fix in nav.fix_coords_by_ident:
                            start_candidates.append({"fix":fix,"match_index":i,"coord":coord,"resolution":None})
                        if in_degree.get(fix,0)>0 and fix in nav.fix_coords_by_ident:
                            goal_candidates.append({"fix":fix,"match_index":i,"coord":coord,"resolution":None})
                start_row=start_candidates[0] if start_candidates else None
                goal_row=goal_candidates[-1] if goal_candidates else None
                start=start_row["fix"] if start_row else None
                goal=goal_row["fix"] if goal_row else None
                start_coord=start_row["coord"] if start_row else None
                goal_coord=goal_row["coord"] if goal_row else None

                diag = {
                    "leg": result.get("legNumber"),
                    "origin_airport": result.get("origin"),
                    "destination_airport": result.get("destination"),
                    "segmentation": result.get("segmentation"),
                    "position_count": result.get("positionCount"),
                    "matched_fix_count": len(observed),
                    "resolved_node_count": len(resolved),
                    "physical_resolved_fixes": resolved,
                    "unresolved_fixes": physical_unresolved,
                    "identifier_resolved_count": len(identifier_resolved),
                    "identifier_unresolved_fixes": [fix for fix in observed if fix not in nav.adj],
                    "physical_fix_resolution_radius_nm": PHYSICAL_FIX_RESOLUTION_RADIUS_NM,
                    "first_matched_fix": observed[0] if observed else None,
                    "last_matched_fix": observed[-1] if observed else None,
                    "first_fix_in_graph": observed[0] in nav.adj if observed else False,
                    "last_fix_in_graph": observed[-1] in nav.adj if observed else False,
                    "first_fix_physical_resolution": resolved[0]["resolution"] if resolved else None,
                    "last_fix_physical_resolution": resolved[-1]["resolution"] if resolved else None,
                    "usable_start_candidates": [x["fix"] for x in start_candidates],
                    "usable_goal_candidates": [x["fix"] for x in goal_candidates],
                    "selected_graph_endpoints": [start, goal],
                    "selected_endpoint_coordinates": [start_coord, goal_coord],
                    "selected_physical_endpoint_resolution": [start_row["resolution"] if start_row else None,
                                                             goal_row["resolution"] if goal_row else None],
                }

                status, overlap = "UNVERIFIED_ENDPOINTS", 0.0
                path = None; distance_nm = None; raw_endpoint_result = None
                if len(observed)>=2:
                    try:
                        raw_endpoint_result=nav.a_star_connected(observed[0],observed[-1],
                                                               detail_coord(0),detail_coord(len(observed)-1))
                    except Exception as exc:
                        raw_endpoint_result={"error":f"{type(exc).__name__}: {exc}"}
                diag["raw_endpoint_probe"]=(
                    {"connected":bool(raw_endpoint_result),
                     "path_node_count":len(raw_endpoint_result[0]) if isinstance(raw_endpoint_result,tuple) and raw_endpoint_result and isinstance(raw_endpoint_result[0],(list,tuple)) else 0,
                     "distance_nm":raw_endpoint_result[1] if isinstance(raw_endpoint_result,tuple) and len(raw_endpoint_result)>1 else None,
                     "physical_path":nav.last_route_physical_path if isinstance(raw_endpoint_result,tuple) else None,
                     "endpoint_resolution":nav.last_route_endpoint_resolution if isinstance(raw_endpoint_result,tuple) else None}
                    if not isinstance(raw_endpoint_result,dict) else raw_endpoint_result)

                if start and goal:
                    try:
                        astar=nav.a_star_connected(start,goal,start_coord,goal_coord)
                    except Exception as exc:
                        astar={"error":f"{type(exc).__name__}: {exc}"}
                    if astar and not isinstance(astar,dict):
                        path,distance_nm=astar
                        a,b=set(observed),set(path)
                        overlap=round(len(a&b)/max(1,len(a|b)),3)
                        status="CONNECTED_FTWG_PHYSICAL_NODES" if nav.physical_nodes else "CONNECTED_CSV_FALLBACK_DIJKSTRA"
                        connected_legs+=1
                    else:
                        status="GRAPH_GAP_DETECTED"
                else:
                    status="UNVERIFIED_ENDPOINTS"

                diag["graph_path_node_count"]=len(path) if path else 0
                diag["graph_path_distance_nm"]=distance_nm
                diag["graph_path_nodes"]=path
                diag["graph_path_physical_nodes"]=nav.last_route_physical_path if path else None
                diag["graph_path_endpoint_resolution"]=nav.last_route_endpoint_resolution if path else None
                result["graphComparison"]={"graph_source":nav.graph_source,"status":status,
                                           "fix_jaccard_overlap":overlap,"diagnostics":diag}
                comparisons.append({"status":status,**diag,"overlap":overlap})
            summary = {
                "trace_rows": trace_rows,
                "total_legs": len(evidence.get("traceResults", [])),
                "eligible_legs": len(accepted),
                "matched_fixes": matched_total,
                "physical_resolved_nodes": resolved_total,
                "physical_unresolved_nodes": matched_total - resolved_total,
                "identifier_resolved_nodes_legacy": identifier_resolved_total,
                "identifier_unresolved_nodes_legacy": matched_total-identifier_resolved_total,
                "connected_legs": connected_legs,
                "graph_source": nav.graph_source,
                "graph_node_count": len(nav.fix_coords_by_ident),
                "graph_adjacency_node_count": len(nav.adj),
                "physical_graph_node_count": len(nav.physical_nodes),
                "physical_graph_adjacency_node_count": len(nav.physical_adj),
                "physical_graph_directed_edge_count": sum(len(v) for v in nav.physical_adj.values()),
                "duplicate_identifier_count": sum(1 for v in nav.nodes_by_ident.values() if len(v)>1),
                "admissible_heuristic_scale": nav.heuristic_scale,
            }
            recorder.state["leg_diagnostics"] = comparisons
            recorder.state["summary"] = summary
            recorder.stage_done(stage, summary)
            recorder.persist()
            print("[BENCHMARK] Per-leg FTWG comparison: " + json.dumps(comparisons), flush=True)
            if connected_legs == 0:
                raise RuntimeError(f"No flight leg connected through FTWG graph: {json.dumps(comparisons)}")

            # Do not serialize aircraft identity or the source trace into the public builder artifact.
            forbidden = {"hex", "icao", "registration", "callsign"}
            def scan(value):
                if isinstance(value, dict):
                    return any(str(k).lower() in forbidden or scan(v) for k, v in value.items())
                if isinstance(value, list):
                    return any(scan(v) for v in value)
                return False
            stage = "privacy_validation"
            recorder.stage(stage)
            if scan(evidence):
                out.unlink(missing_ok=True)
                raise RuntimeError("Privacy validation failed: aircraft identity field detected")
            recorder.stage_done(stage)
            print(json.dumps({"status": "validated", "date": args.date, "release": release,
                              "summary": summary, "output": str(out)}, indent=2))
            recorder.succeed(summary)
    except Exception as exc:
        original = exc
        try:
            recorder.fail(stage, original)
        except Exception as recorder_exc:
            print(f"[evidence] recorder failure while preserving original exception: {recorder_exc}", file=sys.stderr)
        raise

