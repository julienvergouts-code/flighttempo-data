#!/usr/bin/env python3
"""Fetch and validate one real ADSB.lol historical readsb trace.

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


def find_trace(date: str, icao24: str, output: Path) -> dict:
    session = requests.Session()
    session.headers.update({"User-Agent": "FlightTempo-ADS-B-corridor-benchmark/1.0",
                            "Accept": "application/vnd.github+json"})
    release, urls = release_assets(date, session)
    wanted = f"trace_full_{icao24.lower()}.json"
    found = False
    with ConcatenatedHttpStream(urls, session) as raw:
        with io.BufferedReader(raw, buffer_size=CHUNK) as buffered:
            with tarfile.open(fileobj=buffered, mode="r|") as archive:
                for member in archive:
                    name = member.name.rsplit("/", 1)[-1]
                    if not member.isfile() or not (name == wanted or name == wanted + ".gz"):
                        continue
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
                    print(f"[archive] found and parsed {member.name}; {len(document['trace'])} rows", flush=True)
                    break
    if not found:
        raise RuntimeError(f"ICAO24 {icao24} was not present in the {date} archive")
    return {"release_tag": release.get("tag_name"), "release_url": release.get("html_url")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="UTC archive date YYYY-MM-DD")
    parser.add_argument("--mode", choices=("benchmark", "global"), default="benchmark")
    parser.add_argument("--icao24", help="Required for benchmark mode")
    parser.add_argument("--output", default="adsb/corridors/benchmark_evidence.json")
    args = parser.parse_args()

    datetime.strptime(args.date, "%Y-%m-%d")
    if args.mode == "global":
        raise SystemExit("Global ingestion is deliberately locked until real benchmark archive validation passes.")
    if not args.icao24 or not re.fullmatch(r"[0-9a-fA-F]{6}", args.icao24):
        raise SystemExit("Benchmark mode requires a six-character ICAO24 hex via --icao24.")
    if not BUILDER.is_file():
        raise SystemExit(f"Existing corridor builder not found: {BUILDER}")

    with tempfile.TemporaryDirectory(prefix="flighttempo-adsb-") as tmp:
        trace = Path(tmp) / "benchmark_trace.json"
        release = find_trace(args.date, args.icao24, trace)
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, str(BUILDER), "--trace", str(trace),
                        "--output", str(out)], cwd=ROOT, check=True)
        evidence = json.loads(out.read_text(encoding="utf-8"))
        accepted = [r for r in evidence.get("traceResults", []) if not r.get("excluded")]
        if len(accepted) != 1:
            raise RuntimeError(f"Benchmark produced {len(accepted)} accepted traces; expected exactly one")
        result = accepted[0]
        comparison = result.get("graphComparison", {})
        if comparison.get("status") != "path_found":
            raise RuntimeError("Benchmark did not produce a successful FTWG graph comparison")
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
                          "graph_comparison": comparison.get("status"),
                          "output": str(out)}, indent=2))


if __name__ == "__main__":
    main()
