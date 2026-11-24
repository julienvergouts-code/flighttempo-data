#!/usr/bin/env python3
"""Fail closed: only commercially verified and in-cycle datasets are app-downloadable."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

try:
    from .commercial_rights import personal_scope_active, redistribution_block_reason
except ImportError:
    from commercial_rights import personal_scope_active, redistribution_block_reason

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
INCOMPLETE_DATASET_IDS = {"approaches"}
STALE_CAPABILITY_FLAGS = (
    "flightgearNavaids", "legacyGlobalFixes", "legacyGlobalNavaids",
    "legacyGlobalAirways", "legacyGlobalIlsFacilities", "worldCorridorGraph",
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
    "easa_czibs": ("conflictZoneAdvisories",),
    "easa_safety_directives": ("easaSafetyDirectives",),
    "faa_prn_notams": ("faaPrnReferences",),
    "ofma_airspace": ("ofmaAirspace",),
    "terrain_tiles": ("terrainTiles",),
    "terrain_world": ("terrainWorld",),
    "openaip_airspace": ("openaipAirspace",),
    "adsb_observed_routes": ("adsbObservedRoutes",),
    "sids": ("sids",),
    "stars": ("stars",),
    "approaches": ("approaches", "ilsApproaches", "rnavApproaches"),
    "france_sia_sid_star_legs": ("franceSids", "franceStars"),
    "faa_nasr_fixes": ("faaNasrFixes",),
    "faa_nasr_navaids": ("faaNasrNavaids",),
    "faa_nasr_airway_segments": ("faaNasrAirwaySegments",),
}


LEGACY_FALLBACK = ROOT / "data" / "legacy_fallback.json"
RAW_MAIN = "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/"


def legacy_fallback_config(personal: bool, path: Path = LEGACY_FALLBACK) -> dict:
    """Datasets of the 2012 snapshot that stay usable as a labelled fallback (personal scope only)."""
    if not personal:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if data.get("enabled") is True else {}


def apply_legacy_fallback(dataset: dict, config: dict) -> None:
    dataset["personalUseOnly"] = True
    dataset["commercialUseAllowed"] = False
    dataset["legacyFallback"] = True
    dataset["dataCycle"] = config.get("cycleLabel", "2012.08")
    dataset["licenseStatus"] = "gpl3_2012_legacy_personal_use_only_commercial_unverified"
    dataset["status"] = "legacy_fallback_personal_use_only"
    dataset["usageScopeNote"] = ("Legacy 2012 snapshot. Fallback only: prefer current FAA, OFMA or SIA data where they cover "
                                 "the area. Stations, fixes and airways may have been changed or withdrawn since 2012.")
    dataset["preferNewerSources"] = config.get("preferNewerSources", [])
    dataset.pop("downloadBlockReason", None)


def source_cycle_block_reason(dataset: dict, today: date) -> str | None:
    effective_raw = dataset.get("effectiveDate")
    expiry_raw = dataset.get("expiryDate")
    try:
        effective = date.fromisoformat(str(effective_raw)) if effective_raw else None
        expiry = date.fromisoformat(str(expiry_raw)) if expiry_raw else None
    except ValueError:
        return "invalid_source_cycle_date"
    if effective and today < effective:
        return "source_cycle_not_yet_effective"
    if expiry and today > expiry:
        return "source_cycle_expired"
    return None


def enforce(manifest_path: Path = MANIFEST, today: date | None = None) -> list[str]:
    today = today or datetime.now(timezone.utc).date()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    datasets = manifest.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError("navigation_manifest.json has no datasets array")

    personal = personal_scope_active()
    legacy_config = legacy_fallback_config(personal)
    legacy_ids = legacy_config.get("datasets", {})
    blocked = []
    for dataset in datasets:
        dataset_id = dataset.get("id")
        legacy = dataset_id in legacy_ids
        if legacy:
            apply_legacy_fallback(dataset, legacy_config)
        stale = dataset_id in STALE_DATASET_IDS and not legacy
        excluded = dataset_id in BLOCKED_IDS
        incomplete = dataset_id in INCOMPLETE_DATASET_IDS
        rights_reason = redistribution_block_reason(dataset, personal)
        cycle_reason = source_cycle_block_reason(dataset, today)
        if not (stale or excluded or incomplete or rights_reason or cycle_reason):
            if legacy:
                dataset["available"] = True
                dataset["operationallyAvailable"] = False
                dataset["downloadPurpose"] = "reference_only"
                dataset["downloadUrl"] = RAW_MAIN + str(dataset.get("path", ""))
                for flag in legacy_ids[dataset_id]:
                    manifest.setdefault("capabilities", {})[flag] = True
            continue

        dataset["available"] = False
        dataset.pop("downloadUrl", None)
        dataset["operationallyAvailable"] = False
        if stale:
            dataset["status"] = "not_published_stale_legacy_source"
            dataset["downloadBlockReason"] = (
                "The global navigation snapshot is cycle 2012.08 and is stale; "
                "it remains for provenance only and is excluded from app downloads."
            )
        elif cycle_reason:
            dataset["status"] = "not_published_" + cycle_reason
            dataset["downloadBlockReason"] = (
                "The source cycle is not effective yet, has expired, or has invalid dates."
            )
        elif incomplete:
            dataset["status"] = "not_published_incomplete_import"
            dataset["downloadBlockReason"] = (
                "The source is public domain, but this procedure import is incomplete and remains in the repository for review."
            )
        elif excluded or rights_reason:
            dataset["status"] = "not_published_commercial_reuse_unconfirmed_or_restricted"
            dataset["downloadBlockReason"] = (
                "Commercial redistribution permission is not explicitly verified for this source."
            )
        for flag in CAPABILITY_FLAGS.get(dataset_id, ()):
            manifest.setdefault("capabilities", {})[flag] = False
        if stale:
            for flag in STALE_CAPABILITY_FLAGS:
                manifest.setdefault("capabilities", {})[flag] = False
        blocked.append(dataset_id)

    for flag in ("aerosors_vor_ndb", "aerosors_ils", "aeroSorsIlsFacilities",
                 "aerosors_ge_navaids", "aerosors_ge_airports", "firBoundaries",
                 "airspaceFilterAdvisoryOnly"):
        manifest.setdefault("capabilities", {})[flag] = False

    statistics = manifest.setdefault("statistics", {})
    development_stats = manifest.setdefault("developmentOnlyStatistics", {})
    for key in LEGACY_STATISTICS:
        if key in statistics:
            development_stats[key] = statistics.pop(key)

    research_keys = [
        key for key in list(statistics)
        if key.startswith("aerosors_") or key.startswith("aeroSors")
    ]
    for key in research_keys:
        development_stats[key] = statistics.pop(key)

    manifest["developmentOnlySources"] = sorted(
        set(manifest.get("developmentOnlySources", []))
        | {"Aero.Sors derivatives: redistribution not confirmed",
           "OpenAIP FIR geometry and derived filter: CC BY-NC 4.0"}
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print("Blocked app publication for: " + (", ".join(sorted(blocked)) or "none"))
    return blocked


if __name__ == "__main__":
    enforce()
