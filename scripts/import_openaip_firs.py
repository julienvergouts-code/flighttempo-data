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
    "YEKATERINBURG FIR": "USSV",
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


RUSSIA_CZIB_2025_01_R3_FIRS = [
    ("UUWV", "MOSCOW FIR"),
    ("URRV", "ROSTOV-NA-DONU FIR"),
    ("ULLL", "SANKT-PETERSBURG FIR"),
    ("USSV", "YEKATERINBURG FIR"),
    ("UWWW", "SAMARA FIR"),
]


def build_russia_advisory_mapping(item, features):
    """Map only the FIRs explicitly named by EASA CZIB 2025-01 R3.

    OpenAIP polygons are candidate reference geometry only. They are not
    validated against State AIPs, UWWW must be clipped at 60E, and the current
    OpenAIP export lacks some of the five FIRs. Therefore this mapping must not
    be activated for route avoidance until all five source-backed geometries
    are present, clipped to the bulletin scope and validated.
    """
    by_code = {}
    for feature in features:
        props = feature.get("properties") or {}
        code = props.get("flightTempoFirCode") or fir_code(props)
        if code and code not in by_code:
            by_code[code] = feature

    affected = []
    for code, name in RUSSIA_CZIB_2025_01_R3_FIRS:
        feature = by_code.get(code)
        props = (feature.get("properties") or {}) if feature else {}
        verified = props.get("flightTempoVerifiedAgainstStateAip") is True
        clipped = props.get("flightTempoClippedAt60E") is True
        affected.append({
            "firCode": code,
            "name": name,
            "sourceCountryCodes": ["RU"],
            "geometryFeatureId": feature.get("id") if feature else None,
            "geometryAvailable": feature is not None,
            "geometrySource": "OpenAIP CC BY-NC 4.0 development reference" if feature else None,
            "geometryVerifiedAgainstStateAip": verified,
            "geometryClippedTo60E": clipped,
            "geometryStatus": (
                "state_aip_verified" if verified and clipped
                else "candidate_openAIP_unverified" if feature
                else "missing_in_current_OpenAIP_export"
            ),
            "requiresLongitudeClipAt60E": True,
        })

    complete = all(
        x["geometryAvailable"]
        and x["geometryVerifiedAgainstStateAip"]
        and x["geometryClippedTo60E"]
        for x in affected
    )
    return {
        "affectedAirspace": {
            "territory": "Russian Federation",
            "longitudeLimitDegreesEast": 60.0,
            "longitudeRelationship": "west_of",
            "verticalScope": "all_altitudes_and_flight_levels",
            "sourceText": "All altitudes / flight levels in the airspace of the Russian Federation west of longitude 60° East.",
        },
        "affectedFirs": affected,
        "geometryCoverageComplete": complete,
        "routeAvoidanceReady": complete,
        "mappingMethod": "explicit_fir_list_from_EASA_CZIB_2025-01_R3; candidate OpenAIP polygons are community reference geometry only; no country-export association or synthetic boundary is used",
    }


def build_active_firs(advisories):
    active_firs = []
    seen_firs = set()
    for advisory in advisories:
        # An incomplete or unvalidated advisory set is not safe to treat as a
        # complete avoidance polygon set. Keep its scope in the advisory
        # record but do not activate partial geometries in the route layer.
        if advisory.get("routeAvoidanceReady") is False:
            continue
        for fir in advisory.get("affectedFirs", []):
            key = (fir.get("firCode"), fir.get("geometryFeatureId"))
            if key in seen_firs:
                continue
            seen_firs.add(key)
            active_firs.append({
                "firCode": fir.get("firCode"),
                "name": fir.get("name"),
                "geometryFeatureId": fir.get("geometryFeatureId"),
                "geometryAvailable": fir.get("geometryAvailable", fir.get("geometryFeatureId") is not None),
                "sourceAdvisoryId": advisory.get("sourceId"),
                "country": advisory.get("country"),
                "validUntil": advisory.get("validUntil"),
                "classification": "EASA_advisory_not_legal_prohibition",
            })
        for code in (advisory.get("explicitFirCodes") or []):
            key = (code, None)
            if key not in seen_firs:
                seen_firs.add(key)
                active_firs.append({
                    "firCode": code, "name": None, "geometryFeatureId": None,
                    "geometryAvailable": False, "sourceAdvisoryId": advisory.get("sourceId"),
                    "country": advisory.get("country"), "validUntil": advisory.get("validUntil"),
                    "classification": "EASA_advisory_not_legal_prohibition",
                })
    return active_firs


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

        # The Russian bulletin names five FIRs and a 60E limit. Do not use
        # country-export matching here: it incorrectly attaches unrelated FIRs
        # (e.g. Kaliningrad and Simferopol) and misses the actual five-FIR scope.
        if str(item.get("sourceId")) == "141480":
            mapped = build_russia_advisory_mapping(item, features)
            advisories.append({
                "sourceId": item.get("sourceId"),
                "name": item.get("name"),
                "country": item.get("country"),
                "validUntil": item.get("validUntil"),
                **mapped,
            })
            continue

        country_names = [x.strip() for x in (item.get("country") or "").split(",") if x.strip()]
        wanted = {code for name in country_names for code in EASA_COUNTRY_CODES.get(name, [])}
        affected = []
        for feature in features:
            source_countries = set(feature["properties"].get("flightTempoSourceCountries", []))
            if source_countries & wanted:
                props = feature["properties"]
                code = props.get("flightTempoFirCode") or fir_code(props)
                affected.append({
                    "firCode": code,
                    "name": props.get("name"),
                    "sourceCountryCodes": sorted(source_countries),
                    "geometryFeatureId": feature.get("id"),
                })
        advisories.append({
            "sourceId": item.get("sourceId"),
            "name": item.get("name"),
            "country": item.get("country"),
            "validUntil": item.get("validUntil"),
            "affectedFirs": affected,
            "mappingMethod": "country-export polygon association; verify FIR designators and boundaries against State AIP",
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
    active_firs = build_active_firs(advisories)
    filter_data["activeFirs"] = active_firs
    filter_data["unmappedAdvisories"] = [x["sourceId"] for x in advisories if not x.get("affectedFirs") and not x.get("explicitFirCodes")]
    filter_data["incompleteGeometryAdvisories"] = [
        x["sourceId"] for x in advisories if x.get("routeAvoidanceReady") is False
    ]
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
