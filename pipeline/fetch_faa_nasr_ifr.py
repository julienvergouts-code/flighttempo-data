#!/usr/bin/env python3
"""FlightTempo IFR reference importer: FAA NASR fixes, navaids and airway segments.

Source: FAA Aeronautical Information Services 28-day NASR subscription
(FIX_CSV, NAV_CSV and AWY_CSV groups). These are US Government public-domain
data with exact coordinates and an exact effective cycle.

Design rules (they mirror the rest of this repository):
* Only a cycle whose effective date has already passed is imported, so the app
  never receives a preview cycle early and never loses the current one.
* All three groups must come from the same cycle (referential integrity).
* An airway segment is published only when BOTH endpoints resolve to exactly one
  coordinate. Ambiguous or unknown identifiers are rejected, never guessed.
* The importer fails closed: size floors, a maximum rejection rate and a
  missing-column check stop a truncated or reshaped download from being
  committed. Nothing is written until everything has been validated.

This is reference data for planning practice. It is not an approved operational
navigation database.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import math
import os
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_vfr_points as http  # noqa: E402  (shared FAA HTTP helpers)

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "navigation" / "faa_nasr"
INDEX_URL = http.INDEX_URL
CYCLE_ANCHOR = date(2026, 11, 26)  # a known NASR effective date; cycles repeat every 28 days
CYCLE_DAYS = 28
CYCLE_PAGE = INDEX_URL + "{date}"

MAX_UNRESOLVED_RATE = float(os.getenv("NASR_MAX_UNRESOLVED_RATE", "0.05"))
MAX_SEQUENCE_MISMATCH_RATE = float(os.getenv("NASR_MAX_SEQUENCE_MISMATCH_RATE", "0.05"))
MIN_FIXES = int(os.getenv("NASR_MIN_FIXES", "10000"))
MIN_NAVAIDS = int(os.getenv("NASR_MIN_NAVAIDS", "500"))
MIN_SEGMENTS = int(os.getenv("NASR_MIN_SEGMENTS", "1000"))
MAX_SEGMENT_NM = 2000.0

FIX_COLUMNS = ["ident", "latitude", "longitude", "state_code", "icao_region_code",
               "fix_use", "source", "cycle_effective"]
NAVAID_COLUMNS = ["ident", "type", "name", "latitude", "longitude", "elevation_ft",
                  "frequency", "state_code", "country_code", "status", "source",
                  "cycle_effective"]
SEGMENT_COLUMNS = ["airway_id", "airway_location", "airway_family", "segment_seq",
                   "from_ident", "from_kind", "from_latitude", "from_longitude",
                   "to_ident", "to_kind", "to_latitude", "to_longitude",
                   "distance_nm", "mag_course", "min_enroute_alt_ft", "source",
                   "cycle_effective"]

REQUIRED = {
    "fix": {"FIX_ID", "LAT_DECIMAL", "LONG_DECIMAL"},
    "nav": {"NAV_ID", "NAV_TYPE", "LAT_DECIMAL", "LONG_DECIMAL"},
    "awy": {"AWY_ID", "FROM_POINT"},
}
ARCHIVE_NAMES = {"fix": "FIX_CSV", "nav": "NAV_CSV", "awy": "AWY_CSV"}
FIX_HINTS = ("REP", "WAY", "FIX", "CNF", "INTERS", "RNAV", "WP")
NAV_HINTS = ("VOR", "NDB", "DME", "TACAN", "ILS", "LOC")
VFR_POINT_RE = re.compile(r"VP[A-Z0-9]{3}")

log = logging.getLogger("faa-nasr-ifr")


class NasrError(RuntimeError):
    """Raised for any condition that must stop publication."""


# --------------------------------------------------------------------------- cycles

def cycle_effective_on_or_before(today: date) -> date:
    steps = (today - CYCLE_ANCHOR).days // CYCLE_DAYS
    return CYCLE_ANCHOR + timedelta(days=CYCLE_DAYS * steps)


def cycle_expiry(effective: date) -> date:
    """Last day of validity (inclusive); the next cycle is effective 28 days later."""
    return effective + timedelta(days=CYCLE_DAYS - 1)


def find_archive_links(html: str, page_url: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for href in re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I):
        url = urljoin(page_url, href)
        name = url.rsplit("/", 1)[-1].upper()
        for key, stem in ARCHIVE_NAMES.items():
            if name.endswith(stem + ".ZIP"):
                found.setdefault(key, url)
    return found


# --------------------------------------------------------------------------- reading

def norm_row(row: dict[str, Any]) -> dict[str, str]:
    return {str(k).strip().upper(): http.clean(v) for k, v in row.items() if k is not None}


def _csv_members(zf: zipfile.ZipFile) -> list[str]:
    return [n for n in zf.namelist() if n.lower().endswith(".csv")]


def read_group_rows(zip_path: Path, kind: str) -> list[dict[str, str]]:
    """Return rows of the first CSV member that carries every required column.

    Handles a CSV directly inside the archive or inside one nested archive. For
    airways several member files exist, so the member with the required columns
    (and, preferring segment files, the most columns) wins.
    """
    required = REQUIRED[kind]
    seen_headers: list[str] = []
    best: tuple[int, list[dict[str, str]]] | None = None

    def consider(name: str, handle) -> None:
        nonlocal best
        text = io.TextIOWrapper(handle, encoding="utf-8-sig", errors="replace", newline="")
        reader = csv.DictReader(text)
        header = {h.strip().upper() for h in (reader.fieldnames or [])}
        seen_headers.append(f"{name}: {sorted(header)[:40]}")
        if not required.issubset(header):
            return
        if kind == "fix" and "fix_base" not in name.lower():
            return
        if kind == "nav" and "nav_base" not in name.lower():
            return
        if kind == "awy" and "awy_seg" not in name.lower():
            return
        rows = [norm_row(r) for r in reader]
        score = len(header)
        if best is None or score > best[0]:
            best = (score, rows)

    with zipfile.ZipFile(zip_path) as outer:
        for name in _csv_members(outer):
            with outer.open(name) as member:
                consider(name, member)
        for nested in [n for n in outer.namelist() if n.lower().endswith(".zip")]:
            with tempfile.TemporaryDirectory(prefix="nasr-nested-") as td:
                inner_path = Path(td) / "inner.zip"
                with outer.open(nested) as src, inner_path.open("wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
                with zipfile.ZipFile(inner_path) as inner:
                    for name in _csv_members(inner):
                        with inner.open(name) as member:
                            consider(f"{nested}/{name}", member)
    if best is None:
        raise NasrError(
            f"No CSV with required columns {sorted(required)} found for {kind}. "
            f"Headers seen: {' | '.join(seen_headers) or 'none'}"
        )
    return best[1]


# --------------------------------------------------------------------------- parsing

def _coord(row: dict[str, str]) -> tuple[float, float] | None:
    try:
        lat, lon = float(row["LAT_DECIMAL"]), float(row["LONG_DECIMAL"])
    except (KeyError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    return round(lat, 6), round(lon, 6)


def parse_fixes(rows: Iterable[dict[str, str]], effective: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    out, stats = [], {"vfr_reporting_points_skipped": 0, "rejected": 0}
    for row in rows:
        ident = row.get("FIX_ID", "").upper()
        coord = _coord(row)
        if not ident or coord is None:
            stats["rejected"] += 1
            continue
        if VFR_POINT_RE.fullmatch(ident):
            stats["vfr_reporting_points_skipped"] += 1  # published in data/vfr_points.csv
            continue
        out.append({"ident": ident, "latitude": coord[0], "longitude": coord[1],
                    "state_code": row.get("STATE_CODE", "").upper(),
                    "icao_region_code": row.get("ICAO_REGION_CODE", "").upper(),
                    "fix_use": row.get("FIX_USE_CODE", ""),
                    "source": "FAA_NASR_FIX", "cycle_effective": effective})
    out.sort(key=lambda r: (r["ident"], r["state_code"], r["icao_region_code"], r["latitude"], r["longitude"]))
    return out, stats


def parse_navaids(rows: Iterable[dict[str, str]], effective: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    out, stats = [], {"rejected": 0}
    for row in rows:
        ident = row.get("NAV_ID", "").upper()
        coord = _coord(row)
        if not ident or coord is None:
            stats["rejected"] += 1
            continue
        elev = re.sub(r"[^0-9.\-]", "", row.get("ELEV", ""))
        out.append({"ident": ident, "type": row.get("NAV_TYPE", "").upper(),
                    "name": row.get("NAME", ""), "latitude": coord[0], "longitude": coord[1],
                    "elevation_ft": elev, "frequency": row.get("FREQ", ""),
                    "state_code": row.get("STATE_CODE", "").upper(),
                    "country_code": row.get("COUNTRY_CODE", "").upper(),
                    "status": row.get("NAV_STATUS", "").upper(),
                    "source": "FAA_NASR_NAV", "cycle_effective": effective})
    out.sort(key=lambda r: (r["ident"], r["type"], r["state_code"], r["latitude"], r["longitude"]))
    return out, stats


# --------------------------------------------------------------------------- airways

def build_index(fixes: list[dict[str, Any]], navaids: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for f in fixes:
        index.setdefault(f["ident"], []).append({
            "kind": "FIX", "lat": f["latitude"], "lon": f["longitude"],
            "state": f["state_code"], "region": f["icao_region_code"]})
    for n in navaids:
        index.setdefault(n["ident"], []).append({
            "kind": "NAV", "lat": n["latitude"], "lon": n["longitude"],
            "state": n["state_code"], "region": ""})
    return index


def kind_hint(point_type: str) -> str:
    text = point_type.upper()
    if any(h in text for h in NAV_HINTS):
        return "NAV"
    if any(h in text for h in FIX_HINTS):
        return "FIX"
    return ""


def resolve_point(index: dict[str, list[dict[str, Any]]], ident: str, point_type: str,
                  state: str, region: str) -> tuple[str, float, float] | None:
    """Return (kind, lat, lon) only when exactly one coordinate is possible."""
    candidates = index.get(ident.upper(), [])
    if not candidates:
        return None
    hint = kind_hint(point_type)
    if hint and any(c["kind"] == hint for c in candidates):
        candidates = [c for c in candidates if c["kind"] == hint]
    if state and any(c["state"] == state for c in candidates):
        candidates = [c for c in candidates if c["state"] == state]
    if region and any(c["region"] == region for c in candidates):
        candidates = [c for c in candidates if c["region"] == region]
    coords = {(c["lat"], c["lon"]) for c in candidates}
    if len(coords) != 1:
        return None
    kinds = {c["kind"] for c in candidates}
    lat, lon = next(iter(coords))
    return (next(iter(kinds)) if len(kinds) == 1 else (hint or "FIX")), lat, lon


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * 3440.065 * math.asin(min(1.0, math.sqrt(a)))


def airway_family(airway_id: str) -> str:
    match = re.match(r"[A-Z]+", airway_id.upper())
    return match.group(0) if match else ""


def _seq_key(row: dict[str, str], position: int) -> tuple[int, int]:
    try:
        return (int(float(row.get("POINT_SEQ", ""))), position)
    except ValueError:
        return (position, position)


def build_segments(rows: list[dict[str, str]], index: dict[str, list[dict[str, Any]]],
                   effective: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Turn ordered airway point records into coordinate-bearing segments."""
    groups: dict[tuple[str, str], list[tuple[int, dict[str, str]]]] = {}
    for position, row in enumerate(rows):
        airway_id = row.get("AWY_ID", "").upper()
        if airway_id and row.get("FROM_POINT"):
            groups.setdefault((row.get("AWY_LOCATION", "").upper(), airway_id), []).append((position, row))

    segments: list[dict[str, Any]] = []
    stats: dict[str, Any] = {"airways": len(groups), "candidate_segments": 0, "unresolved": 0,
                             "implausible_length": 0, "gap_breaks": 0,
                             "sequence_checks": 0, "sequence_mismatches": 0,
                             "unresolved_examples": []}

    for (location, airway_id), members in sorted(groups.items()):
        ordered = [row for _, row in sorted(members, key=lambda m: _seq_key(m[1], m[0]))]
        points = [(r["FROM_POINT"].upper(), r.get("FROM_PT_TYPE", ""), r.get("STATE_CODE", "").upper(),
                   r.get("ICAO_REGION_CODE", "").upper(), r.get("AWY_SEG_GAP_FLAG", "").upper() == "Y",
                   r) for r in ordered]
        last = ordered[-1]
        last_to = last.get("TO_POINT", "").upper()
        if last_to and last_to != points[-1][0]:
            points.append((last_to, "", last.get("STATE_CODE", "").upper(),
                           last.get("ICAO_REGION_CODE", "").upper(), False, last))
        family = airway_family(airway_id)
        seq = 0
        for i in range(len(points) - 1):
            a, b = points[i], points[i + 1]
            src_row = a[5]
            to_declared = src_row.get("TO_POINT", "").upper()
            if a[4]:
                stats["gap_breaks"] += 1
                continue
            if to_declared:
                stats["sequence_checks"] += 1
                if to_declared != b[0]:
                    stats["sequence_mismatches"] += 1
            stats["candidate_segments"] += 1
            start = resolve_point(index, a[0], a[1], a[2], a[3])
            end = resolve_point(index, b[0], b[1], b[2], b[3])
            if start is None or end is None:
                stats["unresolved"] += 1
                if len(stats["unresolved_examples"]) < 50:
                    stats["unresolved_examples"].append(f"{airway_id}:{a[0]}->{b[0]}")
                continue
            dist = haversine_nm(start[1], start[2], end[1], end[2])
            if dist > MAX_SEGMENT_NM:
                stats["implausible_length"] += 1
                stats["unresolved"] += 1
                continue
            seq += 1
            mea = re.sub(r"[^0-9]", "", src_row.get("MIN_ENROUTE_ALT", ""))
            segments.append({
                "airway_id": airway_id, "airway_location": location, "airway_family": family,
                "segment_seq": seq, "from_ident": a[0], "from_kind": start[0],
                "from_latitude": start[1], "from_longitude": start[2],
                "to_ident": b[0], "to_kind": end[0], "to_latitude": end[1], "to_longitude": end[2],
                "distance_nm": round(dist, 1), "mag_course": src_row.get("MAG_COURSE", ""),
                "min_enroute_alt_ft": mea, "source": "FAA_NASR_AWY", "cycle_effective": effective})
    return segments, stats


# --------------------------------------------------------------------------- guards and output

def check_guards(fixes: list, navaids: list, segments: list, seg_stats: dict[str, Any]) -> None:
    if len(fixes) < MIN_FIXES:
        raise NasrError(f"Only {len(fixes)} fixes; floor is {MIN_FIXES}. Refusing to publish a truncated download.")
    if len(navaids) < MIN_NAVAIDS:
        raise NasrError(f"Only {len(navaids)} navaids; floor is {MIN_NAVAIDS}.")
    if len(segments) < MIN_SEGMENTS:
        raise NasrError(f"Only {len(segments)} airway segments; floor is {MIN_SEGMENTS}.")
    candidates = seg_stats["candidate_segments"]
    if candidates and seg_stats["unresolved"] / candidates > MAX_UNRESOLVED_RATE:
        raise NasrError(
            f"{seg_stats['unresolved']}/{candidates} airway segments have unresolved endpoints "
            f"(limit {MAX_UNRESOLVED_RATE:.0%}). Examples: {seg_stats['unresolved_examples'][:10]}")
    checks = seg_stats["sequence_checks"]
    if checks and seg_stats["sequence_mismatches"] / checks > MAX_SEQUENCE_MISMATCH_RATE:
        raise NasrError(
            f"{seg_stats['sequence_mismatches']}/{checks} airway rows disagree with the next point in sequence; "
            "the AWY file layout probably changed.")


def csv_bytes(columns: list[str], rows: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def build_meta(effective: date, files: dict[str, tuple[bytes, int]], archives: dict[str, dict[str, Any]],
               stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "FAA Aeronautical Information Services, 28 Day NASR Subscription",
        "sourceUrl": INDEX_URL,
        "license": "US Government public-domain data",
        "licenseStatus": "public_domain",
        "attribution": "Federal Aviation Administration, Aeronautical Information Services, NASR.",
        "coverage": "United States National Airspace System (FIX, NAV and AWY groups, one cycle)",
        "effectiveDate": effective.isoformat(),
        "expiryDate": cycle_expiry(effective).isoformat(),
        "dataCycle": effective.isoformat(),
        "operationalUse": "Reference only. Not an approved operational navigation database.",
        "files": {name: {"sha256": hashlib.sha256(raw).hexdigest(), "sizeBytes": len(raw), "recordCount": count}
                  for name, (raw, count) in files.items()},
        "sourceArchives": archives,
        "importStatistics": stats,
    }


def write_outputs(out_dir: Path, effective: date, fixes: list, navaids: list, segments: list,
                  archives: dict[str, dict[str, Any]], stats: dict[str, Any]) -> bool:
    """Write CSVs and meta.json. Returns True if anything changed."""
    files = {
        "fixes.csv": (csv_bytes(FIX_COLUMNS, fixes), len(fixes)),
        "navaids.csv": (csv_bytes(NAVAID_COLUMNS, navaids), len(navaids)),
        "airway_segments.csv": (csv_bytes(SEGMENT_COLUMNS, segments), len(segments)),
    }
    meta = build_meta(effective, files, archives, stats)
    meta_path = out_dir / "meta.json"
    changed = False
    previous = None
    if meta_path.exists():
        try:
            previous = json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError:
            previous = None
    comparable = lambda m: {k: v for k, v in (m or {}).items() if k != "generatedAtUtc"}  # noqa: E731
    if previous is not None and comparable(previous) == comparable(meta):
        log.info("No change in NASR cycle %s; leaving published files untouched.", effective)
        return False
    for name, (raw, _) in files.items():
        atomic_write(out_dir / name, raw)
        changed = True
    meta["generatedAtUtc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    atomic_write(meta_path, (json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return changed


# --------------------------------------------------------------------------- orchestration

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_cycle(effective: date, workdir: Path) -> tuple[dict[str, Path], dict[str, dict[str, Any]]]:
    page_url = CYCLE_PAGE.format(date=effective.isoformat())
    response = http.get(page_url)
    response.raise_for_status()
    links = find_archive_links(response.text, page_url)
    missing = [k for k in ARCHIVE_NAMES if k not in links]
    if missing:
        raise NasrError(f"Cycle page {page_url} lacks archive link(s) for: {', '.join(missing)}")
    paths: dict[str, Path] = {}
    meta: dict[str, dict[str, Any]] = {}
    for kind, url in links.items():
        target = workdir / f"{ARCHIVE_NAMES[kind]}.zip"
        log.info("Downloading %s", url)
        http.download_to(url, target)
        paths[kind] = target
        meta[kind] = {"url": url, "sha256": sha256_file(target), "sizeBytes": target.stat().st_size}
    return paths, meta


def run(effective: date, zips: dict[str, Path], archives: dict[str, dict[str, Any]], out_dir: Path) -> bool:
    eff = effective.isoformat()
    fixes, fix_stats = parse_fixes(read_group_rows(zips["fix"], "fix"), eff)
    navaids, nav_stats = parse_navaids(read_group_rows(zips["nav"], "nav"), eff)
    index = build_index(fixes, navaids)
    segments, seg_stats = build_segments(read_group_rows(zips["awy"], "awy"), index, eff)
    check_guards(fixes, navaids, segments, seg_stats)
    stats = {"fixes": fix_stats, "navaids": nav_stats, "airways": seg_stats}
    log.info("NASR %s: %d fixes, %d navaids, %d segments (%d/%d unresolved)", eff, len(fixes),
             len(navaids), len(segments), seg_stats["unresolved"], seg_stats["candidate_segments"])
    return write_outputs(out_dir, effective, fixes, navaids, segments, archives, stats)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today", help="Override today's date (YYYY-MM-DD) for cycle selection.")
    parser.add_argument("--cycle", help="Force a cycle effective date (YYYY-MM-DD).")
    parser.add_argument("--zip-dir", type=Path,
                        help="Use FIX_CSV.zip, NAV_CSV.zip and AWY_CSV.zip from this folder instead of downloading "
                             "(requires --cycle).")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.zip_dir:
        if not args.cycle:
            parser.error("--zip-dir requires --cycle so the cycle dates are never guessed")
        effective = date.fromisoformat(args.cycle)
        zips = {k: args.zip_dir / f"{stem}.zip" for k, stem in ARCHIVE_NAMES.items()}
        missing = [str(p) for p in zips.values() if not p.is_file()]
        if missing:
            parser.error("missing archive(s): " + ", ".join(missing))
        archives = {k: {"url": "local-file", "sha256": sha256_file(p), "sizeBytes": p.stat().st_size}
                    for k, p in zips.items()}
        changed = run(effective, zips, archives, args.out)
        print("Updated" if changed else "No change")
        return 0

    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    first = date.fromisoformat(args.cycle) if args.cycle else cycle_effective_on_or_before(today)
    last_error: Exception | None = None
    for effective in (first, first - timedelta(days=CYCLE_DAYS)):
        try:
            with tempfile.TemporaryDirectory(prefix="flighttempo-nasr-") as td:
                zips, archives = download_cycle(effective, Path(td))
                changed = run(effective, zips, archives, args.out)
            print("Updated" if changed else "No change")
            return 0
        except Exception as exc:  # try the previous cycle once, then fail loudly
            last_error = exc
            log.warning("NASR cycle %s failed: %s", effective, exc)
            if args.cycle:
                break
    raise NasrError(f"No usable NASR cycle: {last_error}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except NasrError as exc:
        log.error("%s", exc)
        sys.exit(1)
