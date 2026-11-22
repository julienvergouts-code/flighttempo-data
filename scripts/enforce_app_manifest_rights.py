#!/usr/bin/env python3
"""Keep the app download manifest limited to sources with confirmed redistribution rights.

Research datasets may remain in the repository with their provenance, but they
must not be advertised as app-downloadable while redistribution rights are
unclear or non-commercial-only.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "navigation_manifest.json"

BLOCKED_IDS = {
    "aerosors_vor_ndb",
    "aerosors_ils",
    "aerosors_ge_navaids",
    "aerosors_ge_airports",
    "openaip_fir_boundaries",
    "airspace_filter",
    "airport_reference",
}

STALE_DATASET_IDS = {
    "flightgear_fixes",
    "flightgear_navaids",
    "flightgear_airway_segments",
    "world_corridor_graph",
}
STALE_CAPABILITY_FLAGS = (
    "legacyGlobalFixes", "legacyGlobalNavaids", "legacyGlobalAirways",
    "legacyGlobalIlsFacilities", "worldCorridorGraph",
    "independentWaypoints", "publishedAirways",
)
LEGACY_STATISTICS = {
    "ifrWaypoints", "flightgearNavaids", "airwaySegments",
    "lowAirwaySegments", "highAirwaySegments",
    "flightgearIlsFacilities", "flightgearLocalizerFacilities",
    "flightgearGlideslopeFacilities", "flightgearMarkerBeacons",
    "flightgearDmeFacilities",
}

CAPABILITY_FLAGS = {
    "aerosors_vor_ndb": ("aerosors_vor_ndb",),
    "aerosors_ils": ("aerosors_ils", "aeroSorsIlsFacilities"),
    "aerosors_ge_navaids": ("aerosors_ge_navaids",),
    "aerosors_ge_airports": ("aerosors_ge_airports",),
    "openaip_fir_boundaries": ("firBoundaries",),
    "airspace_filter": ("airspaceFilterAdvisoryOnly",),
}


def rights_block_reason(dataset: dict) -> str | None:
    text = " ".join(str(dataset.get(key, "")) for key in ("license", "licenseStatus", "status")).lower()
    markers = (
        "cc by-nc", "cc_by_nc", "non_commercial_only", "non-commercial-only",
        "personal_noncommercial_only", "personal_non-commercial-only",
        "not_confirmed", "not-confirmed", "redistribution_not_confirmed",
        "public_redistribution_not_confirmed", "permission_required",
        "permission_review_required", "mixed_source_review_required",
        "declared_redistributable_check_required", "scope_to_confirm",
        "scope_pending", "license_scope_unconfirmed", "rights_unconfirmed",
    )
    return next((marker for marker in markers if marker in text), None)


def enforce(manifest_path: Path = MANIFEST) -> list[str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    datasets = manifest.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError("navigation_manifest.json has no datasets array")

    blocked = []
    for dataset in datasets:
        dataset_id = dataset.get("id")
        reason = rights_block_reason(dataset)
        if dataset_id not in BLOCKED_IDS and dataset_id not in STALE_DATASET_IDS and not reason:
            continue
        stale = dataset_id in STALE_DATASET_IDS
        dataset["available"] = False
        dataset.pop("downloadUrl", None)
        dataset["operationallyAvailable"] = False
        dataset["status"] = (
            "not_published_stale_legacy_source"
            if stale else "not_published_commercial_reuse_unconfirmed_or_restricted"
        )
        dataset["downloadBlockReason"] = (
            "This global navigation snapshot is cycle 2012.08 and is not current. "
            "It remains in repository history for provenance but is excluded from app downloads."
            if stale else
            "Retained for research/provenance only until commercial redistribution rights are confirmed."
        )
        for flag in CAPABILITY_FLAGS.get(dataset_id, ()):
            manifest.setdefault("capabilities", {})[flag] = False
        if stale:
            for flag in STALE_CAPABILITY_FLAGS:
                manifest.setdefault("capabilities", {})[flag] = False
        blocked.append(dataset_id)

    # These flags describe app-download availability, not the presence of
    # research files in the repository. Set them false even if an earlier
    # workflow removed the dataset entries before this guard runs.
    for flags in CAPABILITY_FLAGS.values():
        for flag in flags:
            manifest.setdefault("capabilities", {})[flag] = False

    # Stale legacy IFR counts describe files kept for provenance, not current data.
    statistics = manifest.setdefault("statistics", {})
    development_stats = manifest.setdefault("developmentOnlyStatistics", {})
    for key in LEGACY_STATISTICS:
        if key in statistics:
            development_stats[key] = statistics.pop(key)

    # Keep research counts out of the app-facing capability/statistics surface.
    research_keys = [
        key for key in list(statistics)
        if key.startswith("aerosors_") or key.startswith("aeroSors")
    ]
    if research_keys:
        research = manifest.setdefault("developmentOnlyStatistics", {})
        for key in research_keys:
            research[key] = statistics.pop(key)

    manifest["developmentOnlySources"] = sorted(
        set(manifest.get("developmentOnlySources", []))
        | {"Aero.Sors derivative exports: redistribution not confirmed",
           "OpenAIP FIR geometry and derived airspace filter: CC BY-NC 4.0"}
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print("Blocked app publication for: " + (", ".join(sorted(blocked)) or "none"))
    return blocked


if __name__ == "__main__":
    enforce()
