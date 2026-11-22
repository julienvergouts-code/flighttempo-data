#!/usr/bin/env python3
"""Register the separate French SIA designated-point reference package."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "navigation/waypoints/fr_sia_designated_points.csv"
META_PATH = ROOT / "navigation/waypoints/fr_sia_designated_points_meta.json"
MANIFEST_PATH = ROOT / "navigation_manifest.json"
DATASET_ID = "fr_sia_designated_points"
DOWNLOAD_URL = "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/navigation/waypoints/fr_sia_designated_points.csv"


def load_rows(raw: bytes):
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    required = {"ident", "latitude", "longitude", "code_type", "datum", "source_provider"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError(f"French SIA points CSV schema missing columns: {required - set(reader.fieldnames or [])}")
    rows = list(reader)
    if not rows:
        raise ValueError("French SIA designated points CSV has no records")
    for row in rows:
        lat, lon = float(row["latitude"]), float(row["longitude"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            raise ValueError(f"Invalid coordinate for SIA designated point {row.get('ident')}")
        if row["datum"] != "WGS84" or not row["ident"].strip():
            raise ValueError(f"Invalid datum or identifier for SIA designated point {row.get('ident')}")
        if row["source_provider"] != "Service de l'Information Aeronautique (SIA France)":
            raise ValueError("Unexpected source provider in French SIA dataset")
    return rows


def register(csv_path: Path = CSV_PATH, meta_path: Path = META_PATH, manifest_path: Path = MANIFEST_PATH, today: date | None = None):
    raw = csv_path.read_bytes()
    rows = load_rows(raw)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("license") != "Licence Ouverte / Open Licence (Etalab)":
        raise ValueError("French SIA dataset licence metadata is missing or unexpected")
    effective = meta.get("effectiveDate")
    expiry = meta.get("expiryDate")
    if not effective or not expiry:
        raise ValueError("French SIA dataset must carry effective and expiry dates")
    expiry_date = date.fromisoformat(expiry)
    is_current_or_upcoming = expiry_date >= (today or datetime.now(timezone.utc).date())
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset = {
        "id": DATASET_ID,
        "path": "navigation/waypoints/fr_sia_designated_points.csv",
        "available": is_current_or_upcoming,
        "recordCount": len(rows),
        "sizeBytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sourceProvider": meta["sourceProvider"],
        "sourceUrl": meta["sourceUrl"],
        "sourceFileUrl": meta["sourceFileUrl"],
        "coverage": meta["coverage"],
        "sourceTag": f"FR_SIA_AIXM_{effective}",
        "license": meta["license"],
        "licenseStatus": "public_domain_open_licence",
        "dataCycle": effective,
        "effectiveDate": effective,
        "expiryDate": expiry,
        "provenanceVerification": "source_snapshot",
        "downloadPurpose": "reference_only",
        "operationallyAvailable": False,
        "status": meta["status"] if is_current_or_upcoming else "expired_reference_dataset_not_downloadable",
        "attribution": meta["attribution"],
    }
    if is_current_or_upcoming:
        dataset["downloadUrl"] = DOWNLOAD_URL
    datasets = manifest.setdefault("datasets", [])
    found = [index for index, item in enumerate(datasets) if item.get("id") == DATASET_ID]
    if len(found) > 1:
        raise ValueError(f"Duplicate manifest dataset id: {DATASET_ID}")
    if found:
        datasets[found[0]] = dataset
    else:
        datasets.append(dataset)
    statistics = manifest.setdefault("statistics", {})
    development_statistics = manifest.setdefault("developmentOnlyStatistics", {})
    if is_current_or_upcoming:
        statistics["frSiaDesignatedPoints"] = len(rows)
        development_statistics.pop("frSiaDesignatedPoints", None)
    else:
        statistics.pop("frSiaDesignatedPoints", None)
        development_statistics["frSiaDesignatedPoints"] = len(rows)
    manifest.setdefault("capabilities", {})["frSiaDesignatedPoints"] = is_current_or_upcoming
    sources = manifest.setdefault("dataSources", [])
    source = {
        "dataset": DATASET_ID,
        "url": meta["sourceUrl"],
        "provider": meta["sourceProvider"],
        "license": meta["license"],
        "downloadedAt": meta["downloadedAtUtc"],
        "sizeBytes": len(raw),
        "sha256": dataset["sha256"],
        "recordCount": len(rows),
    }
    old = [index for index, item in enumerate(sources) if item.get("dataset") == DATASET_ID]
    if len(old) > 1:
        raise ValueError(f"Duplicate manifest data-source entry: {DATASET_ID}")
    if old:
        sources[old[0]] = source
    else:
        sources.append(source)
    manifest["generatedAtUtc"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state = "registered" if is_current_or_upcoming else "retained as expired, development-only data"
    print(f"{state}: {len(rows)} French SIA designated points; {len(raw)} bytes; effective {effective}, expiry {expiry}")
    return dataset


if __name__ == "__main__":
    register()
