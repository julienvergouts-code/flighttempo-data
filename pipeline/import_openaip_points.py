#!/usr/bin/env python3
"""Import openAIP navaids (nav) and VFR reporting points (rpp) as non-commercial test layers (CC BY-NC).

Own files and own manifest datasets (openaip_navaids, openaip_reporting_points), marked personalUseOnly.
Countries covered by a verified source are skipped (data/airspace_priority.json: coveredNavaids / coveredReportingPoints).
Skips cleanly when openAIP is not reachable. Output: navigation/openaip/navaids.csv, data/openaip_reporting_points.csv.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import import_openaip_airspace as asp  # noqa: E402

NAV_OUT = ROOT / "navigation" / "openaip" / "navaids.csv"
RPP_OUT = ROOT / "data" / "openaip_reporting_points.csv"
EXPORT = "https://storage.openaip.net/openaip-system-exports/{cc}_{kind}.geojson"
FT_PER_M = 3.28084
log = logging.getLogger("openaip-points")
NAV_TYPES = {0: "DME", 1: "TACAN", 2: "NDB", 3: "VOR", 4: "VOR-DME", 5: "VORTAC", 6: "DVOR", 7: "DVOR-DME", 8: "DVORTAC"}
NAV_FIELDS = ["ident", "type", "name", "latitude", "longitude", "elevation_ft", "frequency", "channel", "country_code", "source", "license"]
RPP_FIELDS = ["country_code", "name", "latitude", "longitude", "compulsory", "elevation_ft", "source", "license"]
NAV_STATS = {"unknown_type": 0}


def elevation_ft(e: Any) -> str:
    if not isinstance(e, dict) or not isinstance(e.get("value"), (int, float)):
        return ""
    return str(int(round(e["value"] * FT_PER_M))) if e.get("unit") == 0 else str(int(round(e["value"]))) if e.get("unit") == 1 else ""


def frequency(f: Any) -> str:
    if not isinstance(f, dict) or f.get("value") in (None, ""):
        return ""
    unit = {1: "kHz", 2: "MHz"}.get(f.get("unit"), "")
    return f"{f['value']} {unit}".strip()


def point(feature: dict) -> tuple[float, float] | None:
    g = feature.get("geometry") or {}
    c = g.get("coordinates")
    if g.get("type") != "Point" or not c or len(c) < 2:
        return None
    lon, lat = c[0], c[1]
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return round(lat, 6), round(lon, 6)


def parse_navaids(raw: bytes | dict, cc: str) -> tuple[list[dict], dict]:
    data = json.loads(raw) if isinstance(raw, (bytes, str)) else raw
    rows, stats = [], {"considered": 0, "bad_geometry": 0, "unknown_type": 0}
    for f in data.get("features", []):
        p = f.get("properties", {})
        stats["considered"] += 1
        pt = point(f)
        if pt is None:
            stats["bad_geometry"] += 1
            continue
        t = p.get("type")
        if t not in NAV_TYPES:
            stats["unknown_type"] += 1
        rows.append({"ident": str(p.get("identifier") or "").strip(), "type": NAV_TYPES.get(t, "UNKNOWN"),
                     "name": str(p.get("name") or "").strip(), "latitude": pt[0], "longitude": pt[1],
                     "elevation_ft": elevation_ft(p.get("elevation")), "frequency": frequency(p.get("frequency")),
                     "channel": str(p.get("channel") or ""), "country_code": cc, "source": "openAIP", "license": "CC BY-NC 4.0"})
    return rows, stats


def parse_reporting_points(raw: bytes | dict, cc: str) -> tuple[list[dict], dict]:
    data = json.loads(raw) if isinstance(raw, (bytes, str)) else raw
    rows, stats = [], {"considered": 0, "bad_geometry": 0}
    for f in data.get("features", []):
        p = f.get("properties", {})
        stats["considered"] += 1
        pt = point(f)
        if pt is None or not str(p.get("name") or "").strip():
            stats["bad_geometry"] += 1
            continue
        rows.append({"country_code": cc, "name": str(p["name"]).strip(), "latitude": pt[0], "longitude": pt[1],
                     "compulsory": "true" if p.get("compulsory") else "false", "elevation_ft": elevation_ft(p.get("elevation")),
                     "source": "openAIP", "license": "CC BY-NC 4.0"})
    return rows, stats


def check(cc: str, kind: str, rows: list[dict], stats: dict) -> None:
    n = stats["considered"]
    if n and not rows:
        raise asp.OpenAipError(f"{cc} {kind}: no usable rows; stats {stats}")
    if n >= 10 and len(rows) / n < 0.9:
        raise asp.OpenAipError(f"{cc} {kind}: only {len(rows)}/{n} usable rows; stats {stats}")
    if kind == "nav" and n >= 5 and stats["unknown_type"] / n > 0.3:
        raise asp.OpenAipError(f"{cc} nav: {stats['unknown_type']}/{n} unknown type codes; the enum may have changed")


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    for r in sorted(rows, key=lambda r: tuple(str(r[k]) for k in fields)):
        w.writerow(r)
    asp.atomic_write(path, buf.getvalue().encode("utf-8"))


def covered(kind_key: str) -> set[str]:
    try:
        d = json.loads(asp.PRIORITY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {c for cs in d.get(kind_key, {}).values() for c in cs}


def run(nav_out: Path = NAV_OUT, rpp_out: Path = RPP_OUT, countries: list[str] | None = None, getter=asp.http_get,
        include_covered: bool = False) -> int:
    wanted = [c.upper() for c in (countries or asp.ISO_COUNTRIES)]
    skip_nav = set() if include_covered else covered("coveredNavaids")
    skip_rpp = set() if include_covered else covered("coveredReportingPoints")
    nav_rows, rpp_rows, errors, reachable = [], [], [], 0
    for cc in wanted:
        for kind, skip, parse, rows in (("nav", skip_nav, parse_navaids, nav_rows), ("rpp", skip_rpp, parse_reporting_points, rpp_rows)):
            if cc in skip:
                continue
            try:
                raw = getter(EXPORT.format(cc=cc.lower(), kind=kind))
            except Exception as exc:  # network trouble for one country must not stop the others
                errors.append(f"{cc} {kind}: download failed: {exc}")
                continue
            if raw is None:
                continue
            reachable += 1
            try:
                got, stats = parse(raw, cc)
                check(cc, kind, got, stats)
            except (asp.OpenAipError, ValueError) as exc:
                errors.append(str(exc))
                continue
            rows.extend(got)
    if reachable == 0 and not errors:
        log.warning("openAIP exports not reachable: skipped cleanly, nothing published")
        return 0
    if nav_rows:
        write_csv(nav_out, NAV_FIELDS, nav_rows)
    if rpp_rows:
        write_csv(rpp_out, RPP_FIELDS, rpp_rows)
    log.info("navaids %d, reporting points %d, errors %d", len(nav_rows), len(rpp_rows), len(errors))
    if errors:
        log.error("%s", "; ".join(errors)[:1500])
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--country", action="append")
    ap.add_argument("--include-covered", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(countries=a.country, include_covered=a.include_covered)


if __name__ == "__main__":
    sys.exit(main())
