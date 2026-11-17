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
RUSSIA_CZIB_FIR_CODES = ["UUWV", "URRV", "ULLL", "USSV", "UWWW"]
SAFETY_DIRECTIVES = ROOT / "airspace/advisories/easa_safety_directives.json"


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
        # FIR scope is taken from the authoritative advisory detail page, not
        # inferred from every polygon in a country's export. The Russia CZIB
        # explicitly lists these five FIRs west of 60E.
        if "russian federation" in name.lower():
            fir_codes = list(RUSSIA_CZIB_FIR_CODES)
        elif "sana" in name.lower() and "flight information region" in name.lower():
            fir_codes = ["OYSC"]
        else:
            fir_codes = []
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
    # Preserve the separately imported FIR geometry and country-to-FIR mapping
    # when the daily EASA feed refresh runs.
    if FILTER.is_file():
        try:
            previous_filter = json.loads(FILTER.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_filter = {}
        for preserved_key in ("faaRestrictions", "conditionalRestrictions", "faaRestrictionSource", "hardNoFlyFirs"):
            if preserved_key in previous_filter:
                filter_data[preserved_key] = previous_filter[preserved_key]
        previous_firs = previous_filter.get("firBoundaryDataset")
        if isinstance(previous_firs, dict) and previous_firs.get("status") == "available_development_reference":
            filter_data["firBoundaryDataset"] = previous_firs
            previous_by_id = {
                str(x.get("sourceId")): x
                for x in previous_filter.get("activeAdvisories", [])
                if isinstance(x, dict)
            }
            for item in filter_data["activeAdvisories"]:
                prior = previous_by_id.get(str(item.get("sourceId")))
                if prior:
                    prior_affected = prior.get("affectedFirs", [])
                    if item.get("name") == "Airspace of the Russian Federation":
                        prior_affected = [
                            fir for fir in prior_affected
                            if fir.get("firCode") in RUSSIA_CZIB_FIR_CODES
                        ]
                    item["affectedFirs"] = prior_affected
                    item["mappingMethod"] = prior.get("mappingMethod", "")
                    for preserved_key in ("routeAvoidanceReady", "geometryCoverageComplete", "affectedAirspace"):
                        if preserved_key in prior:
                            item[preserved_key] = prior[preserved_key]
            active_firs = []
            seen_firs = set()
            for advisory in filter_data["activeAdvisories"]:
                # Never reactivate partial/unverified Russia geometry on the
                # daily EASA refresh. Preserve the explicit FIR codes below as
                # geometry-unavailable warnings until every boundary is
                # source-verified and UWWW is clipped to the 60E limit.
                geometry_ready = advisory.get("routeAvoidanceReady") is not False
                if geometry_ready:
                    for fir in advisory.get("affectedFirs", []):
                        key = (fir.get("firCode"), fir.get("geometryFeatureId"))
                        if key in seen_firs:
                            continue
                        seen_firs.add(key)
                        active_firs.append({
                            "firCode": fir.get("firCode"), "name": fir.get("name"),
                            "geometryFeatureId": fir.get("geometryFeatureId"),
                            "geometryAvailable": fir.get("geometryFeatureId") is not None,
                            "sourceAdvisoryId": advisory.get("sourceId"),
                            "country": advisory.get("country"), "validUntil": advisory.get("validUntil"),
                            "classification": "EASA_advisory_not_legal_prohibition"
                        })
                geometry_codes = {
                    fir.get("firCode") for fir in advisory.get("affectedFirs", [])
                    if geometry_ready and fir.get("geometryFeatureId") is not None
                }
                for code in (advisory.get("explicitFirCodes") or []):
                    if code in geometry_codes:
                        continue
                    key = (code, None)
                    if key not in seen_firs:
                        seen_firs.add(key)
                        active_firs.append({
                            "firCode": code, "name": None, "geometryFeatureId": None,
                            "geometryAvailable": False, "sourceAdvisoryId": advisory.get("sourceId"),
                            "country": advisory.get("country"), "validUntil": advisory.get("validUntil"),
                            "classification": "EASA_advisory_not_legal_prohibition"
                        })
            filter_data["activeFirs"] = active_firs
            filter_data["unmappedAdvisories"] = [
                x["sourceId"] for x in filter_data["activeAdvisories"]
                if not x.get("explicitFirCodes") and not x.get("affectedFirs")
            ]
            if SAFETY_DIRECTIVES.is_file():
                directive_rows = json.loads(SAFETY_DIRECTIVES.read_text(encoding="utf-8")).get("records", [])
                filter_data["safetyDirectives"] = directive_rows
            else:
                filter_data["safetyDirectives"] = []
            geometry_codes = {
                fir.get("firCode") for fir in active_firs
                if fir.get("geometryFeatureId") is not None
            }
            missing_geometry = []
            for advisory in filter_data["activeAdvisories"]:
                for code in (advisory.get("explicitFirCodes") or []):
                    if code not in geometry_codes:
                        missing_geometry.append({
                            "sourceId": advisory.get("sourceId"),
                            "instrumentType": "EASA_CZIB",
                            "firCode": code,
                            "reason": "No matching FIR polygon is present in the imported boundary dataset."
                        })
            for directive in filter_data["safetyDirectives"]:
                for fir in directive.get("affectedFirs", []):
                    if not fir.get("geometryAvailable", False):
                        missing_geometry.append({
                            "sourceId": directive.get("sourceId"),
                            "instrumentType": "EASA_SAFETY_DIRECTIVE",
                            "firCode": fir.get("firCode"),
                            "reason": fir.get("geometryReason", "FIR geometry is not available.")
                        })
            filter_data["missingFIRGeometry"] = missing_geometry
            filter_data["geometryReviewRequired"] = [
                {
                    "sourceId": advisory.get("sourceId"),
                    "firCode": fir.get("firCode"),
                    "reason": fir.get("geometryNote")
                }
                for advisory in filter_data["activeAdvisories"]
                for fir in advisory.get("affectedFirs", [])
                if fir.get("firCode") == "UWWW"
            ]
            filter_data["geometryCoverageStatus"] = (
                "INCOMPLETE: required Russian and Minsk FIR geometry is missing or requires clipping; "
                "missing polygons must never be interpreted as unrestricted airspace."
            )
            filter_data["policy"]["missingGeometryHandling"] = "unknown_not_clear"
    FILTER.parent.mkdir(parents=True, exist_ok=True)
    FILTER.write_text(json.dumps(filter_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"EASA CZIB import: {len(all_rows)} total; {len(active)} active; {len(filter_data['unmappedAdvisories'])} active advisories not mapped to explicit FIR codes")


if __name__ == "__main__":
    normalize()
