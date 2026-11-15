#!/usr/bin/env python3
"""Download worldwide OpenAIP FIR/UIR polygons and map EASA advisory areas."""

from __future__ import annotations

import concurrent.futures
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AIRPORTS = ROOT / "navigation/airports/ourairports_airports.csv"
OUT_DIR = ROOT / "navigation/airspace"
OUT_GEOJSON = OUT_DIR / "openaip_fir_boundaries.geojson"
OUT_META = OUT_DIR / "meta.json"
EASA_FILE = ROOT / "airspace/advisories/easa_czibs.json"
FILTER_FILE = ROOT / "airspace/airspace_filter.json"
BASE = "https://storage.openaip.net/openaip-system-exports/{cc}_asp.geojson"
LICENSE = "CC BY-NC 4.0"
ATTRIBUTION = "Contains data from OpenAIP (https://www.openaip.net/), licensed under CC BY-NC 4.0."

# ISO country codes for the current EASA advisory set. Country export coverage
# is still discovered from OurAirports; this map is only for advisory matching.
EASA_COUNTRY_CODES = {
    "Jordan": ["JO"], "Saudi Arabia": ["SA"], "Syria": ["SY"],
    "Somalia": ["SO"], "Mali": ["ML"], "Yemen": ["YE"],
    "Iran": ["IR"], "Iraq": ["IQ"], "Lebanon": ["LB"],
    "Bahrain": ["BH"], "Kuwait": ["KW"], "Qatar": ["QA"],
    "Oman": ["OM"], "United Arab Emirates": ["AE"], "Libya": ["LY"],
    "Afghanistan": ["AF"], "Pakistan": ["PK"], "Ukraine": ["UA"],
    "Sudan": ["SD"], "Russia": ["RU"],
}
RUSSIA_CZIB_FIR_CODES = {"UUWV", "URRV", "ULLL", "USSV", "UWWW"}



def country_codes():
    codes = set()
    import csv
    with AIRPORTS.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = (row.get("country") or row.get("source_iso_country") or row.get("iso_country") or "").strip().lower()
            if re.fullmatch(r"[a-z]{2}", code):
                codes.add(code)
    if not codes:
        raise RuntimeError("No ISO country codes found in OurAirports worldwide extract")
    return sorted(codes)


def fetch_country(cc):
    url = BASE.format(cc=cc)
    request = urllib.request.Request(url, headers={"User-Agent": "FlightTempo-data-import/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return cc, None, "not_published"
        raise
    data = json.loads(payload.decode("utf-8"))
    if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise ValueError(f"Unexpected OpenAIP GeoJSON structure for {cc}")
    return cc, data, None


FIR_NAME_TO_CODE = {
    "TEHRAN FIR": "OIIX", "TRIPOLI FIR": "HLLL",
    "KALININGRAD FIR": "UMKK", "SAMARA FIR": "UWWW",
    "YEKATERINBURG FIR": "USSV", "YEKATARINBURG FIR": "USSV",
    "SIMFEROPOL FIR": "UKFV", "ROSTOV-NA-DONU FIR": "URRV",
    "MOSCOW FIR": "UUWV", "ST PETERSBURG FIR": "ULLL",
    "KYIV FIR": "UKBV", "DNIPRO FIR": "UKDV",
    "LVIV FIR": "UKLV", "ODESA FIR": "UKOV",
    "KHARTOUM FIR": "HSSS", "NIAMEY FIR": "DRRR",
    "KABUL FIR": "OAKX", "MOGADISHU FIR": "HCSM",
    "DAMASCUS FIR": "OSTT", "BAGHDAD FIR": "ORBB",
    "SANAA FIR": "OYSC", "SANA'A FIR": "OYSC",
    "AMMAN FIR": "OJAC", "BEIRUT FIR": "OLBB",
    "BAHRAIN FIR": "OBBB", "KUWAIT FIR": "OKAC",
    "DOHA FIR": "OTDF", "MUSCAT FIR": "OOMM",
    "EMIRATES FIR": "OMAE", "JEDDAH FIR": "OEJD",
    "ISLAMABAD FIR": "OPIS", "KARACHI FIR": "OPKR",
    "LAHORE FIR": "OPLR", "PYONGYANG FIR": "ZKKP",
}


def fir_code(properties):
    for key in ("designator", "icaoCode", "code", "ident"):
        value = str(properties.get(key) or "").strip().upper()
        if len(value) == 4 and value.isalpha():
            return value
    raw_name = str(properties.get("name") or "").upper().replace("/", " ").strip()
    for known_name, code in FIR_NAME_TO_CODE.items():
        if known_name in raw_name:
            return code
    tokens = raw_name.split()
    for index, token in enumerate(tokens):
        if token in {"FIR", "UIR"} and index + 1 < len(tokens):
            candidate = tokens[index + 1]
            if len(candidate) == 4 and candidate.isalpha():
                return candidate
        if len(token) == 4 and token.isalpha() and index + 1 < len(tokens) and tokens[index + 1] in {"FIR", "UIR"}:
            return token
    return None


def is_fir(feature):
    props = feature.get("properties") or {}
    value = props.get("type")
    # OpenAIP Airspace enum: 10=FIR, 11=UIR.
    if value in (10, 11, "10", "11"):
        return True
    if isinstance(value, str) and value.upper() in {"FIR", "UIR"}:
        return True
    label = str(props.get("typeName") or props.get("typeLabel") or "").upper()
    return label in {"FIR", "UIR"}


def main():
    codes = country_codes()
    found = []
    missing = []
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_country, cc): cc for cc in codes}
        for future in concurrent.futures.as_completed(futures):
            cc = futures[future]
            try:
                country, data, status = future.result()
                if status:
                    missing.append(country)
                    continue
                for feature in data["features"]:
                    if not is_fir(feature):
                        continue
                    geometry = feature.get("geometry")
                    if not geometry or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
                        continue
                    props = dict(feature.get("properties") or {})
                    props["flightTempoSourceCountry"] = country.upper()
                    props["flightTempoSourceUrl"] = BASE.format(cc=country)
                    props["flightTempoFirCode"] = fir_code(props)
                    found.append({
                        "type": "Feature",
                        "id": feature.get("id"),
                        "geometry": geometry,
                        "properties": props,
                    })
            except Exception as exc:
                errors.append({"country": cc, "error": str(exc)})

    if errors:
        raise RuntimeError("OpenAIP export download errors: " + json.dumps(errors[:20]))
    if not found:
        raise RuntimeError("No FIR/UIR polygons downloaded from OpenAIP country exports")

    # Deduplicate copies of the same FIR returned in neighbouring country packs.
    unique = {}
    for feature in found:
        props = feature["properties"]
        code = props.get("flightTempoFirCode") or fir_code(props) or feature.get("id")
        key = (str(code), json.dumps(feature["geometry"], sort_keys=True, separators=(",", ":")))
        if key not in unique:
            unique[key] = feature
        else:
            old = unique[key]["properties"].setdefault("flightTempoSourceCountries", [])
            country = props.get("flightTempoSourceCountry")
            if country and country not in old:
                old.append(country)
        unique[key]["properties"].setdefault("flightTempoSourceCountries", [props.get("flightTempoSourceCountry")])

    features = list(unique.values())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    geo = {
        "type": "FeatureCollection",
        "name": "FlightTempo OpenAIP FIR and UIR boundaries",
        "attribution": ATTRIBUTION,
        "features": features,
    }
    OUT_GEOJSON.write_text(json.dumps(geo, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")

    # Map EASA advisories to the FIR/UIR features delivered in the relevant
    # country exports. These are advisory overlaps, not legal prohibitions.
    easa = json.loads(EASA_FILE.read_text(encoding="utf-8"))
    advisories = []
    for item in easa.get("records", []):
        if item.get("effectiveStatus") != "active":
            continue
        country_names = [x.strip() for x in (item.get("country") or "").split(",") if x.strip()]
        wanted = {code for name in country_names for code in EASA_COUNTRY_CODES.get(name, [])}
        affected = []
        explicit_fir_codes = list(item.get("explicitFirCodes") or [])
        is_russia_czib = item.get("sourceId") == "141480" or "russian federation" in str(item.get("name", "")).lower()
        for feature in features:
            source_countries = set(feature["properties"].get("flightTempoSourceCountries", []))
            if not (source_countries & wanted):
                continue
            props = feature["properties"]
            code = props.get("flightTempoFirCode") or fir_code(props)
            # The Russian CZIB names exactly five FIRs. Do not associate every
            # polygon in the Russian country export (for example UMKK/UKFV).
            if is_russia_czib and code not in RUSSIA_CZIB_FIR_CODES:
                continue
            if explicit_fir_codes and code not in set(explicit_fir_codes):
                continue
            geometry_note = (
                "OpenAIP UWWW geometry extends east of 60E and is not clipped to the EASA CZIB limit."
                if code == "UWWW" and is_russia_czib else
                "Community-maintained OpenAIP FIR reference geometry; verify against current State AIP."
            )
            affected.append({
                "firCode": code,
                "name": props.get("name"),
                "sourceCountryCodes": sorted(source_countries),
                "geometryFeatureId": feature.get("id"),
                "geometrySource": "OpenAIP",
                "geometryNote": geometry_note,
            })
        advisories.append({
            "sourceId": item.get("sourceId"),
            "name": item.get("name"),
            "country": item.get("country"),
            "validUntil": item.get("validUntil"),
            "explicitFirCodes": explicit_fir_codes,
            "affectedFirs": affected,
            "mappingMethod": (
                "Official EASA detail page FIR list matched by exact ICAO designator; OpenAIP geometry is partial and requires review."
                if is_russia_czib else
                "country-export polygon association; verify FIR designators and boundaries against State AIP"
            ),
        })

    filter_data = json.loads(FILTER_FILE.read_text(encoding="utf-8"))
    filter_data["firBoundaryDataset"] = {
        "status": "available_development_reference",
        "source": "OpenAIP",
        "license": LICENSE,
        "attribution": ATTRIBUTION,
        "featureCount": len(features),
        "file": "navigation/airspace/openaip_fir_boundaries.geojson",
        "note": "Community-maintained FIR/UIR geometry. Advisory-country association is a routing hint, not a legal prohibition. Verify against current State AIPs and NOTAMs."
    }
    filter_data["activeAdvisories"] = advisories
    active_firs = []
    seen_firs = set()
    for advisory in advisories:
        for fir in advisory.get("affectedFirs", []):
            key = (fir.get("firCode"), fir.get("geometryFeatureId"))
            if key in seen_firs:
                continue
            seen_firs.add(key)
            active_firs.append({
                "firCode": fir.get("firCode"),
                "name": fir.get("name"),
                "geometryFeatureId": fir.get("geometryFeatureId"),
                "geometryAvailable": fir.get("geometryFeatureId") is not None,
                "sourceAdvisoryId": advisory.get("sourceId"),
                "country": advisory.get("country"),
                "validUntil": advisory.get("validUntil"),
                "classification": "EASA_advisory_not_legal_prohibition"
            })
        geometry_codes = {
            fir.get("firCode") for fir in advisory.get("affectedFirs", [])
            if fir.get("geometryFeatureId") is not None
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
                    "classification": "EASA_advisory_not_legal_prohibition",
                    "geometryNote": "No matching FIR polygon is present in the imported boundary dataset."
                })
    filter_data["activeFirs"] = active_firs
    filter_data["unmappedAdvisories"] = [x["sourceId"] for x in advisories if not x.get("affectedFirs") and not x.get("explicitFirCodes")]
    available_geometry_codes = {x.get("firCode") for x in active_firs if x.get("geometryFeatureId") is not None}
    missing_geometry = []
    geometry_review = []
    for advisory in advisories:
        for code in advisory.get("explicitFirCodes", []):
            if code not in available_geometry_codes:
                missing_geometry.append({
                    "sourceId": advisory.get("sourceId"), "instrumentType": "EASA_CZIB",
                    "firCode": code,
                    "reason": "No matching FIR polygon is present in the imported OpenAIP boundary dataset."
                })
        for fir in advisory.get("affectedFirs", []):
            if fir.get("firCode") == "UWWW":
                geometry_review.append({
                    "sourceId": advisory.get("sourceId"), "firCode": "UWWW",
                    "reason": "OpenAIP Samara FIR polygon extends east of 60E; clip before representing the exact EASA CZIB footprint."
                })
    for directive in filter_data.get("safetyDirectives", []):
        for fir in directive.get("affectedFirs", []):
            if not fir.get("geometryAvailable", False):
                missing_geometry.append({
                    "sourceId": directive.get("sourceId"), "instrumentType": "EASA_SAFETY_DIRECTIVE",
                    "firCode": fir.get("firCode"),
                    "reason": fir.get("geometryReason", "FIR geometry is not available.")
                })
    filter_data["missingFIRGeometry"] = missing_geometry
    filter_data["geometryReviewRequired"] = geometry_review
    filter_data["generatedAtUtc"] = datetime.now(timezone.utc).isoformat()
    FILTER_FILE.write_text(json.dumps(filter_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    import hashlib
    raw = OUT_GEOJSON.read_bytes()
    meta = {
        "source": "OpenAIP country airspace exports",
        "sourceUrl": "https://www.openaip.net/",
        "airacCycle": None,
        "effectiveDate": None,
        "expiryDate": None,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "licenceStatus": "CC_BY_NC_4.0_attribution_required_non_commercial_only",
        "licenseName": LICENSE,
        "attribution": ATTRIBUTION,
        "recordCount": len(features),
        "countryCodesRequested": len(codes),
        "countryExportsMissing": sorted(missing),
        "files": [{
            "path": OUT_GEOJSON.name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "sizeBytes": len(raw),
            "recordCount": len(features),
        }],
        "notes": "Community-maintained FIR/UIR reference polygons, not an official or operationally approved boundary dataset. Country-pack association for EASA advisory areas is only a routing-preview hint."
    }
    OUT_META.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"countryExportsRequested": len(codes), "missing": len(missing), "firUirFeatures": len(features), "easaAdvisoriesMapped": len(advisories)}, indent=2))


if __name__ == "__main__":
    main()
