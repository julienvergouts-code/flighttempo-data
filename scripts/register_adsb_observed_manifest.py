#!/usr/bin/env python3
"""Register the ADS-B observed routes layer (``adsb_observed_routes``) in navigation_manifest.json.

Licence tier: ADSB.lol publishes the archive under ODbL 1.0. ODbL allows commercial use but asks for attribution and
share-alike on a published derived database. That obligation has not been reviewed, so the layer is marked
personal-use-only and never commercial until the owner confirms otherwise. With no index (no archive run yet) the
dataset is simply not registered.
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

INDEX = ROOT / "routes" / "observed" / "index.json"
MANIFEST = ROOT / "navigation_manifest.json"
RAW_MAIN = "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/"


STATUS = ROOT / "data" / "adsb_status.json"


def feeds_app_enabled(path: Path | None = None) -> bool:
    """True only when data/adsb_status.json explicitly says feedsApp is true (default: still a test pipeline)."""
    try:
        return json.loads((path or STATUS).read_text(encoding="utf-8")).get("feedsApp") is True
    except (OSError, ValueError):
        return False


def register(index_path: Path = INDEX, manifest_path: Path = MANIFEST, scope_path: Path | None = None,
             status_path: Path | None = None) -> dict | None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rest = [d for d in manifest.setdefault("datasets", []) if d.get("id") != "adsb_observed_routes"]
    caps = manifest.setdefault("capabilities", {})
    if not index_path.is_file():
        manifest["datasets"] = rest
        caps["adsbObservedRoutes"] = False
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("observed routes index absent: layer not registered")
        return None
    raw = index_path.read_bytes()
    index = json.loads(raw)
    if not index.get("routeCount"):
        raise ValueError("observed routes index lists no routes")
    personal = personal_scope_active(scope_path) if scope_path else personal_scope_active()
    feeds_app = feeds_app_enabled(status_path)
    live = personal and feeds_app
    entry = {
        "id": "adsb_observed_routes", "path": "routes/observed/index.json", "available": live, "testPhase": not feeds_app,
        "recordCount": index["routeCount"], "airportPairs": index["airportPairs"],
        "flightsCounted": index["flightsCounted"],
        "sizeBytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "packFile": "routes/observed/" + index["file"],
        "packSizeBytes": index["sizeBytes"], "packSha256": index["sha256"],
        "sourceProvider": "ADSB.lol", "sourceUrl": index["sourceUrl"],
        "license": "ODbL 1.0 (attribution and share-alike apply)", "licenseUrl": index["licenseUrl"],
        "licenseStatus": "odbl_1_0_share_alike_obligations_unreviewed_personal_use_only",
        "attribution": index["attribution"], "usage": "personal", "personalUseOnly": True,
        "commercialUseAllowed": False,
        "usageScopeNote": "ODbL derived-database obligations are unreviewed. Keep this layer separate; confirm before any public release.",
        "coverage": "Airline flights between airports seen in the ADSB.lol archive days processed so far; grows weekly.",
        "dataCycle": None, "provenanceVerification": "source_snapshot", "downloadPurpose": "reference_only",
        "operationallyAvailable": False, "legacyGraphUsed": False,
        "status": ("personal_use_only" if live else "test_phase_not_published_to_app" if personal else "blocked_scope_not_personal"),
    }
    if live:
        entry["downloadUrl"] = RAW_MAIN + "routes/observed/index.json"
    manifest["datasets"] = rest + [entry]
    caps["adsbObservedRoutes"] = live
    manifest.setdefault("statistics", {})["adsbObservedRoutes"] = index["routeCount"]
    manifest["generatedAtUtc"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Registered adsb_observed_routes: {index['routeCount']} routes, {index['airportPairs']} airport pairs, available={live}")
    return entry


if __name__ == "__main__":
    register()
