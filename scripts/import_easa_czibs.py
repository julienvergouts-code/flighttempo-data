#!/usr/bin/env python3
"""Normalize the official EASA CZIB JSON export for FlightTempo development."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "airspace/advisories/easa_czibs_source.json"
OUTPUT = ROOT / "airspace/advisories/easa_czibs.json"
FILTER = ROOT / "airspace/airspace_filter.json"
SOURCE_URL = "https://www.easa.europa.eu/en/domains/air-operations/czibs/export-json?_format=json&page="


def clean_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", value).strip()


def parse_date(value: str):
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def normalize():
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    records = raw.get("conflict_zones")
    if not isinstance(records, list):
        raise ValueError("EASA export missing conflict_zones array")

    today = datetime.now(timezone.utc).date()
    all_rows = []
    for item in records:
        status = (item.get("status") or "Unknown").strip()
        valid_until_raw = item.get("valid_until_date") or ""
        valid_until = parse_date(valid_until_raw)
        effective_status = status.lower()
        if effective_status == "active" and valid_until and valid_until < today:
            effective_status = "expired_pending_source_update"

        name = clean_html(item.get("name", ""))
        # Only encode an FIR association when the official advisory title itself
        # names the FIR. Do not infer FIRs from country names or draw boundaries.
        fir_codes = ["OYSC"] if "sana" in name.lower() and "flight information region" in name.lower() else []
        coords = item.get("coordinates") or ""
        all_rows.append({
            "sourceId": str(item.get("Nid", "")),
            "name": name,
            "status": status,
            "effectiveStatus": effective_status,
            "country": clean_html(item.get("country", "")),
            "issuedDate": item.get("issued_date", "")[:10] or None,
            "updated": clean_html(item.get("updated", "")),
            "validUntil": valid_until.isoformat() if valid_until else None,
            "sourceValidUntilText": valid_until_raw or None,
            "coordinatesText": coords or None,
            "explicitFirCodes": fir_codes,
            "sourceUrl": SOURCE_URL,
        })

    active = [r for r in all_rows if r["effectiveStatus"] == "active"]
    result = {
        "schemaVersion": 1,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "provider": "European Union Aviation Safety Agency (EASA)",
        "sourceUrl": SOURCE_URL,
        "attribution": "Source: European Union Aviation Safety Agency (EASA), Conflict Zone Information Bulletins. Reproduction authorised provided the source is acknowledged.",
        "disclaimer": "Advisory information only. Not a NOTAM, AIP, flight-planning clearance, legal determination or sole source for an operator risk assessment. Verify current State NOTAMs, AIPs, operator policy and the original EASA bulletin.",
        "recordCount": len(all_rows),
        "activeCount": len(active),
        "records": all_rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Deliberately separate advisory warnings from legal prohibitions.
    filter_data = {
        "schemaVersion": 1,
        "generatedAtUtc": result["generatedAtUtc"],
        "source": "EASA CZIB JSON export",
        "sourceUrl": SOURCE_URL,
        "policy": {
            "defaultAvoidActiveEasaAdvisories": True,
            "meaning": "Route preview preference only: suggest avoiding active advisory areas. This is not a legal prohibition and does not replace NOTAM/AIP/operator checks.",
            "hardNoFlyFirs": [],
            "hardNoFlyStatus": "not_populated_no_verified_machine_readable_prohibition_feed_ingested",
            "advisoryFirsRequireVerifiedGeometry": True,
        },
        "activeAdvisories": [
            {
                "sourceId": r["sourceId"],
                "name": r["name"],
                "country": r["country"],
                "validUntil": r["validUntil"],
                "explicitFirCodes": r["explicitFirCodes"],
                "status": r["effectiveStatus"],
            } for r in active
        ],
        "unmappedAdvisories": [
            r["sourceId"] for r in active if not r["explicitFirCodes"]
        ],
        "firBoundaryDataset": {
            "status": "not_ingested",
            "note": "No FIR polygon is fabricated from country names or advisory centroids. A separately licensed global FIR geometry source is required."
        }
    }
    FILTER.parent.mkdir(parents=True, exist_ok=True)
    FILTER.write_text(json.dumps(filter_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"EASA CZIB import: {len(all_rows)} total; {len(active)} active; {len(result['unmappedAdvisories'])} active advisories not mapped to explicit FIR codes")


if __name__ == "__main__":
    normalize()
