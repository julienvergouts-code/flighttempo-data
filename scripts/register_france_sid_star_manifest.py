#!/usr/bin/env python3
"""Re-register the published France SID/STAR dataset (procedures/europe/france) in navigation_manifest.json.

The daily navigation rebuild does not carry this dataset over, so it is registered again from the files on main.
Does nothing when the files are missing. The window check in enforce_app_manifest_rights.py still applies.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_sia_eaip_procedure_data as sia  # noqa: E402

CSV = ROOT / "procedures" / "europe" / "france" / "sid_star_legs.csv"
META = ROOT / "procedures" / "europe" / "france" / "meta.json"


def main() -> int:
    if not (CSV.is_file() and META.is_file()):
        print("France SID/STAR files absent: nothing to register")
        return 0
    meta = json.loads(META.read_text(encoding="utf-8"))
    sia.register_manifest(CSV, meta)
    print("Registered france_sia_sid_star_legs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
