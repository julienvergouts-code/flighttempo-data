#!/usr/bin/env python3
"""Register the SIA France ENR datasets in navigation_manifest.json.

Datasets (verified-commercial tier, SIA Licence Ouverte; each only ``available`` inside its AIRAC window):
  sia_france_fixes, sia_france_navaids, sia_france_airway_segments  (navigation/sia_france/*.csv)
  sia_france_airspace                                               (airspace/sia/index.json + FR.json.gz)
Missing files unregister the dataset (the app then falls back to other sources).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import fetch_faa_nasr_ifr as nasr  # noqa: E402

NAV_DIR = ROOT / "navigation" / "sia_france"
AIRSPACE_INDEX = ROOT / "airspace" / "sia" / "index.json"
MANIFEST = ROOT / "navigation_manifest.json"
RAW_MAIN = "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/"
COVERAGE = "France (SIA eAIP ENR)"
NAV_DATASETS = (
    ("sia_france_fixes", "fixes.csv", nasr.FIX_COLUMNS, "siaFranceFixes", "France SIA significant points (ENR 4.4)"),
    ("sia_france_navaids", "navaids.csv", nasr.NAVAID_COLUMNS, "siaFranceNavaids", "France SIA radio navigation aids (ENR 4.1)"),
    ("sia_france_airway_segments", "airway_segments.csv", nasr.SEGMENT_COLUMNS, "siaFranceAirwaySegments",
     "France SIA ATS route segments (ENR 3.2)"),
)


def _put(datasets: list, entry: dict) -> None:
    for i, d in enumerate(datasets):
        if d.get("id") == entry["id"]:
            datasets[i] = entry
            return
    datasets.append(entry)


def _drop(manifest: dict, dataset_id: str, cap: str) -> None:
    manifest["datasets"] = [d for d in manifest.get("datasets", []) if d.get("id") != dataset_id]
    manifest.setdefault("capabilities", {})[cap] = False


def _common(meta: dict, in_cycle: bool, relative: str, raw: bytes) -> dict:
    entry = {
        "path": relative, "available": in_cycle, "sizeBytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "sourceProvider": "SIA / DGAC (France)", "sourceUrl": meta["sourceUrl"], "coverage": COVERAGE,
        "sourceTag": f"SIA_EAIP_{meta['effectiveDate']}",
        "license": meta["license"], "licenseStatus": meta["licenseStatus"], "attribution": meta["attribution"],
        "dataCycle": meta["effectiveDate"], "effectiveDate": meta["effectiveDate"], "expiryDate": meta["expiryDate"],
        "provenanceVerification": "source_snapshot", "downloadPurpose": "reference_only",
        "operationallyAvailable": False,
        "status": "present_reference_dataset" if in_cycle else "not_published_source_cycle_expired",
    }
    if in_cycle:
        entry["downloadUrl"] = RAW_MAIN + relative
    return entry


def register(today: date | None = None, nav_dir: Path = NAV_DIR, airspace_index: Path = AIRSPACE_INDEX,
             manifest_path: Path = MANIFEST) -> list[dict]:
    today = today or datetime.now(timezone.utc).date()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    datasets = manifest.setdefault("datasets", [])
    stats = manifest.setdefault("statistics", {})
    caps = manifest.setdefault("capabilities", {})
    registered: list[dict] = []
    meta_path = nav_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else None

    for dataset_id, filename, columns, key, coverage in NAV_DATASETS:
        path = nav_dir / filename
        if meta is None or not path.is_file() or filename not in meta.get("files", {}):
            _drop(manifest, dataset_id, key)
            continue
        raw = path.read_bytes()
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        if reader.fieldnames != columns:
            raise ValueError(f"{filename}: unexpected header {reader.fieldnames}")
        rows = list(reader)
        declared = meta["files"][filename]
        if declared["sha256"] != hashlib.sha256(raw).hexdigest() or declared["recordCount"] != len(rows) or not rows:
            raise ValueError(f"{filename}: does not match meta.json")
        for r in rows:
            for lat, lon in (("latitude", "longitude"), ("from_latitude", "from_longitude"), ("to_latitude", "to_longitude")):
                if lat in r and not (-90 <= float(r[lat]) <= 90 and -180 <= float(r[lon]) <= 180):
                    raise ValueError(f"{filename}: invalid coordinate {r}")
        in_cycle = date.fromisoformat(meta["effectiveDate"]) <= today <= date.fromisoformat(meta["expiryDate"])
        entry = {"id": dataset_id, "recordCount": len(rows), **_common(meta, in_cycle, f"navigation/sia_france/{filename}", raw)}
        entry["coverage"] = coverage
        _put(datasets, entry)
        stats[key] = len(rows)
        caps[key] = in_cycle
        registered.append(entry)

    if airspace_index.is_file():
        raw = airspace_index.read_bytes()
        index = json.loads(raw)
        count = sum(r["featureCount"] for r in index["regions"])
        if count == 0:
            raise ValueError("SIA airspace index lists no airspaces")
        for region in index["regions"]:
            pack = (airspace_index.parent / region["file"]).read_bytes()
            if hashlib.sha256(pack).hexdigest() != region["sha256"]:
                raise ValueError(f"{region['file']}: does not match index.json")
        in_cycle = date.fromisoformat(index["effectiveDate"]) <= today <= date.fromisoformat(index["expiryDate"])
        entry = {"id": "sia_france_airspace", "recordCount": count, "regionCount": len(index["regions"]),
                 "regionBytes": sum(r["sizeBytes"] for r in index["regions"]),
                 **_common({"sourceUrl": "https://www.sia.aviation-civile.gouv.fr/produits-numeriques-en-libre-disposition/eaip.html",
                            "effectiveDate": index["effectiveDate"], "expiryDate": index["expiryDate"],
                            "license": index["license"], "licenseStatus": "verified_commercial_open_licence",
                            "attribution": index["attribution"]}, in_cycle, "airspace/sia/index.json", raw)}
        entry["coverage"] = "France CTA/TMA/CTR/TMZ/RMZ and P/R/D zones (SIA eAIP ENR 2.1, 2.2, 5.1); polygons only"
        entry["alterations"] = index["alterations"]
        _put(datasets, entry)
        stats["siaFranceAirspaces"] = count
        caps["siaFranceAirspace"] = in_cycle
        registered.append(entry)
    else:
        _drop(manifest, "sia_france_airspace", "siaFranceAirspace")

    manifest["generatedAtUtc"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for e in registered:
        print(f"Registered {e['id']}: {e['recordCount']} records, available={e['available']}")
    if not registered:
        print("SIA France data absent: nothing registered")
    return registered


if __name__ == "__main__":
    register()
