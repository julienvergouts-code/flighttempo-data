#!/usr/bin/env python3
"""Import France SIA eAIP ENR data (fixes, navaids, airway segments, airspace polygons).

Source: the free "ZIP eAIP complet" product (SIA Licence Ouverte), read page by page from the SIA web eAIP.
The licence/product check is the same live check used for the SID/STAR import. If the SIA site is not
reachable (it only is from some networks) the run ends cleanly without touching any published file.

Outputs
  navigation/sia_france/{fixes,navaids,airway_segments}.csv + meta.json   (same columns as FAA NASR)
  airspace/sia/FR.json.gz + airspace/sia/index.json                       (same pack schema as openAIP/OFMA)
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import sys
import tempfile
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "pipeline"))
import fetch_faa_nasr_ifr as nasr  # noqa: E402
import fetch_sia_eaip_procedure_data as sia  # noqa: E402
import sia_enr_parse as parse  # noqa: E402

NAV_DIR = ROOT / "navigation" / "sia_france"
AIRSPACE_DIR = ROOT / "airspace" / "sia"
PAGE_LIMIT = 40 * 1024 * 1024
AIRSPACE_PAGES = (("FR-ENR-2.1-fr-FR.html", "enr2"), ("FR-ENR-2.2-fr-FR.html", "enr2"),
                  ("FR-ENR-5.1-fr-FR.html", "enr5"))
ATTRIBUTION = ("Source : SIA / DGAC, eAIP France, Licence Ouverte. Donnees retraitees par FlightTempo "
               "(geometrie simplifiee). Date de derniere mise a jour : cycle AIRAC {cycle}.")
ALTERATIONS = ("Coordinates converted from DMS, arcs/circles approximated by polylines, national-border "
               "segments joined by straight lines (flagged approx), vertical limits normalised to feet.")
MIN_COUNTS = {"fixes": 300, "navaids": 50, "airway_segments": 300, "airspace": 100}
MAX_DROP = 0.30


class SiaError(Exception):
    pass


def http_get(url: str, attempts: int = 4) -> str | None:
    """Fetch text with retries. None = unreachable/not found (clean skip), exception only for bad data."""
    last = None
    for attempt in range(attempts):
        try:
            with urlopen(Request(url, headers={"User-Agent": sia.USER_AGENT}), timeout=90) as r:
                raw = r.read(PAGE_LIMIT + 1)
            if len(raw) > PAGE_LIMIT:
                raise SiaError(f"page exceeds safety limit: {url}")
            return raw.decode("utf-8", "replace")
        except HTTPError as exc:
            last = exc
            if exc.code in (401, 403, 404):
                break
        except (URLError, OSError) as exc:
            last = exc
        time.sleep(min(20, 2 ** (attempt + 1)))
    print(f"unreachable: {url}: {last}", file=sys.stderr)
    return None


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


def csv_bytes(columns: list[str], rows: list[dict]) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    w.writeheader()
    for row in rows:
        w.writerow({c: row.get(c, "") for c in columns})
    return buf.getvalue().encode("utf-8")


def previous_count(meta_path: Path, name: str) -> int | None:
    try:
        return int(json.loads(meta_path.read_text(encoding="utf-8"))["files"][name]["recordCount"])
    except (OSError, ValueError, KeyError):
        return None


def guard(kind: str, count: int, previous: int | None) -> None:
    if count < MIN_COUNTS[kind]:
        raise SiaError(f"{kind}: only {count} records (minimum {MIN_COUNTS[kind]}); page layout may have changed")
    if previous and previous >= 100 and count < previous * (1 - MAX_DROP):
        raise SiaError(f"{kind}: {count} records vs {previous} published; refusing a sudden drop")


def build_tables(pages: dict[str, str], cycle_effective: str) -> dict[str, list[dict]]:
    src = f"SIA_eAIP_{cycle_effective}"
    out: dict[str, list[dict]] = {}
    if "FR-ENR-4.4-fr-FR.html" in pages:
        rows = parse.parse_fixes(parse.iter_rows(pages["FR-ENR-4.4-fr-FR.html"]))
        out["fixes"] = [{"ident": r["ident"], "latitude": r["latitude"], "longitude": r["longitude"],
                         "state_code": "FR", "icao_region_code": "LF", "fix_use": r["routes"],
                         "source": src, "cycle_effective": cycle_effective} for r in rows]
    if "FR-ENR-4.1-fr-FR.html" in pages:
        rows = parse.parse_navaids(parse.iter_rows(pages["FR-ENR-4.1-fr-FR.html"]))
        out["navaids"] = [{"ident": r["ident"], "type": r["type"], "name": r["name"], "latitude": r["latitude"],
                           "longitude": r["longitude"], "elevation_ft": r["elevation_ft"], "frequency": r["frequency"],
                           "state_code": "FR", "country_code": "FR", "status": "OPERATIONAL", "source": src,
                           "cycle_effective": cycle_effective} for r in rows]
    if "FR-ENR-3.2-fr-FR.html" in pages:
        segs = parse.route_segments(parse.parse_routes(parse.iter_rows(pages["FR-ENR-3.2-fr-FR.html"])))
        out["airway_segments"] = [{**s, "airway_location": "FR", "airway_family": s["airway_id"][0],
                                   "from_kind": "", "to_kind": "", "source": src,
                                   "cycle_effective": cycle_effective} for s in segs]
    return out


def build_airspace(pages: dict[str, str]) -> tuple[list[dict], dict[str, int]]:
    features: list[dict] = []
    totals: Counter = Counter()
    seen: set[str] = set()
    for name, section in AIRSPACE_PAGES:
        if name not in pages:
            continue
        feats, stats = parse.parse_airspace(parse.iter_rows(pages[name]), section)
        totals.update(stats)
        for f in feats:
            if f["id"] not in seen:
                seen.add(f["id"])
                features.append(f)
    features.sort(key=lambda f: f["id"])
    return features, dict(totals)


def pack_bytes(features: list[dict], cycle: dict) -> bytes:
    body = {"schema": 1, "region": "FR", "source": "SIA France eAIP", "license": "SIA Licence Ouverte",
            "licenseUrl": sia.OPEN_LICENSE_URL, "attribution": ATTRIBUTION.format(cycle=cycle["cycle"]),
            "usage": "commercial_allowed_with_attribution", "alterations": ALTERATIONS,
            "effectiveDate": cycle["effectiveDate"], "expiryDate": cycle["expiryDate"], "features": features}
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(raw)
    return buf.getvalue()


def run(nav_dir: Path = NAV_DIR, airspace_dir: Path = AIRSPACE_DIR, getter=http_get, today: date | None = None) -> int:
    catalog = getter(sia.CATALOG_URL)
    if catalog is None:
        print("SIA catalogue not reachable: skipped cleanly, nothing published")
        return 0
    ex = sia.TextExtractor()
    ex.feed(catalog)
    issue = sia.select_current_issue(sia.parse_catalog_issues(ex.text), today)
    lic = getter(sia.OPEN_LICENSE_URL)
    if lic is None:
        print("SIA licence page not reachable: skipped cleanly, nothing published")
        return 0
    lx = sia.TextExtractor()
    lx.feed(lic)
    verification = sia.verify_sia_commercial_reuse(ex.text, lx.text, issue)  # raises if no longer commercial-safe
    base = sia.issue_base_url(issue)
    wanted = ["FR-ENR-4.4-fr-FR.html", "FR-ENR-4.1-fr-FR.html", "FR-ENR-3.2-fr-FR.html"] + [p for p, _ in AIRSPACE_PAGES]
    pages: dict[str, str] = {}
    for page in wanted:
        text = getter(f"{base}/html/eAIP/{page}")
        if text is not None:
            pages[page] = text
    if not pages:
        print("SIA eAIP pages not reachable: skipped cleanly, nothing published")
        return 0
    effective = issue["effectiveDate"]
    meta_path = nav_dir / "meta.json"
    errors: list[str] = []
    files_meta: dict[str, dict] = {}
    tables = build_tables(pages, effective)
    column_sets = {"fixes": ("fixes.csv", nasr.FIX_COLUMNS), "navaids": ("navaids.csv", nasr.NAVAID_COLUMNS),
                   "airway_segments": ("airway_segments.csv", nasr.SEGMENT_COLUMNS)}
    old_meta = {}
    try:
        old_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    for kind, rows in tables.items():
        filename, columns = column_sets[kind]
        try:
            guard(kind, len(rows), previous_count(meta_path, filename))
        except SiaError as exc:
            errors.append(str(exc))
            continue
        data = csv_bytes(columns, rows)
        atomic_write(nav_dir / filename, data)
        files_meta[filename] = {"recordCount": len(rows), "sha256": hashlib.sha256(data).hexdigest(), "sizeBytes": len(data)}
        print(f"{filename}: {len(rows)} records")
    if files_meta:
        merged = {**old_meta.get("files", {}), **files_meta}
        meta = {"source": "SIA France eAIP ENR", "sourceUrl": f"{base}/html/eAIP/", "provider": "SIA / DGAC",
                "license": "SIA Licence Ouverte (commercial reuse with attribution)",
                "licenseStatus": "verified_commercial_open_licence", "licenseVerification": verification,
                "attribution": ATTRIBUTION.format(cycle=issue["cycle"]), "cycle": issue["cycle"],
                "effectiveDate": effective, "expiryDate": issue["expiryDate"],
                "generatedAtUtc": datetime.now(timezone.utc).isoformat(), "files": merged}
        atomic_write(meta_path, (json.dumps(meta, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    features, stats = build_airspace(pages)
    if any(p for p, _ in AIRSPACE_PAGES if p in pages):
        index_path = airspace_dir / "index.json"
        prev = None
        try:
            prev = json.loads(index_path.read_text(encoding="utf-8"))["regions"][0]["featureCount"]
        except (OSError, ValueError, KeyError, IndexError):
            pass
        try:
            guard("airspace", len(features), prev)
            data = pack_bytes(features, issue)
            atomic_write(airspace_dir / "FR.json.gz", data)
            index = {"schema": 1, "format": "FlightTempo SIA France airspace packs", "provider": "SIA / DGAC",
                     "license": "SIA Licence Ouverte", "licenseUrl": sia.OPEN_LICENSE_URL,
                     "attribution": ATTRIBUTION.format(cycle=issue["cycle"]), "commercialUseAllowed": True,
                     "alterations": ALTERATIONS, "effectiveDate": effective, "expiryDate": issue["expiryDate"],
                     "operationalUse": False, "parseStats": stats,
                     "regions": [{"region": "FR", "file": "FR.json.gz", "featureCount": len(features),
                                  "sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                                  "types": dict(Counter(f["type"] for f in features))}]}
            atomic_write(index_path, (json.dumps(index, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
            print(f"airspace: {len(features)} features; stats {stats}")
        except SiaError as exc:
            errors.append(f"{exc}; stats {stats}")
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(run())
