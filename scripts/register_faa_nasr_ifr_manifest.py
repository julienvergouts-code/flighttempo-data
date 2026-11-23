#!/usr/bin/env python3
"""Register the FAA NASR IFR reference CSVs in navigation_manifest.json.

Reads navigation/faa_nasr/{fixes,navaids,airway_segments}.csv plus meta.json and
creates or replaces three manifest datasets. A dataset is marked downloadable
only while today's date lies inside the cycle's effective/expiry window; the
shared fail-closed gate (enforce_app_manifest_rights.py) re-checks this daily.
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

DATA_DIR = ROOT / "navigation" / "faa_nasr"
MANIFEST_PATH = ROOT / "navigation_manifest.json"
RAW_BASE = "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/"

DATASETS = (
    ("faa_nasr_fixes", "fixes.csv", nasr.FIX_COLUMNS, "faaNasrFixes", "faaNasrFixes",
     "United States NASR named fixes and waypoints (VFR reporting points excluded)"),
    ("faa_nasr_navaids", "navaids.csv", nasr.NAVAID_COLUMNS, "faaNasrNavaids", "faaNasrNavaids",
     "United States NASR navaids (VOR, VORTAC, VOR/DME, NDB, TACAN, DME)"),
    ("faa_nasr_airway_segments", "airway_segments.csv", nasr.SEGMENT_COLUMNS,
     "faaNasrAirwaySegments", "faaNasrAirwaySegments",
     "United States NASR airway segments with endpoint coordinates"),
)


def parse_csv(raw: bytes, columns: list[str], label: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    if reader.fieldnames != columns:
        raise ValueError(f"{label}: header {reader.fieldnames} does not match expected {columns}")
    rows = list(reader)
    if not rows:
        raise ValueError(f"{label}: no data records")
    return rows


def check_coordinates(rows: list[dict[str, str]], pairs: list[tuple[str, str]], label: str) -> None:
    for row in rows:
        for lat_key, lon_key in pairs:
            lat, lon = float(row[lat_key]), float(row[lon_key])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
                raise ValueError(f"{label}: invalid coordinate in row {row}")


def register(today: date | None = None, data_dir: Path = DATA_DIR, manifest_path: Path = MANIFEST_PATH) -> list[dict]:
    today = today or datetime.now(timezone.utc).date()
    meta = json.loads((data_dir / "meta.json").read_text(encoding="utf-8"))
    effective, expiry = meta["effectiveDate"], meta["expiryDate"]
    in_cycle = date.fromisoformat(effective) <= today <= date.fromisoformat(expiry)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    datasets = manifest.setdefault("datasets", [])
    manifest.setdefault("dataSources", [])
    stats = manifest.setdefault("statistics", {})
    caps = manifest.setdefault("capabilities", {})
    registered = []

    for dataset_id, filename, columns, stat_key, cap_key, coverage in DATASETS:
        raw = (data_dir / filename).read_bytes()
        rows = parse_csv(raw, columns, filename)
        if filename == "airway_segments.csv":
            check_coordinates(rows, [("from_latitude", "from_longitude"), ("to_latitude", "to_longitude")], filename)
        else:
            check_coordinates(rows, [("latitude", "longitude")], filename)
        declared = meta["files"][filename]
        digest = hashlib.sha256(raw).hexdigest()
        if declared["sha256"] != digest or declared["recordCount"] != len(rows):
            raise ValueError(f"{filename}: file does not match meta.json (sha256 or record count)")
        relative = f"navigation/faa_nasr/{filename}"
        entry = {
            "id": dataset_id, "path": relative, "available": in_cycle,
            "recordCount": len(rows), "sizeBytes": len(raw), "sha256": digest,
            "sourceProvider": "FAA Aeronautical Information Services / NASR",
            "sourceUrl": meta["sourceUrl"], "coverage": coverage,
            "sourceTag": f"FAA_NASR_{effective}",
            "license": meta["license"], "licenseStatus": meta["licenseStatus"],
            "attribution": meta["attribution"],
            "dataCycle": effective, "effectiveDate": effective, "expiryDate": expiry,
            "provenanceVerification": "source_snapshot",
            "downloadPurpose": "reference_only", "operationallyAvailable": False,
            "status": "present_reference_dataset" if in_cycle else "not_published_source_cycle_expired",
        }
        if in_cycle:
            entry["downloadUrl"] = RAW_BASE + relative
        matches = [i for i, d in enumerate(datasets) if d.get("id") == dataset_id]
        if len(matches) > 1:
            raise ValueError(f"Duplicate manifest dataset id: {dataset_id}")
        if matches:
            datasets[matches[0]] = entry
        else:
            datasets.append(entry)
        stats[stat_key] = len(rows)
        caps[cap_key] = in_cycle

        source = {"dataset": dataset_id, "url": meta["sourceUrl"], "provider": "FAA Aeronautical Information Services",
                  "license": meta["license"], "downloadedAt": meta.get("generatedAtUtc", ""),
                  "sizeBytes": len(raw), "sha256": digest, "recordCount": len(rows)}
        old = [i for i, d in enumerate(manifest["dataSources"]) if d.get("dataset") == dataset_id]
        if old:
            manifest["dataSources"][old[0]] = source
        else:
            manifest["dataSources"].append(source)
        registered.append(entry)

    manifest["generatedAtUtc"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for entry in registered:
        print(f"Registered {entry['id']}: {entry['recordCount']} records, cycle {effective}, available={entry['available']}")
    return registered


if __name__ == "__main__":
    register()
