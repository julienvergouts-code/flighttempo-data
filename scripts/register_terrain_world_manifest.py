#!/usr/bin/env python3
"""Merge block-zip entries into terrain/world-index.json and register ``terrain_world``.

Block zips are hosted as GitHub Release assets (no repo-size cost); the small index
lives on main so the manifest can carry its SHA-256. Commercial redistribution stays
blocked by the shared rights gate until data/terrain_rights_confirmation.json is confirmed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import terrain_notices  # noqa: E402
from commercial_rights import personal_scope_active  # noqa: E402
WORLD_INDEX = ROOT / "terrain" / "world-index.json"
TILE_INDEX = ROOT / "terrain" / "index.json"  # source of licence / attribution wording
CONFIRMATION = ROOT / "data" / "terrain_rights_confirmation.json"
MANIFEST_PATH = ROOT / "navigation_manifest.json"
RAW_MAIN = "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/"


def merge_index(entries: list[dict], world_index: Path = WORLD_INDEX, tile_index: Path = TILE_INDEX) -> dict:
    if not entries:
        raise ValueError("no block entries to merge")
    meta = json.loads(tile_index.read_text(encoding="utf-8"))
    blocks: dict[str, dict] = {}
    if world_index.is_file():
        for b in json.loads(world_index.read_text(encoding="utf-8"))["blocks"]:
            blocks[b["id"]] = b
    for b in entries:
        blocks[b["id"]] = b
    index = {
        "schema": 1, "format": meta["format"], "tilePath": "tile N47E011 is inside block N40E010 (10 degree blocks, zip of .fttr files)",
        "cellsPerDegree": meta["cellsPerDegree"], "cellSizeArcSeconds": meta["cellSizeArcSeconds"],
        "heightUnit": meta["heightUnit"], "rowOrder": meta["rowOrder"], "blockDegrees": 10,
        "elevationMeaning": meta["elevationMeaning"], "source": meta["source"], "license": meta["license"],
        "attribution": meta["attribution"], "disclaimer": meta["disclaimer"],
        "modificationNotice": meta["modificationNotice"], "operationalUse": False, "notice": meta["notice"],
        "accuracyNotes": [
            "Sharp peaks can read well below their real height (Matterhorn about -150 m, Mont Orohena about -400 m).",
            "A missing tile is treated as open sea (0 m). Copernicus withholds GLO-30 tiles for a few countries, so land there can be missing: do not read 'no tile' as 'no terrain' over land.",
        ],
        "blocks": [blocks[k] for k in sorted(blocks)],
    }
    world_index.parent.mkdir(parents=True, exist_ok=True)
    world_index.write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return index


def register(world_index: Path = WORLD_INDEX, confirmation_path: Path = CONFIRMATION,
             manifest_path: Path = MANIFEST_PATH, scope_path: Path | None = None) -> dict:
    index = json.loads(world_index.read_bytes())
    if terrain_notices.refresh(index):
        world_index.write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    raw = world_index.read_bytes()
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    confirmed = confirmation.get("commercialUseConfirmed") is True and bool(confirmation.get("confirmedBy"))
    personal = (personal_scope_active(scope_path) if scope_path else personal_scope_active()) and not confirmed
    blocks = index["blocks"]
    tiles = sum(b["tileCount"] for b in blocks)
    if not blocks or tiles == 0:
        raise ValueError("world terrain index lists no tiles")
    entry = {
        "id": "terrain_world", "path": "terrain/world-index.json",
        "available": confirmed or personal, "recordCount": tiles,
        "sizeBytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "blockCount": len(blocks), "tileCount": tiles, "blockBytes": sum(b["sizeBytes"] for b in blocks),
        "blockDegrees": index["blockDegrees"], "cellsPerDegree": index["cellsPerDegree"], "format": index["format"],
        "sourceProvider": "Copernicus DEM GLO-30 (ESA / European Union; DLR, Airbus)",
        "sourceUrl": "https://registry.opendata.aws/copernicus-dem/",
        "coverage": "Land between 60S and 84N in 10 degree block zips hosted as GitHub Release assets; "
                    "highest-sample-per-cell terrain (max pooled).",
        "license": index["license"],
        "licenseStatus": ("copernicus_free_licence_owner_confirmed" if confirmed
                          else "copernicus_free_licence_personal_use_only_commercial_unverified" if personal
                          else "copernicus_free_licence_commercial_reuse_not_confirmed"),
        "licenseUrl": confirmation["licenceUrl"],
        "attribution": index["attribution"], "disclaimer": index["disclaimer"],
        "modificationNotice": index["modificationNotice"],
        "dataCycle": None, "provenanceVerification": "source_snapshot",
        "downloadPurpose": "reference_only", "operationallyAvailable": False,
        "status": ("reference_dataset" if confirmed else "personal_use_only" if personal
                   else "blocked_commercial_reuse_not_confirmed"),
    }
    if personal:
        entry["personalUseOnly"] = True
        entry["commercialUseAllowed"] = False
        entry["usageScopeNote"] = "Personal use only until the Copernicus commercial reading is confirmed."
    if confirmed or personal:
        if confirmed:
            entry["commercialUseAllowed"] = True
        entry["downloadUrl"] = RAW_MAIN + "terrain/world-index.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    datasets = manifest.setdefault("datasets", [])
    matches = [i for i, d in enumerate(datasets) if d.get("id") == "terrain_world"]
    if len(matches) > 1:
        raise ValueError("Duplicate manifest dataset id: terrain_world")
    if matches:
        datasets[matches[0]] = entry
    else:
        datasets.append(entry)
    manifest.setdefault("capabilities", {})["terrainWorld"] = confirmed or personal
    manifest.setdefault("statistics", {})["terrainWorldTiles"] = tiles
    manifest["generatedAtUtc"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Registered terrain_world: {tiles} tiles in {len(blocks)} blocks, available={entry['available']}")
    return entry


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--entries", type=Path, help="block entries JSON from pack_terrain_blocks.py to merge first")
    a = ap.parse_args()
    if a.entries:
        merge_index(json.loads(a.entries.read_text(encoding="utf-8")))
    register()
