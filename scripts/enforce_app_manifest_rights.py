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
    # This app-facing table carries legacy IATA and time-zone fields whose
    # redistribution provenance is still unresolved. The separate normalized
    # OurAirports tables remain available under the provider's CC0 terms.
    "airport_reference",
    "aerosors_vor_ndb",
    "aerosors_ils",
    "aerosors_ge_navaids",
    "aerosors_ge_airports",
    "openaip_fir_boundaries",
    "airspace_filter",
}

BLOCK_REASONS = {
    "airport_reference": (
        "Legacy IATA and time-zone fields have mixed upstream provenance; "
        "keep this table in the repository until redistribution rights are "
        "confirmed. Use the separate OurAirports CC0 dataset for app downloads."
    ),
}

CAPABILITY_FLAGS = {
    "aerosors_vor_ndb": ("aerosors_vor_ndb",),
    "aerosors_ils": ("aerosors_ils", "aeroSorsIlsFacilities"),
    "aerosors_ge_navaids": ("aerosors_ge_navaids",),
    "aerosors_ge_airports": ("aerosors_ge_airports",),
    "openaip_fir_boundaries": ("firBoundaries",),
    "airspace_filter": ("airspaceFilterAdvisoryOnly",),
}


def enforce() -> list[str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    datasets = manifest.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError("navigation_manifest.json has no datasets array")

    blocked = []
    for dataset in datasets:
        dataset_id = dataset.get("id")
        if dataset_id not in BLOCKED_IDS:
            continue
        dataset["available"] = False
        dataset.pop("downloadUrl", None)
        dataset["operationallyAvailable"] = False
        dataset["status"] = "not_published_redistribution_rights_unconfirmed_or_non_commercial_only"
        dataset["downloadBlockReason"] = BLOCK_REASONS.get(dataset_id, (
            "Retained for research/provenance only. Do not publish through the "
            "app download manifest until redistribution rights suitable for "
            "the intended product have been confirmed in writing."
        ))
        for flag in CAPABILITY_FLAGS.get(dataset_id, ()):
            manifest.setdefault("capabilities", {})[flag] = False
        blocked.append(dataset_id)

    # These flags describe app-download availability, not the presence of
    # research files in the repository. Set them false even if an earlier
    # workflow removed the dataset entries before this guard runs.
    for flags in CAPABILITY_FLAGS.values():
        for flag in flags:
            manifest.setdefault("capabilities", {})[flag] = False

    # Keep research counts out of the app-facing capability/statistics surface.
    statistics = manifest.setdefault("statistics", {})
    research_keys = [
        key for key in list(statistics)
        if key.startswith("aerosors_")
        or key.startswith("aeroSors")
        or key.startswith("airportReference")
    ]
    if research_keys:
        research = manifest.setdefault("developmentOnlyStatistics", {})
        for key in research_keys:
            research[key] = statistics.pop(key)

    if "airport_reference" in blocked:
        # The app-facing airport count should describe the clean OurAirports
        # table that remains downloadable, not the excluded mixed-source copy.
        if statistics.get("ourairportsAirports") is not None:
            statistics["airports"] = statistics["ourairportsAirports"]
        enrichment = manifest.get("airportReferenceEnrichment")
        if isinstance(enrichment, dict):
            enrichment["appDownloadable"] = False
            enrichment["downloadBlockReason"] = BLOCK_REASONS["airport_reference"]

    manifest["developmentOnlySources"] = sorted(
        set(manifest.get("developmentOnlySources", []))
        | {"Aero.Sors derivative exports: redistribution not confirmed",
           "OpenAIP FIR geometry and derived airspace filter: CC BY-NC 4.0",
           "Legacy airport reference IATA/time-zone fields: source redistribution rights under review"}
    )
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print("Blocked app publication for: " + (", ".join(sorted(blocked)) or "none"))
    return blocked


if __name__ == "__main__":
    enforce()
