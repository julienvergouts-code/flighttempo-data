#!/usr/bin/env python3
"""Register the FlightTempo terrain tiles in navigation_manifest.json.

The tiles themselves live on the ``terrain-data`` branch (too many files for
``main``); the small index is mirrored to ``terrain/index.json`` on main so the
manifest can carry its SHA-256. Commercial redistribution stays blocked by the
shared rights gate until data/terrain_rights_confirmation.json says it has been
confirmed by the owner.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import terrain_notices  # noqa: E402
INDEX = ROOT / "terrain" / "index.json"
CONFIRMATION = ROOT / "data" / "terrain_rights_confirmation.json"
MANIFEST_PATH = ROOT / "navigation_manifest.json"
RAW = "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/"


def register(index_path: Path = INDEX, confirmation_path: Path = CONFIRMATION,
             manifest_path: Path = MANIFEST_PATH) -> dict:
    index = json.loads(index_path.read_bytes())
    if terrain_notices.refresh(index):
        index_path.write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    raw = index_path.read_bytes()
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    confirmed = confirmation.get("commercialUseConfirmed") is True and bool(confirmation.get("confirmedBy"))
    tiles = sum(r["tileCount"] for r in index["regions"])
    size = sum(r["sizeBytes"] for r in index["regions"])
    if tiles == 0:
        raise ValueError("terrain index lists no tiles")
    entry = {
        "id": "terrain_tiles", "path": "terrain/index.json",
        "available": confirmed, "recordCount": tiles,
        "sizeBytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "tileBaseUrl": RAW + "terrain-data/", "tileCount": tiles, "tileBytes": size,
        "regions": [{"id": r["id"], "name": r["name"], "bbox": r["bbox"],
                     "tileCount": r["tileCount"], "sizeBytes": r["sizeBytes"]} for r in index["regions"]],
        "cellsPerDegree": index["cellsPerDegree"], "format": index["format"],
        "sourceProvider": "Copernicus DEM GLO-30 (ESA / European Union; DLR, Airbus)",
        "sourceUrl": "https://registry.opendata.aws/copernicus-dem/",
        "coverage": "Regional tile packs: " + ", ".join(r["name"] for r in index["regions"]) +
                    ". Highest-sample-per-cell terrain (max pooled), not worldwide.",
        "license": index["license"],
        "licenseStatus": ("copernicus_free_licence_owner_confirmed" if confirmed
                          else "copernicus_free_licence_commercial_reuse_not_confirmed"),
        "licenseUrl": confirmation["licenceUrl"],
        "attribution": index["attribution"], "disclaimer": index["disclaimer"],
        "modificationNotice": index["modificationNotice"],
        "dataCycle": None, "provenanceVerification": "source_snapshot",
        "downloadPurpose": "reference_only", "operationallyAvailable": False,
        "status": "reference_dataset" if confirmed else "blocked_commercial_reuse_not_confirmed",
    }
    if confirmed:
        entry["commercialUseAllowed"] = True
        entry["downloadUrl"] = RAW + "main/terrain/index.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    datasets = manifest.setdefault("datasets", [])
    matches = [i for i, d in enumerate(datasets) if d.get("id") == "terrain_tiles"]
    if len(matches) > 1:
        raise ValueError("Duplicate manifest dataset id: terrain_tiles")
    if matches:
        datasets[matches[0]] = entry
    else:
        datasets.append(entry)
    manifest.setdefault("capabilities", {})["terrainTiles"] = confirmed
    manifest.setdefault("statistics", {})["terrainTiles"] = tiles
    manifest["generatedAtUtc"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Registered terrain_tiles: {tiles} tiles, available={confirmed}")
    return entry


if __name__ == "__main__":
    register()
