#!/usr/bin/env python3
"""Learn observed airport-to-airport flight paths from the ADSB.lol daily archive.

Simple method, no navigation graph and no airway data (none of the legacy 2012 navigation set is used):
  1. read airline-style readsb traces from the daily archive (HTTP range reads, nothing stored),
  2. cut each trace into complete flights (take-off to landing, both ends seen on the ground),
  3. name origin and destination from the airports in OurAirports (public domain),
  4. resample the flight to a point every 20 NM and group paths of the same airport pair that stay within
     12 NM of each other on average,
  5. count flights per group. One group is one observed route; more flights means more trust.

Published per group: airport pair, flight count, the first path seen, its length and the last day seen.
Never published: aircraft id, registration, callsign, per-point timestamps or the raw trace.
Evidence of what aircraft flew, not a filed route, a clearance or proof that an airway was used.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import sys
import tarfile
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

OUT_DIR = ROOT / "routes" / "observed"
AIRPORTS_CSV = ROOT / "navigation" / "airports" / "ourairports_airports.csv"
EARTH_NM = 3440.065
ANCHOR_RADIUS_NM = 8.0
MIN_LEG_NM = 150.0
MIN_CRUISE_FT = 20000
MAX_DETOUR = 1.6          # path length / great-circle distance
RESAMPLE_NM = 20.0
SIGNATURE_POINTS = 32
CLUSTER_NM = 12.0
MAX_CLUSTERS_PER_PAIR = 6
MAX_GAP_SECONDS = 1200
MAX_SAMPLES = 100000
PACK_NAME = "observed_routes.json.gz"
ATTRIBUTION = "Contains information from ADSB.lol, made available under the Open Database License (ODbL) 1.0."
LICENSE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
SOURCE_URL = "https://github.com/adsblol"


def dist_nm(a, b) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_NM * math.asin(min(1.0, math.sqrt(h)))


def lerp(a, b, f):
    """Point a fraction f of the way from a to b, crossing the antimeridian the short way."""
    dlon = b[1] - a[1]
    if dlon > 180:
        dlon -= 360
    elif dlon < -180:
        dlon += 360
    lon = a[1] + dlon * f
    lon = (lon + 180) % 360 - 180
    return (a[0] + (b[0] - a[0]) * f, lon)


def load_airports(path: Path = AIRPORTS_CSV) -> list[tuple[str, float, float]]:
    out = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ident = (row.get("icao") or row.get("ident") or "").strip().upper()
            kind = row.get("source_type") or ""
            if len(ident) != 4 or not ident.isalpha() or kind in ("heliport", "closed", "seaplane_base", "balloonport"):
                continue
            try:
                lat = float(row.get("latitude") or row.get("latitude_deg"))
                lon = float(row.get("longitude") or row.get("longitude_deg"))
            except (TypeError, ValueError):
                continue
            out.append((ident, lat, lon))
    return out


class AirportIndex:
    """Nearest-airport lookup on a 1 degree grid."""

    def __init__(self, airports):
        self.cells = defaultdict(list)
        for a in airports:
            self.cells[(math.floor(a[1]), math.floor(a[2]))].append(a)

    def nearest(self, lat: float, lon: float, radius_nm: float = ANCHOR_RADIUS_NM):
        best = None
        r = int(radius_nm / 60.0) + 1
        for dla in range(-r, r + 1):
            for dlo in range(-r - 1, r + 2):
                cell = (math.floor(lat) + dla, math.floor(lon) + dlo)
                for ident, la, lo in self.cells.get(cell, ()):
                    d = dist_nm((lat, lon), (la, lo))
                    if d <= radius_nm and (best is None or d < best[0]):
                        best = (d, ident)
        return best[1] if best else None


def read_points(doc: dict) -> list[dict]:
    epoch = float(doc.get("timestamp", 0) or 0)
    pts = []
    for row in doc.get("trace", []) or []:
        if not isinstance(row, list) or len(row) < 3:
            continue
        try:
            sec, lat, lon = float(row[0]), float(row[1]), float(row[2])
        except (TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        flags = int(row[6]) if len(row) > 6 and isinstance(row[6], (int, float)) else 0
        alt = row[3] if len(row) > 3 else None
        on_ground = alt == "ground" or bool(flags & 2)
        alt_ft = float(alt) if isinstance(alt, (int, float)) and not isinstance(alt, bool) else None
        pts.append({"t": epoch + sec, "lat": lat, "lon": lon, "ground": on_ground, "alt": alt_ft})
    pts.sort(key=lambda p: p["t"])
    return pts


def complete_flights(points: list[dict]) -> list[dict]:
    """Airborne stretches that start after a ground sample and end before one (both ends seen on the ground)."""
    chunks, chunk = [], []
    for p in points:
        if chunk and p["t"] - chunk[-1]["t"] > MAX_GAP_SECONDS:
            chunks.append(chunk)
            chunk = []
        chunk.append(p)
    if chunk:
        chunks.append(chunk)
    flights = []
    for c in chunks:
        start = None
        for i, p in enumerate(c):
            if not p["ground"] and start is None:
                start = i
            elif p["ground"] and start is not None:
                air = c[start:i]
                if start > 0 and len(air) >= 10:
                    flights.append({"air": air, "before": c[max(0, start - 10):start], "after": c[i:i + 10]})
                start = None
    return flights


def anchor(window: list[dict], index: AirportIndex):
    votes = Counter()
    for p in window:
        if p["ground"]:
            ident = index.nearest(p["lat"], p["lon"])
            if ident:
                votes[ident] += 1
    if not votes:
        return None
    ident, n = votes.most_common(1)[0]
    return ident if n >= 2 else None


def path_length(pts) -> float:
    return sum(dist_nm(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def resample(pts, spacing_nm: float):
    """A point every ``spacing_nm`` along the path, plus the last point."""
    out = [tuple(pts[0])]
    acc, next_at = 0.0, spacing_nm
    for a, b in zip(pts, pts[1:]):
        seg = dist_nm(a, b)
        if seg <= 0:
            continue
        while next_at <= acc + seg:
            out.append(lerp(a, b, (next_at - acc) / seg))
            next_at += spacing_nm
        acc += seg
    if out[-1] != tuple(pts[-1]):
        out.append(tuple(pts[-1]))
    return out


def signature(pts, n: int = SIGNATURE_POINTS):
    """n points at equal fractions of the path length."""
    total = path_length(pts)
    if total <= 0 or len(pts) < 2:
        return [tuple(pts[0])] * n
    out, acc, j = [], 0.0, 0
    for k in range(n):
        target = total * k / (n - 1)
        while j < len(pts) - 2 and acc + dist_nm(pts[j], pts[j + 1]) < target:
            acc += dist_nm(pts[j], pts[j + 1])
            j += 1
        seg = dist_nm(pts[j], pts[j + 1]) or 1e-9
        out.append(lerp(pts[j], pts[j + 1], min(1.0, max(0.0, (target - acc) / seg))))
    return out


def route_distance(sig_a, sig_b) -> float:
    return sum(dist_nm(a, b) for a, b in zip(sig_a, sig_b)) / len(sig_a)


def flight_to_route(flight: dict, index: AirportIndex):
    """Return ((origin, destination, path), None) for a usable flight, else (None, reason)."""
    air = flight["air"]
    origin, destination = anchor(flight["before"], index), anchor(flight["after"], index)
    if not origin or not destination:
        return None, "airports_unresolved"
    if origin == destination:
        return None, "same_airport"
    latlon = [(p["lat"], p["lon"]) for p in air]
    direct = dist_nm(latlon[0], latlon[-1])
    if direct < MIN_LEG_NM:
        return None, "short_leg"
    if max((p["alt"] or 0) for p in air) < MIN_CRUISE_FT:
        return None, "no_cruise"
    if path_length(latlon) > direct * MAX_DETOUR:
        return None, "detour_or_loop"
    return (origin, destination, [(round(a, 2), round(b, 2)) for a, b in resample(latlon, RESAMPLE_NM)]), None


def add_route(pairs: dict, origin: str, destination: str, path, day: str) -> None:
    key = f"{origin}-{destination}"
    sig = signature(path)
    clusters = pairs.setdefault(key, [])
    for c in clusters:
        if route_distance(sig, signature([tuple(p) for p in c["polyline"]])) <= CLUSTER_NM:
            c["samples"] = min(MAX_SAMPLES, c["samples"] + 1)
            c["lastObserved"] = max(c["lastObserved"], day)
            return
    clusters.append({"samples": 1, "polyline": [list(p) for p in path], "lengthNm": round(path_length(path)),
                     "lastObserved": day})
    if len(clusters) > MAX_CLUSTERS_PER_PAIR:
        clusters.sort(key=lambda c: (-c["samples"], c["lastObserved"]))
        del clusters[MAX_CLUSTERS_PER_PAIR:]


def confidence(samples: int) -> str:
    return "HIGH" if samples >= 5 else "MEDIUM" if samples >= 3 else "LOW"


def process_document(doc: dict, index: AirportIndex, pairs: dict, day: str, rejected: Counter) -> int:
    added = 0
    for flight in complete_flights(read_points(doc)):
        route, reason = flight_to_route(flight, index)
        if route is None:
            rejected[reason] += 1
            continue
        add_route(pairs, route[0], route[1], route[2], day)
        added += 1
    return added


def load_existing(out: Path) -> dict:
    pack = out / PACK_NAME
    if pack.is_file():
        body = json.loads(gzip.decompress(pack.read_bytes()))
        return {"processedDates": list(body.get("processedDates", [])), "pairs": body.get("pairs", {})}
    return {"processedDates": [], "pairs": {}}


def pack_bytes(state: dict) -> bytes:
    body = {"schema": 1, "source": "ADSB.lol globe_history", "license": "ODbL 1.0", "licenseUrl": LICENSE_URL,
            "attribution": ATTRIBUTION, "processedDates": sorted(set(state["processedDates"])),
            "privacy": "No aircraft identifiers, callsigns or timestamps are stored.",
            "pairs": {k: sorted(v, key=lambda c: (-c["samples"], c["lastObserved"]))
                      for k, v in sorted(state["pairs"].items())}}
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(raw)
    return buf.getvalue()


def build_index(state: dict, pack: bytes) -> dict:
    clusters = [c for v in state["pairs"].values() for c in v]
    tiers = Counter(confidence(c["samples"]) for c in clusters)
    return {
        "schema": 1, "format": "FlightTempo observed routes (ADS-B)", "provider": "ADSB.lol",
        "license": "ODbL 1.0", "licenseUrl": LICENSE_URL, "attribution": ATTRIBUTION, "sourceUrl": SOURCE_URL,
        "file": PACK_NAME, "sizeBytes": len(pack), "sha256": hashlib.sha256(pack).hexdigest(),
        "airportPairs": len(state["pairs"]), "routeCount": len(clusters),
        "flightsCounted": sum(c["samples"] for c in clusters),
        "confidence": dict(tiers), "processedDates": sorted(set(state["processedDates"])),
        "confidenceRule": "LOW 1-2 flights, MEDIUM 3-4, HIGH 5 or more flights in the group.",
        "method": "Complete flights (ground to ground) from airline-style traces; paths grouped within 12 NM mean separation.",
        "notice": "Observed ADS-B paths are evidence of flown tracks, not filed routes, clearances or proof of airway use. Reference data only.",
        "operationalUse": False, "legacyGraphUsed": False,
        "derivedDatabaseNote": "ODbL share-alike applies to a published derived database: keep this layer separate and offer it under ODbL.",
    }


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_outputs(state: dict, out: Path) -> dict:
    pack = pack_bytes(state)
    atomic_write(out / PACK_NAME, pack)
    index = build_index(state, pack)
    atomic_write(out / "index.json", (json.dumps(index, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    return index


def scan_archive(date: str, index: AirportIndex, state: dict, max_flights: int, max_members: int, budget_s: float) -> dict:
    import requests
    import adsb_archive as arch
    session = requests.Session()
    session.headers.update({"User-Agent": "FlightTempo-observed-routes/1.0", "Accept": "application/vnd.github+json"})
    try:
        release, assets = arch.release_asset_specs(date, session)
    except RuntimeError as exc:
        return {"status": "no_archive", "detail": str(exc)}
    started, members, flights, rejected = time.monotonic(), 0, 0, Counter()
    with arch.HTTPRangeConcatReader(assets, session) as raw, tarfile.open(fileobj=raw, mode="r:") as tar:
        while members < max_members and flights < max_flights and time.monotonic() - started < budget_s:
            member = tar.next()
            if member is None:
                break
            name = member.name.replace("\\", "/").rsplit("/", 1)[-1].lower()
            if not member.isfile() or not name.startswith("trace_full_") or not 0 < member.size <= arch.MAX_TRACE_MEMBER_BYTES:
                continue
            members += 1
            doc, reason = arch.load_trace_member(tar, member)
            if reason:
                rejected[reason] += 1
                continue
            flights += process_document(doc, index, state["pairs"], date, rejected)
        requests_made = raw.range_requests
    state["processedDates"].append(date)
    return {"status": "ok", "release": release.get("tag_name"), "members": members, "flightsAdded": flights,
            "rejected": dict(rejected), "seconds": round(time.monotonic() - started), "rangeRequests": requests_made}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", help="UTC archive day YYYY-MM-DD (default: 3 days ago)")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--max-flights", type=int, default=400)
    ap.add_argument("--max-members", type=int, default=30000)
    ap.add_argument("--budget-minutes", type=float, default=70)
    ap.add_argument("--force", action="store_true", help="count the day again even if already processed")
    a = ap.parse_args()
    day = a.date or (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()
    state = load_existing(a.out)
    if day in state["processedDates"] and not a.force:
        print(f"{day} already processed; nothing to do")
        return 0
    index = AirportIndex(load_airports())
    result = scan_archive(day, index, state, a.max_flights, a.max_members, a.budget_minutes * 60)
    print(json.dumps(result, indent=1))
    if result["status"] != "ok":
        print("archive not available for that day: skipped cleanly, nothing published")
        return 0
    if result["flightsAdded"] == 0:
        print("no usable flights found: nothing published")
        return 0
    print(json.dumps(write_outputs(state, a.out), indent=1)[:600])
    return 0


if __name__ == "__main__":
    sys.exit(main())
