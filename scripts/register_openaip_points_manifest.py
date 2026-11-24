#!/usr/bin/env python3
"""Register the openAIP navaid and VFR reporting point test layers (non-commercial, personal-use scope only)."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from commercial_rights import personal_scope_active  # noqa: E402

MANIFEST = ROOT / "navigation_manifest.json"
RAW_MAIN = "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/"
SPECS = [
    {"id": "openaip_navaids", "path": "navigation/openaip/navaids.csv", "flag": "openaipNavaids",
     "coverage": "VOR, DME, NDB, TACAN outside the US and France (gap filling)."},
    {"id": "openaip_reporting_points", "path": "data/openaip_reporting_points.csv", "flag": "openaipReportingPoints",
     "coverage": "VFR reporting points (entry/exit, compulsory flag) in countries OFMA and the FAA do not cover."},
]


def register(root: Path = ROOT, manifest_path: Path = MANIFEST, scope_path: Path | None = None) -> list[dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    personal = personal_scope_active(scope_path) if scope_path else personal_scope_active()
    ids = {s["id"] for s in SPECS}
    datasets = [d for d in manifest.get("datasets", []) if d.get("id") not in ids]
    caps = manifest.setdefault("capabilities", {})
    out = []
    for spec in SPECS:
        f = root / spec["path"]
        if not f.is_file():
            caps[spec["flag"]] = False
            continue
        raw = f.read_bytes()
        with f.open(encoding="utf-8", newline="") as h:
            count = sum(1 for _ in csv.DictReader(h))
        if count == 0:
            caps[spec["flag"]] = False
            continue
        entry = {
            "id": spec["id"], "path": spec["path"], "available": personal, "recordCount": count,
            "sizeBytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "sourceProvider": "openAIP", "sourceUrl": "https://www.openaip.net",
            "license": "CC BY-NC 4.0 (non-commercial)", "licenseUrl": "https://creativecommons.org/licenses/by-nc/4.0/",
            "licenseStatus": "openaip_noncommercial_personal_use_only",
            "attribution": "Contains data from openAIP (www.openaip.net), licensed CC BY-NC 4.0.",
            "alterations": ["Reduced to identifier, type, name, position, elevation, frequency and country."],
            "usage": "non-commercial", "personalUseOnly": True, "commercialUseAllowed": False,
            "usageScopeNote": "Test-phase layer. Switch off (usage scope) before any paid or public release.",
            "coverage": spec["coverage"], "dataCycle": None, "provenanceVerification": "source_snapshot",
            "downloadPurpose": "reference_only", "operationallyAvailable": False,
            "status": "personal_use_only" if personal else "blocked_scope_not_personal",
        }
        if personal:
            entry["downloadUrl"] = RAW_MAIN + spec["path"]
        datasets.append(entry)
        caps[spec["flag"]] = personal
        out.append(entry)
    manifest["datasets"] = datasets
    manifest["generatedAtUtc"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    for e in register():
        print(f"Registered {e['id']}: {e['recordCount']} records, available={e['available']}")
