#!/usr/bin/env python3
"""Register the openAIP airspace layer (``openaip_airspace``) in navigation_manifest.json.

Non-commercial (CC BY-NC) data: it is only ``available`` while data/usage_scope.json says 'personal',
and it is never marked commercial. With no index (no key / no export access) the dataset is
registered as unavailable so the app falls back to OFMA/FAA data.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from commercial_rights import personal_scope_active  # noqa: E402

INDEX = ROOT / "airspace" / "openaip" / "index.json"
MANIFEST = ROOT / "navigation_manifest.json"
RAW_MAIN = "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/"


def register(index_path: Path = INDEX, manifest_path: Path = MANIFEST, scope_path: Path | None = None) -> dict | None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    datasets = manifest.setdefault("datasets", [])
    rest = [d for d in datasets if d.get("id") != "openaip_airspace"]
    if not index_path.is_file():
        manifest["datasets"] = rest
        manifest.setdefault("capabilities", {})["openaipAirspace"] = False
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("openAIP index absent: layer not registered (fallback to OFMA/FAA)")
        return None
    raw = index_path.read_bytes()
    index = json.loads(raw)
    regions = index["regions"]
    count = sum(r["featureCount"] for r in regions)
    if not regions or count == 0:
        raise ValueError("openAIP index lists no airspaces")
    personal = personal_scope_active(scope_path) if scope_path else personal_scope_active()
    entry = {
        "id": "openaip_airspace", "path": "airspace/openaip/index.json",
        "available": personal, "recordCount": count, "regionCount": len(regions),
        "sizeBytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "regionBytes": sum(r["sizeBytes"] for r in regions),
        "sourceProvider": "openAIP", "sourceUrl": "https://www.openaip.net",
        "license": "CC BY-NC 4.0 (non-commercial)", "licenseUrl": index["licenseUrl"],
        "licenseStatus": "openaip_noncommercial_personal_use_only",
        "attribution": index["attribution"], "alterations": index["alterations"],
        "usage": "non-commercial", "personalUseOnly": True, "commercialUseAllowed": False,
        "usageScopeNote": "Test-phase layer. Switch off (usage scope) before any paid or public release.",
        "coverage": "Countries not covered by a verified free-commercial source (gap filling); airspace polygons only.",
        "dataCycle": None, "provenanceVerification": "source_snapshot",
        "downloadPurpose": "reference_only", "operationallyAvailable": False,
        "status": "personal_use_only" if personal else "blocked_scope_not_personal",
    }
    if personal:
        entry["downloadUrl"] = RAW_MAIN + "airspace/openaip/index.json"
    rest.append(entry)
    manifest["datasets"] = rest
    manifest.setdefault("capabilities", {})["openaipAirspace"] = personal
    manifest.setdefault("statistics", {})["openaipAirspaces"] = count
    manifest["generatedAtUtc"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Registered openaip_airspace: {count} airspaces in {len(regions)} countries, available={personal}")
    return entry


if __name__ == "__main__":
    register()
