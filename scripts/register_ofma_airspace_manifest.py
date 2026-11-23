#!/usr/bin/env python3
"""Register the OFMA airspace packs (airspace/ofma/index.json) in navigation_manifest.json.

One manifest dataset (``ofma_airspace``) points at the index; the app reads the
index and downloads only the regional packs it needs. Every pack's size and
SHA-256 are re-verified here before the entry is marked available.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "airspace" / "ofma"
MANIFEST_PATH = ROOT / "navigation_manifest.json"
RAW_BASE = "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/"


def register(today: date | None = None, out_dir: Path = OUT_DIR, manifest_path: Path = MANIFEST_PATH) -> dict:
    today = today or datetime.now(timezone.utc).date()
    index_path = out_dir / "index.json"
    raw_index = index_path.read_bytes()
    index = json.loads(raw_index)
    total = 0
    for region in index["regions"]:
        pack = (out_dir / region["file"]).read_bytes()
        if hashlib.sha256(pack).hexdigest() != region["sha256"] or len(pack) != region["sizeBytes"]:
            raise ValueError(f"{region['file']} does not match index.json (sha256 or size)")
        total += region["featureCount"]
    cycles = {r["cycle"] for r in index["regions"]}
    in_cycle = (date.fromisoformat(index["effectiveDate"]) <= today <= date.fromisoformat(index["expiryDate"])
                and cycles == {index["cycle"]})
    relative = "airspace/ofma/index.json"
    entry = {
        "id": "ofma_airspace", "path": relative, "available": in_cycle,
        "recordCount": total, "sizeBytes": len(raw_index), "sha256": hashlib.sha256(raw_index).hexdigest(),
        "packBaseUrl": RAW_BASE + "airspace/ofma/",
        "packCount": len(index["regions"]),
        "packBytes": sum(r["sizeBytes"] for r in index["regions"]),
        "sourceProvider": index["provider"], "sourceUrl": "https://openflightmaps.org/",
        "coverage": "OFMA regions only (not worldwide): " + ", ".join(r["region"] for r in index["regions"]) +
                    ". CTR, TMA, ATZ, RMZ, TMZ, danger/restricted/prohibited and similar areas as polygons.",
        "license": index["license"], "licenseStatus": "commercial_use_permitted_subject_to_OFMA_GUL",
        "licenseUrl": index["licenseUrl"], "attribution": index["attribution"],
        "commercialUseAllowed": True, "licenseConditions": index["licenseConditions"],
        "alterations": index["alterations"],
        "dataCycle": index["cycle"], "effectiveDate": index["effectiveDate"], "expiryDate": index["expiryDate"],
        "provenanceVerification": "official_OFMA_publication_service_and_snapshot",
        "downloadPurpose": "reference_only", "operationallyAvailable": False,
        "status": "reference_dataset" if in_cycle else "not_published_source_cycle_expired",
    }
    if in_cycle:
        entry["downloadUrl"] = RAW_BASE + relative
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    datasets = manifest.setdefault("datasets", [])
    matches = [i for i, d in enumerate(datasets) if d.get("id") == "ofma_airspace"]
    if len(matches) > 1:
        raise ValueError("Duplicate manifest dataset id: ofma_airspace")
    if matches:
        datasets[matches[0]] = entry
    else:
        datasets.append(entry)
    manifest.setdefault("capabilities", {})["ofmaAirspace"] = in_cycle
    manifest.setdefault("statistics", {})["ofmaAirspaceFeatures"] = total
    manifest["generatedAtUtc"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Registered ofma_airspace: {total} airspaces in {len(index['regions'])} packs, cycle {index['cycle']}, available={in_cycle}")
    return entry


if __name__ == "__main__":
    register()
