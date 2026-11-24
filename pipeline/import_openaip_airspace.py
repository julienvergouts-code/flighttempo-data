#!/usr/bin/env python3
"""Import openAIP airspace (CC BY-NC 4.0) as a separate, switchable, non-commercial layer.

Why separate: openAIP data is non-commercial. It lives in its own packs and its own manifest
dataset (``openaip_airspace``), is marked ``personalUseOnly`` and is only app-downloadable while
data/usage_scope.json says 'personal'. Nothing here is ever merged into the OFMA or FAA data.

Source: per-country GeoJSON exports (storage.openaip.net/openaip-system-exports/<cc>_asp.geojson).
If an export is not reachable and OPENAIP_API_KEY is set, the core API is used for that country.
With neither, the run skips cleanly (exit 0) and publishes nothing.

Gap filling: countries already covered by a verified source (data/airspace_priority.json) are skipped.
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
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "airspace/openaip"
INDEX = OUT_DIR / "index.json"
PRIORITY = ROOT / "data/airspace_priority.json"
EXPORT_URL = "https://storage.openaip.net/openaip-system-exports/{cc}_asp.geojson"
API_URL = "https://api.core.openaip.net/api/airspaces?country={cc}&limit=1000&page={page}"
UA = "FlightTempo-data/1.0 (+https://github.com/julienvergouts-code/flighttempo-data)"
ATTRIBUTION = "Contains data from openAIP (www.openaip.net), licensed CC BY-NC 4.0."
LICENSE_URL = "https://creativecommons.org/licenses/by-nc/4.0/"
MIN_GEOMETRY_SUCCESS = 0.90
MAX_UNKNOWN_TYPE_SHARE = 0.30
MAX_DROP_VS_PREVIOUS = 0.50
MAX_FEATURE_SPAN_DEG = 30.0
log = logging.getLogger("openaip")

ISO_COUNTRIES = (
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ "
    "CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR "
    "GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP "
    "KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT "
    "MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW "
    "SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG "
    "UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW"
).split()

# openAIP enums (third-party documented; unknown values are counted, never guessed).
TYPES = {0: "OTHER", 1: "R", 2: "D", 3: "P", 4: "CTR", 5: "TMZ", 6: "RMZ", 7: "TMA", 8: "TRA", 9: "TSA",
         12: "ADIZ", 13: "ATZ", 14: "MATZ", 17: "ALERT", 18: "WARNING", 19: "PROTECTED", 20: "HTZ",
         21: "GLIDING", 22: "TRP", 23: "TIZ", 24: "TIA", 25: "MTA", 26: "CTA", 27: "ACC_SECTOR",
         28: "SPORT", 29: "LOW_OVERFLIGHT", 30: "MRT", 31: "TFR", 32: "VFR_SECTOR", 33: "FIS_SECTOR",
         34: "LTA", 35: "UTA", 36: "MCTR"}
SKIPPED_TYPES = {10: "FIR", 11: "UIR", 15: "AIRWAY", 16: "MTR"}
CLASSES = {0: "A", 1: "B", 2: "C", 3: "D", 4: "E", 5: "F", 6: "G"}
ALTERATIONS = [
    "Reduced to type, class, name, vertical limits and outer polygon rings (other attributes dropped).",
    "Coordinates rounded to 5 decimal places; polygon holes are not kept.",
    "FIR, UIR and airway entries are excluded.",
]


class OpenAipError(Exception):
    pass


def vertical_limit(limit: Any) -> dict[str, Any]:
    """Convert an openAIP {value, unit, referenceDatum} object to {ft, ref}."""
    if not isinstance(limit, dict):
        return {"ft": None, "ref": "UNKNOWN"}
    value, unit, datum = limit.get("value"), limit.get("unit"), limit.get("referenceDatum")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return {"ft": None, "ref": "UNKNOWN"}
    if value == 0 and datum == 0:
        return {"ft": 0, "ref": "GND"}
    if unit == 6:
        ft, ref = value * 100, "FL"
    elif unit == 1:
        ft, ref = value, {0: "AGL", 1: "MSL", 2: "FL"}.get(datum, "UNKNOWN")
    else:
        return {"ft": None, "ref": "UNKNOWN"}
    if ref == "UNKNOWN" or not -2000 <= ft <= 100000:
        return {"ft": None, "ref": "UNKNOWN"}
    return {"ft": int(round(ft)), "ref": ref}


def outer_rings(geometry: Any) -> list[list[list[float]]]:
    """Outer rings as [[lat, lon], ...] (closed). Raises ValueError for unusable geometry."""
    if not isinstance(geometry, dict):
        raise ValueError("no geometry")
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    if kind == "Polygon":
        polygons = [coords]
    elif kind == "MultiPolygon":
        polygons = coords
    else:
        raise ValueError(f"unsupported geometry {kind}")
    rings = []
    for polygon in polygons or []:
        if not polygon:
            continue
        pts = []
        for lon, lat, *_ in polygon[0]:
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("coordinate out of range")
            pts.append([round(lat, 5), round(lon, 5)])
        if pts and pts[0] != pts[-1]:
            pts.append(pts[0])
        if len({tuple(p) for p in pts}) < 3:
            raise ValueError("fewer than three vertices")
        rings.append(pts)
    if not rings:
        raise ValueError("no rings")
    return rings


def parse_country(raw: bytes | dict, cc: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = json.loads(raw) if isinstance(raw, (bytes, str)) else raw
    items = data.get("features") if isinstance(data, dict) and "features" in data else data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise OpenAipError(f"{cc}: not a GeoJSON FeatureCollection or API page")
    stats: Counter = Counter()
    features, seen = [], set()
    for item in items:
        props = item.get("properties", item) if isinstance(item, dict) else {}
        geometry = item.get("geometry") if isinstance(item, dict) else None
        raw_type = props.get("type")
        if raw_type in SKIPPED_TYPES:
            stats["skipped_" + SKIPPED_TYPES[raw_type]] += 1
            continue
        stats["considered"] += 1
        if raw_type not in TYPES:
            stats["unknown_type"] += 1
        try:
            rings = outer_rings(geometry)
        except ValueError as exc:
            stats["geometry_failed"] += 1
            stats["geometry_failed:" + str(exc)[:40]] += 1
            continue
        lats = [p[0] for r in rings for p in r]
        lons = [p[1] for r in rings for p in r]
        if max(lats) - min(lats) > MAX_FEATURE_SPAN_DEG or max(lons) - min(lons) > MAX_FEATURE_SPAN_DEG:
            stats["geometry_failed"] += 1
            stats["geometry_failed:implausible span"] += 1
            continue
        name = str(props.get("name") or "").strip()
        source_id = str(props.get("_id") or props.get("id") or "")
        identity = "|".join((cc, source_id or name, str(raw_type)))
        fid = hashlib.sha256(identity.encode()).hexdigest()[:16]
        if fid in seen:
            stats["duplicate_id"] += 1
            continue
        seen.add(fid)
        features.append({
            "id": fid, "type": TYPES.get(raw_type, "UNKNOWN"), "name": name,
            "class": CLASSES.get(props.get("icaoClass"), ""),
            "lower": vertical_limit(props.get("lowerLimit")), "upper": vertical_limit(props.get("upperLimit")),
            "rings": rings,
            "bbox": [min(lats), min(lons), max(lats), max(lons)],
        })
    features.sort(key=lambda f: f["id"])
    return features, {"stats": dict(stats)}


def check_country(cc: str, features: list[dict[str, Any]], info: dict[str, Any], previous: int | None) -> None:
    stats = info["stats"]
    considered = stats.get("considered", 0)
    if not features:
        raise OpenAipError(f"{cc}: no usable airspaces; stats {stats}")
    if considered >= 10 and len(features) / considered < MIN_GEOMETRY_SUCCESS:
        raise OpenAipError(f"{cc}: geometry resolved for only {len(features) / considered:.1%}; stats {stats}")
    if considered and stats.get("unknown_type", 0) / considered > MAX_UNKNOWN_TYPE_SHARE:
        raise OpenAipError(f"{cc}: {stats['unknown_type']}/{considered} unknown type codes; the enum may have changed")
    if previous and previous >= 20 and len(features) < previous * (1 - MAX_DROP_VS_PREVIOUS):
        raise OpenAipError(f"{cc}: {len(features)} airspaces vs {previous} published before; refusing a sudden drop")


def pack_bytes(cc: str, features: list[dict[str, Any]]) -> bytes:
    body = {"schema": 1, "region": cc, "source": "openAIP", "license": "CC BY-NC 4.0", "licenseUrl": LICENSE_URL,
            "attribution": ATTRIBUTION, "usage": "non-commercial", "personalUseOnly": True,
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


def http_get(url: str, headers: dict[str, str] | None = None) -> bytes | None:
    """GET with retries; 401/403/404 mean 'not available here' and return None."""
    request = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 404):
                return None
            if attempt == 4:
                raise
        except (urllib.error.URLError, OSError):
            if attempt == 4:
                raise
        time.sleep(min(30, 2 ** (attempt + 1)))
    return None


def fetch_country(cc: str, api_key: str | None, getter=http_get) -> bytes | dict | None:
    raw = getter(EXPORT_URL.format(cc=cc.lower()))
    if raw is not None:
        return raw
    if not api_key:
        return None
    items, page = [], 1
    while True:
        chunk = getter(API_URL.format(cc=cc, page=page), {"x-openaip-api-key": api_key})
        if chunk is None:
            return None if page == 1 else {"items": items}
        data = json.loads(chunk)
        items.extend(data.get("items", []))
        if page >= int(data.get("totalPages", 1)):
            return {"items": items}
        page += 1


def covered_countries(path: Path = PRIORITY) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {cc for ccs in data.get("coveredByVerifiedSources", {}).values() for cc in ccs}


def build_index(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": 1, "format": "FlightTempo openAIP airspace packs (non-commercial layer)",
        "provider": "openAIP", "license": "CC BY-NC 4.0", "licenseUrl": LICENSE_URL,
        "attribution": ATTRIBUTION, "usage": "non-commercial", "personalUseOnly": True,
        "commercialUseAllowed": False,
        "licenseConditions": [
            "Show the openAIP attribution wherever the data is displayed.",
            "Non-commercial use only; switch this layer off (data/usage_scope.json) before any paid release.",
            "openAIP's homepage also says paid apps may ship the data if the data itself is not sold; get that in writing before relying on it.",
        ],
        "alterations": ALTERATIONS, "operationalUse": False,
        "notice": "Reference data only. Not certified, not for navigation or airspace-compliance decisions.",
        "regions": sorted(entries, key=lambda e: e["region"]),
    }


def run(out: Path = OUT_DIR, countries: list[str] | None = None, include_covered: bool = False,
        getter=http_get, api_key: str | None = None) -> int:
    wanted = [c.upper() for c in (countries or ISO_COUNTRIES)]
    if not include_covered:
        skip = covered_countries()
        wanted = [c for c in wanted if c not in skip]
    index_path = out / "index.json"
    existing: dict[str, dict[str, Any]] = {}
    if index_path.is_file():
        for e in json.loads(index_path.read_text(encoding="utf-8")).get("regions", []):
            existing[e["region"]] = e
    errors, written, reachable = [], 0, 0
    for cc in wanted:
        try:
            raw = fetch_country(cc, api_key, getter)
        except (urllib.error.URLError, OSError) as exc:
            errors.append(f"{cc}: download failed: {exc}")
            continue
        if raw is None:
            continue
        reachable += 1
        try:
            features, info = parse_country(raw, cc)
            check_country(cc, features, info, (existing.get(cc) or {}).get("featureCount"))
        except (OpenAipError, ValueError) as exc:
            errors.append(str(exc))
            log.error("%s failed: %s", cc, exc)
            continue
        data = pack_bytes(cc, features)
        atomic_write(out / f"{cc}.json.gz", data)
        existing[cc] = {"region": cc, "file": f"{cc}.json.gz", "featureCount": len(features),
                        "sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                        "types": dict(Counter(f["type"] for f in features))}
        written += 1
        log.info("%s: %d airspaces (%d bytes)", cc, len(features), len(data))
    if reachable == 0 and not errors:
        log.warning("openAIP exports not reachable and no usable API key: skipped cleanly, nothing published")
        return 0
    if existing:
        atomic_write(index_path, (json.dumps(build_index(list(existing.values())), indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    log.info("countries written %d, reachable %d, errors %d", written, reachable, len(errors))
    if errors:
        log.error("%d country problem(s); good countries were written: %s", len(errors), "; ".join(errors)[:1500])
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--country", action="append", help="ISO alpha-2 code (repeatable); default all")
    ap.add_argument("--include-covered", action="store_true", help="also build countries covered by verified sources")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(a.out, a.country, a.include_covered, api_key=os.environ.get("OPENAIP_API_KEY") or None)


if __name__ == "__main__":
    sys.exit(main())
