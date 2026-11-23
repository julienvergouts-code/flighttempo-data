#!/usr/bin/env python3
"""Import OFMA OFMX airspace (CTR, TMA, ATZ, restricted areas...) as regional offline packs.

Source: OpenFlightMaps Association (OFMA) OFMX snapshots, General Users' License
(commercial use permitted; attribution; pass-through of the licence; alterations
must be communicated to OFMA within 15 days). Reference data only, never a
navigation or airspace-compliance database.

Alterations made by this importer (declared in index.json, GUL section 4.3):
  * circular and arc boundary segments are converted to polylines (<= 3 degree steps);
  * coordinates are rounded to 5 decimals (about 1 m);
  * boundaries that follow a geographic border (FNT) use the border line published in
    the same package; if it is missing they are approximated by straight lines and
    flagged ``approx``;
  * FIR/UIR records are not exported.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import logging
import math
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PIPELINE = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPELINE))
import import_ofma_ofmx_vfr_points as ofma  # noqa: E402  (shared discovery/download/coordinate code)

ROOT = PIPELINE.parent
CONFIG = ROOT / "data/ofma_ofmx_sources.json"
OUT_DIR = ROOT / "airspace/ofma"
INDEX = OUT_DIR / "index.json"

ATTRIBUTION = "Contains information from the open flightmaps database, see www.openflightmaps.org"
LICENSE_URL = "https://www.openflightmaps.org/live/downloads/20150306-GUL.pdf"
EXCLUDED_TYPES = {"FIR", "UIR", "FIR-P", "UIR-P", "AIRSPACE"}
EARTH_RADIUS_NM = 3440.065
ARC_STEP_DEG = 3.0
CYCLE_DAYS = 28
MIN_GEOMETRY_SUCCESS = float(os.getenv("OFMA_AIRSPACE_MIN_GEOMETRY_SUCCESS", "0.90"))
MAX_APPROX_SHARE = float(os.getenv("OFMA_AIRSPACE_MAX_APPROX_SHARE", "0.50"))
MIN_FEATURES = int(os.getenv("OFMA_AIRSPACE_MIN_FEATURES", "5"))
MAX_FEATURE_SPAN_DEG = 30.0
ALTERATIONS = [
    "Arc and circle boundary segments converted to polylines (3 degree steps).",
    "Coordinates rounded to 5 decimal places.",
    "Border-following (FNT) boundary segments drawn along the published border line; where that border is not in the package they are approximated by straight lines and flagged approx.",
    "FIR and UIR records not exported.",
]
UNITS_TO_FT = {"FT": 1.0, "FL": 100.0, "M": 3.280839895, "KM": 3280.839895}
UNITS_TO_NM = {"NM": 1.0, "KM": 0.539956803, "M": 0.000539956803, "FT": 0.000164578834}

log = logging.getLogger("ofma-airspace")


class AirspaceError(RuntimeError):
    pass


# ------------------------------------------------------------------ cycles

def cycle_effective(airac: str, today: date) -> date:
    """Effective date of the cycle in force on ``today`` (28-day series anchored 2026-01-22)."""
    n = (today - ofma.AIRAC_ANCHOR).days // CYCLE_DAYS
    return ofma.AIRAC_ANCHOR + timedelta(days=CYCLE_DAYS * n)


# ------------------------------------------------------------------ geometry

def _rad(x: float) -> float:
    return math.radians(x)


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2, dl = _rad(lat1), _rad(lat2), _rad(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360


def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = _rad(lat1), _rad(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(_rad(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(a)))


def destination(lat: float, lon: float, brg: float, dist_nm: float) -> tuple[float, float]:
    d, b, p1, l1 = dist_nm / EARTH_RADIUS_NM, _rad(brg), _rad(lat), _rad(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def arc_points(start: tuple[float, float], end: tuple[float, float], centre: tuple[float, float],
               radius_nm: float | None, clockwise: bool) -> list[tuple[float, float]]:
    """Points along an arc from ``start`` (exclusive) to ``end`` (inclusive)."""
    b0 = bearing(*centre, *start)
    b1 = bearing(*centre, *end)
    radius = radius_nm or (distance_nm(*centre, *start) + distance_nm(*centre, *end)) / 2
    sweep = (b1 - b0) % 360 if clockwise else -((b0 - b1) % 360)
    if abs(sweep) < 1e-9:
        sweep = 360.0 if clockwise else -360.0
    steps = max(1, math.ceil(abs(sweep) / ARC_STEP_DEG))
    points = [destination(*centre, b0 + sweep * k / steps, radius) for k in range(1, steps)]
    points.append(end)
    return points


def circle_ring(centre: tuple[float, float], radius_nm: float) -> list[tuple[float, float]]:
    steps = int(360 / ARC_STEP_DEG)
    ring = [destination(*centre, 360.0 * k / steps, radius_nm) for k in range(steps)]
    ring.append(ring[0])
    return ring


# ------------------------------------------------------------------ borders

BORDER_MAX_SNAP_NM = 3.0


def _flat_d2(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat = a[0] - b[0]
    dlon = (a[1] - b[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    return dlat * dlat + dlon * dlon


def nearest_index(border: list[tuple[float, float]], p: tuple[float, float]) -> tuple[int, float]:
    best, best_d = 0, float("inf")
    for i, v in enumerate(border):
        d = _flat_d2(v, p)
        if d < best_d:
            best, best_d = i, d
    return best, math.sqrt(best_d) * 60.0  # degrees -> NM


def border_between(border: list[tuple[float, float]], start: tuple[float, float],
                   end: tuple[float, float]) -> list[tuple[float, float]] | None:
    """Border vertices running from ``start`` to ``end`` (both exclusive of the endpoints themselves).

    Returns None when either end is not within BORDER_MAX_SNAP_NM of the border.
    A closed border (first == last) is walked the shorter way round.
    """
    if len(border) < 2:
        return None
    i, di = nearest_index(border, start)
    j, dj = nearest_index(border, end)
    if di > BORDER_MAX_SNAP_NM or dj > BORDER_MAX_SNAP_NM:
        return None
    if i == j:
        return []
    closed = border[0] == border[-1]
    if not closed:
        seg = border[i + 1:j] if i < j else border[j + 1:i][::-1]
        return seg
    ring = border[:-1]
    n = len(ring)
    i, j = i % n, j % n
    fwd = [ring[(i + k) % n] for k in range(1, (j - i) % n)]
    back = [ring[(i - k) % n] for k in range(1, (i - j) % n)]
    return fwd if len(fwd) <= len(back) else back


def collect_borders(root: ET.Element) -> dict[str, list[tuple[float, float]]]:
    borders: dict[str, list[tuple[float, float]]] = {}
    for node in root.iter():
        if local(node) != "gbr":
            continue
        name = txt(child(node, "GbrUid"), "txtName")
        if not name:
            continue
        pts = []
        for v in node.iter():
            if local(v) == "gbv":
                try:
                    pts.append(point(v, "geoLat", "geoLong"))
                except ValueError:
                    continue
        if len(pts) >= 2:
            borders.setdefault(name, pts)
    return borders


# ------------------------------------------------------------------ parsing helpers

local = ofma.local_name
clean = ofma.clean


def child(node: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in list(node) if local(c) == name.lower()), None)


def txt(node: ET.Element | None, name: str) -> str:
    if node is None:
        return ""
    found = child(node, name)
    return clean(found.text) if found is not None else ""


def number(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def vertical_limit(ase: ET.Element, which: str) -> dict[str, Any]:
    code = txt(ase, f"codeDistVer{which}").upper()
    raw = txt(ase, f"valDistVer{which}").upper()
    unit = txt(ase, f"uomDistVer{which}").upper() or "FT"
    if raw in {"GND", "SFC"} or code == "SFC":
        return {"ft": 0, "ref": "GND"}
    if raw == "UNL":
        return {"ft": None, "ref": "UNL"}
    value = number(raw)
    if value is None:
        return {"ft": None, "ref": "UNKNOWN"}
    ref = {"HEI": "AGL", "ALT": "MSL", "STD": "FL"}.get(code, "FL" if unit == "FL" else "MSL")
    factor = UNITS_TO_FT.get(unit, 1.0)
    return {"ft": int(round(value * factor)), "ref": ref}


def uid_key(uid: ET.Element | None, region: str) -> str | None:
    if uid is None:
        return None
    mid = clean(uid.attrib.get("mid"))
    if mid:
        return "mid:" + mid
    code_type, code_id = txt(uid, "codeType"), txt(uid, "codeId")
    return f"id:{region}|{code_type}|{code_id}" if code_id else None


def point(node: ET.Element, lat_name: str, lon_name: str) -> tuple[float, float]:
    lat = ofma.parse_coord(txt(node, lat_name))
    lon = ofma.parse_coord(txt(node, lon_name))
    if (lat == 0 and lon == 0) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("invalid coordinates")
    return lat, lon


class UnresolvedBorder(ValueError):
    """Boundary follows a border line that is not in the package, so no ring can be drawn."""


def ring_from_abd(abd: ET.Element, stats: Counter,
                  borders: dict[str, list[tuple[float, float]]] | None = None) -> tuple[list[tuple[float, float]], bool]:
    """Return (closed ring, approximated) for one Abd element."""
    circle = child(abd, "Circle")
    if circle is not None:
        centre = point(circle, "geoLatCen", "geoLongCen")
        unit = txt(circle, "uomRadius").upper() or "NM"
        radius = number(txt(circle, "valRadius"))
        if radius is None or radius <= 0:
            raise ValueError("circle without radius")
        stats["circles"] += 1
        return circle_ring(centre, radius * UNITS_TO_NM.get(unit, 1.0)), False
    items = []
    for avx in (c for c in list(abd) if local(c) == "avx"):
        kind = txt(avx, "codeType").upper()
        here = point(avx, "geoLat", "geoLong")
        centre = radius = None
        if kind in {"CWA", "CCA"}:
            centre = point(avx, "geoLatArc", "geoLongArc")
            unit = txt(avx, "uomRadiusArc").upper() or "NM"
            r = number(txt(avx, "valRadiusArc"))
            radius = r * UNITS_TO_NM.get(unit, 1.0) if r else None
        items.append((kind, here, centre, radius, txt(child(avx, "GbrUid"), "txtName")))
    if not items:
        raise ValueError("no boundary")
    ring: list[tuple[float, float]] = []
    approx = False
    for kind, here, centre, radius, border_name in items:
        if kind in {"CWA", "CCA"}:
            if not ring:  # an arc that opens the boundary starts at the closing vertex
                ring.append(items[-1][1] if len(items) > 1 else here)
            ring.extend(arc_points(ring[-1], here, centre, radius, kind == "CWA"))
            stats["arcs"] += 1
        else:
            if kind == "FNT" and ring:
                stats["border_segments"] += 1
                along = border_between(borders[border_name], ring[-1], here) if borders and border_name in borders else None
                if along is None:
                    approx = True
                    stats["border_segments_approximated"] += 1
                else:
                    ring.extend(along)
                    stats["border_segments_resolved"] += 1
            elif kind == "FNT":
                approx = True
                stats["border_segments"] += 1
            ring.append(here)
    distinct = {p for p in ring}
    if len(distinct) < 3:
        if any(i[0] == "FNT" for i in items):
            raise UnresolvedBorder("border-following boundary without border geometry")
        raise ValueError("fewer than three vertices")
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring, approx


def parse_airspace(raw: bytes, region: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = ET.fromstring(raw)
    borders = collect_borders(root)
    stats: Counter = Counter()
    stats["borders_available"] = len(borders)
    ases: dict[str, ET.Element] = {}
    ase_order: list[str] = []
    abds: dict[str, list[ET.Element]] = {}
    for node in root.iter():
        tag = local(node)
        if tag == "ase":
            uid = child(node, "AseUid")
            key = uid_key(uid, region)
            if key and key not in ases:
                ases[key] = node
                ase_order.append(key)
            stats["ase"] += 1
        elif tag == "abd":
            uid = child(node, "AbdUid")
            key = uid_key(child(uid, "AseUid") if uid is not None else None, region)
            if key:
                abds.setdefault(key, []).append(node)
            stats["abd"] += 1
    if not ases:
        tags = Counter(local(n) for n in root.iter()).most_common(15)
        raise AirspaceError(f"{region}: no Ase elements; schema or endpoint may have changed "
                            f"(counts {dict(stats)}; top tags {tags})")
    features: list[dict[str, Any]] = []
    types: Counter = Counter()
    samples: dict[str, str] = {}
    for key in ase_order:
        ase = ases[key]
        uid = child(ase, "AseUid")
        a_type = txt(uid, "codeType").upper()
        if a_type in EXCLUDED_TYPES:
            stats["excluded_type"] += 1
            continue
        if not abds.get(key):
            stats["no_boundary"] += 1
            continue
        stats["considered"] += 1
        rings, approx_any = [], False
        try:
            for abd in abds.get(key, []):
                ring, approx = ring_from_abd(abd, stats, borders)
                rings.append(ring)
                approx_any = approx_any or approx
            if not rings:
                raise ValueError("no boundary")
        except UnresolvedBorder:
            # Not a parse failure: the shape is defined only by a border line we do not have.
            stats["considered"] -= 1
            stats["unresolved_border"] += 1
            continue
        except ValueError as exc:
            stats["geometry_failed"] += 1
            stats["geometry_failed:" + str(exc)[:40]] += 1
            reason = str(exc)[:40]
            if reason not in samples:
                abd_text = clean(ET.tostring(abds[key][0], encoding="unicode"))[:1800]
                samples[reason] = clean(ET.tostring(uid, encoding="unicode"))[:200] + " >> " + abd_text
            continue
        lats = [p[0] for r in rings for p in r]
        lons = [p[1] for r in rings for p in r]
        if max(lats) - min(lats) > MAX_FEATURE_SPAN_DEG or max(lons) - min(lons) > MAX_FEATURE_SPAN_DEG:
            stats["geometry_failed"] += 1
            stats["geometry_failed:implausible span"] += 1
            continue
        code_id = txt(uid, "codeId")
        local_type = txt(ase, "txtLocalType")
        identity = "|".join((region, key, a_type, code_id))
        features.append({
            "id": hashlib.sha256(identity.encode()).hexdigest()[:16],
            "type": a_type or "UNKNOWN",
            **({"localType": local_type} if local_type else {}),
            "name": txt(ase, "txtName") or code_id,
            "class": txt(ase, "codeClass"),
            "lower": vertical_limit(ase, "Lower"),
            "upper": vertical_limit(ase, "Upper"),
            "rings": [[[round(p[0], 5), round(p[1], 5)] for p in r] for r in rings],
            "bbox": [round(min(lats), 5), round(min(lons), 5), round(max(lats), 5), round(max(lons), 5)],
            **({"approx": True} if approx_any else {}),
        })
        types[a_type or "UNKNOWN"] += 1
    stats["features"] = len(features)
    features.sort(key=lambda f: (f["type"], f["name"], f["id"]))
    return features, {"stats": dict(stats), "countsByType": dict(types), "failureSamples": samples}


def check_region(region: str, features: list[dict[str, Any]], info: dict[str, Any]) -> None:
    stats = info["stats"]
    considered = stats.get("considered", 0)
    if len(features) < MIN_FEATURES:
        raise AirspaceError(f"{region}: only {len(features)} airspaces (floor {MIN_FEATURES}); stats {stats}")
    success = len(features) / considered if considered else 0
    if success < MIN_GEOMETRY_SUCCESS:
        failures = {k: v for k, v in stats.items() if k.startswith("geometry_failed:")}
        raise AirspaceError(f"{region}: geometry resolved for only {success:.1%} of airspaces "
                            f"(floor {MIN_GEOMETRY_SUCCESS:.0%}); failures {failures}; abd={stats.get('abd')}; "
                            f"samples {info.get('failureSamples')!r}")
    approx = sum(bool(f.get("approx")) for f in features) / len(features)
    if approx > MAX_APPROX_SHARE:
        raise AirspaceError(f"{region}: {approx:.0%} of airspaces rely on approximated border segments")


# ------------------------------------------------------------------ output

def pack_bytes(region: str, airac: str, features: list[dict[str, Any]]) -> bytes:
    body = {"schema": 1, "region": region, "cycle": airac, "attribution": ATTRIBUTION,
            "license": "OFMA General Users License", "licenseUrl": LICENSE_URL,
            "alterations": ALTERATIONS, "features": features}
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(raw)
    return buf.getvalue()


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


def read_index(path: Path = INDEX) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def build_index(airac: str, effective: date, entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": 1, "format": "FlightTempo OFMA airspace packs", "cycle": airac,
        "effectiveDate": effective.isoformat(),
        "expiryDate": (effective + timedelta(days=CYCLE_DAYS - 1)).isoformat(),
        "provider": "OpenFlightMaps Association (OFMA)", "license": "OFMA General Users License",
        "licenseUrl": LICENSE_URL, "attribution": ATTRIBUTION, "commercialUseAllowed": True,
        "licenseConditions": [
            "Keep the OFMA attribution with the data.",
            "Pass the data on under the same GUL terms; no further restrictions (GUL 4.5).",
            "Communicate alterations to OFMA within 15 days (GUL 4.3).",
            "If users can alter the data, link the OFMA contributor site (GUL 4.4).",
        ],
        "alterations": ALTERATIONS,
        "operationalUse": False,
        "notice": "Reference data only. Not certified, not for navigation or airspace-compliance decisions.",
        "regions": sorted(entries, key=lambda e: e["region"]),
    }


def comparable(index: dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in index.items() if k != "generatedAtUtc"}, sort_keys=True)


def run(config: Path = CONFIG, today: date | None = None, only: list[str] | None = None,
        out_dir: Path = OUT_DIR, fetcher=None, force: bool = False) -> int:
    today = today or datetime.now(timezone.utc).date()
    cfg = json.loads(Path(config).read_text(encoding="utf-8"))
    airac = ofma.current_airac(today)
    effective = cycle_effective(airac, today)
    sources = [s for s in cfg["regions"] if not only or s["region"] in only]
    if not sources:
        raise AirspaceError("no OFMA regions selected")
    for source in sources:
        ofma.validate_source(source)
    previous = {e["region"]: e for e in read_index(out_dir / "index.json").get("regions", [])}
    if not force and all(previous.get(s["region"], {}).get("cycle") == airac for s in sources):
        log.info("Cycle %s already published for all selected regions; nothing to do.", airac)
        return 0
    entries: dict[str, dict[str, Any]] = dict(previous)
    failures: list[str] = []
    for source in sources:
        region = source["region"]
        try:
            if fetcher:
                xml = fetcher(source, airac)
            else:
                package_url, *_ = ofma.resolve_ofmx_source(source, airac)
                raw, _ = ofma.fetch(package_url)
                xml = ofma.xml_from_zip(raw, source)
            features, info = parse_airspace(xml, region)
            check_region(region, features, info)
            data = pack_bytes(region, airac, features)
            name = f"{region}.json.gz"
            existing = out_dir / name
            if not existing.is_file() or existing.read_bytes() != data:
                atomic_write(existing, data)
            lats = [f["bbox"][0] for f in features] + [f["bbox"][2] for f in features]
            lons = [f["bbox"][1] for f in features] + [f["bbox"][3] for f in features]
            entries[region] = {
                "region": region, "regionName": source["regionName"], "file": name,
                "cycle": airac, "featureCount": len(features), "countsByType": info["countsByType"],
                "bbox": [min(lats), min(lons), max(lats), max(lons)],
                "sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            }
            log.info("%s: %d airspaces %s", region, len(features), info["countsByType"])
        except Exception as exc:  # keep going: one region must not block the rest
            failures.append(f"{region}: {exc}")
            log.error("%s failed: %s", region, exc)
            if os.getenv("GITHUB_STEP_SUMMARY"):
                with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as h:
                    h.write(f"- OFMA airspace {region} FAILED: {exc}\n")
    if not entries:
        raise AirspaceError("no region produced a pack: " + "; ".join(failures))
    index = build_index(airac, effective, list(entries.values()))
    old = read_index(out_dir / "index.json")
    if comparable(old) != comparable(index):
        index["generatedAtUtc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        atomic_write(out_dir / "index.json", (json.dumps(index, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    if failures:
        raise AirspaceError(f"{len(failures)} region(s) failed; successful regions were written: " + "; ".join(failures))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today")
    parser.add_argument("--region", action="append", help="Limit to these OFMA region codes")
    parser.add_argument("--force", action="store_true", help="Re-download even if the cycle is already published")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return run(today=date.fromisoformat(args.today) if args.today else None, only=args.region, force=args.force)
    except AirspaceError as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
