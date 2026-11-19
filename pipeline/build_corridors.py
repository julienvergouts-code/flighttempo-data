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

def _nm(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = math.radians(b[0]-a[0]), math.radians(b[1]-a[1])
    q = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*3440.065*math.atan2(math.sqrt(q), math.sqrt(1-q))

class RepositoryNavDatabase:
    """FTWG v1 reader; CSV is a clearly tagged fallback only."""
    def __init__(self):
        self.fix_coords_by_ident = {}
        self.adj = {}
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
        for _ in range(nodes):
            ident,lat,lon,kind=FTWG_NODE.unpack_from(raw,off); off+=FTWG_NODE.size
            name=ident.split(b"\x00",1)[0].decode("ascii","ignore").strip().upper()
            idx.append(name)
            if name: self.fix_coords_by_ident.setdefault(name,(lat/1e6,lon/1e6))
        loaded=0
        for _ in range(edges):
            u,v,dist,awy=FTWG_EDGE.unpack_from(raw,off); off+=FTWG_EDGE.size
            if u>=nodes or v>=nodes: raise ValueError("edge index out of range")
            a,b=idx[u],idx[v]
            airway=awy.split(b"\x00",1)[0].decode("ascii","ignore").strip().upper()
            if a and b:
                self.adj.setdefault(a,[]).append((b,dist/10.0,airway))
                loaded+=1
        self.graph_source=f"FTWG_BINARY_V{version}"
        print(f"[NAV] Loaded {nodes:,} nodes and {loaded:,} directed edges from {bin_path.name}")

    def a_star_connected(self,start,end):
        if start not in self.adj or end not in self.adj: return None
        goal=self.fix_coords_by_ident[end]; startpos=self.fix_coords_by_ident[start]
        queue=[(_nm(startpos,goal),0.0,start,[start])]; visited=set()
        while queue:
            _,cost,node,path=heapq.heappop(queue)
            if node==end: return path,cost
            if node in visited: continue
            visited.add(node)
            for nxt,w,_ in self.adj.get(node,[]):
                if nxt in visited: continue
                nc=cost+w
                heapq.heappush(queue,(nc+_nm(self.fix_coords_by_ident[nxt],goal),nc,nxt,path+[nxt]))
        return None



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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="UTC archive date YYYY-MM-DD")
    parser.add_argument("--mode", choices=("benchmark", "global"), default="benchmark")
    parser.add_argument("--icao24", help="Six-character ICAO24 for benchmark mode")
    parser.add_argument("--auto-pick-4ca", action="store_true", help="Select first qualifying Irish Ryanair 4CA trace (>100 KB)")
    parser.add_argument("--trace-file", help="Local extracted trace (raw or gzip-compressed)")
    parser.add_argument("--output", default="adsb/corridors/benchmark_evidence.json")
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

    with tempfile.TemporaryDirectory(prefix="flighttempo-adsb-") as tmp:
        trace = Path(tmp) / "benchmark_trace.json"
        if args.trace_file:
            raw = Path(args.trace_file).read_bytes()
            if raw[:2] == b"\\x1f\\x8b":
                raw = gzip.decompress(raw)
            document = json.loads(raw)
            if not isinstance(document, dict) or not isinstance(document.get("trace"), list):
                raise RuntimeError(f"Local trace file is not a readsb trace document: {args.trace_file}")
            trace.write_bytes(raw)
            release = {"source": "workflow-local-extraction", "release_tag": f"v{args.date}"}
            print(f"[archive] local trace loaded: {len(document['trace'])} rows", flush=True)
        else:
            release = find_trace(args.date, args.icao24, trace, args.auto_pick_4ca)
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, str(BUILDER), "--trace", str(trace),
                        "--output", str(out)], cwd=ROOT, check=True)
        evidence = json.loads(out.read_text(encoding="utf-8"))
        accepted = [r for r in evidence.get("traceResults", []) if not r.get("excluded")]
        if not accepted:
            raise RuntimeError("Benchmark produced no eligible non-excluded flight legs")
        nav = RepositoryNavDatabase()
        nav._load_airways()
        comparisons = []
        for result in accepted:
            observed = result.get("matchedFixes", [])
            diag = {
                "leg": result.get("legNumber"),
                "origin_airport": result.get("origin"),
                "destination_airport": result.get("destination"),
                "segmentation": result.get("segmentation"),
                "position_count": result.get("positionCount"),
                "matched_fix_count": len(observed),
                "first_matched_fix": observed[0] if observed else None,
                "last_matched_fix": observed[-1] if observed else None,
                "first_fix_in_graph": observed[0] in nav.adj if observed else False,
                "last_fix_in_graph": observed[-1] in nav.adj if observed else False,
            }
            status, overlap = "UNVERIFIED_ENDPOINTS", 0.0
            if len(observed) >= 2:
                astar = nav.a_star_connected(observed[0], observed[-1])
                if astar:
                    path, _distance = astar
                    a, b = set(observed), set(path)
                    overlap = round(len(a & b) / max(1, len(a | b)), 3)
                    status = "CONNECTED_FTWG"
                else:
                    status = "GRAPH_GAP_DETECTED"
            result["graphComparison"] = {"graph_source": nav.graph_source, "status": status,
                                         "fix_jaccard_overlap": overlap, "diagnostics": diag}
            comparisons.append({"status": status, **diag, "overlap": overlap})
        print("[BENCHMARK] Per-leg FTWG comparison: " + json.dumps(comparisons), flush=True)
        if not any(x["status"] == "CONNECTED_FTWG" for x in comparisons):
            raise RuntimeError(f"No flight leg connected through FTWG graph: {json.dumps(comparisons)}")
        # Do not serialize aircraft identity or the source trace into the published artifact.
        forbidden = {"hex", "icao", "registration", "callsign"}
        def scan(value):
            if isinstance(value, dict):
                return any(str(k).lower() in forbidden or scan(v) for k, v in value.items())
            if isinstance(value, list):
                return any(scan(v) for v in value)
            return False
        if scan(evidence):
            out.unlink(missing_ok=True)
            raise RuntimeError("Privacy validation failed: aircraft identity field detected")
        print(json.dumps({"status": "validated", "date": args.date,
                          "release": release, "origin": result["origin"],
                          "destination": result["destination"],
                          "matched_fix_count": result.get("matchCount", 0),
                          "graph_comparison": result["graphComparison"]["status"],
                          "output": str(out)}, indent=2))


if __name__ == "__main__":
    main()
