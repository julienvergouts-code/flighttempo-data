"""Build the app-facing ``layers`` section of navigation_manifest.json from data/layer_toggles.json.

A layer is one on/off switch for the app that groups manifest datasets. ``userToggle`` is true only when
at least one dataset of the layer is available, so the app can never switch on something the data side
has blocked (rights gate, owner decision, test phase, expired cycle).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "layer_toggles.json"


def tier_of(datasets: list[dict]) -> str:
    live = [d for d in datasets if d.get("available")]
    pool = live or datasets
    if any(d.get("legacyFallback") for d in pool):
        return "legacy_fallback"
    if any(d.get("personalUseOnly") for d in pool):
        return "personal_use_only"
    return "commercial_or_public"


def reason_unavailable(dataset: dict | None) -> str:
    if dataset is None:
        return "not_in_manifest"
    return str(dataset.get("downloadBlockReason") or dataset.get("status") or "not_available")


def build_layers(manifest: dict, config: dict) -> dict:
    by_id = {d.get("id"): d for d in manifest.get("datasets", [])}
    layers = []
    for spec in config.get("layers", []):
        members = [by_id[i] for i in spec["datasets"] if i in by_id]
        live = [d for d in members if d.get("available")]
        missing = [i for i in spec["datasets"] if i not in by_id or not by_id[i].get("available")]
        toggle = bool(live)
        tier = tier_of(members) if members else "commercial_or_public"
        layers.append({
            "id": spec["id"], "label": spec["label"], "group": spec["group"],
            "datasets": spec["datasets"],
            "availableDatasets": [d["id"] for d in live],
            "unavailableDatasets": [{"id": i, "reason": reason_unavailable(by_id.get(i))} for i in missing],
            "userToggle": toggle,
            "defaultOn": bool(spec.get("defaultOn")) and toggle,
            "tier": tier,
            "recordCount": sum(int(d.get("recordCount") or 0) for d in live),
            "fallbackFor": spec.get("fallbackFor", []),
            "note": spec.get("note", ""),
        })
    personal_layers = [l["id"] for l in layers if l["userToggle"] and l["tier"] in ("personal_use_only", "legacy_fallback")]
    return {
        "layers": layers,
        "layerPriority": config.get("priority", {}),
        "masterSwitches": {
            "personalUseData": {
                "layers": personal_layers,
                "note": "Data that may only be used personally (non-commercial, legacy or unverified licences). A public or paid build must hide these layers and keep the switch off.",
            }
        },
    }


def apply(manifest: dict, config_path: Path = CONFIG) -> bool:
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    manifest.update(build_layers(manifest, config))
    return True
