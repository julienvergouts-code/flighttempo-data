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
            code = (row.get("iso_country") or "").strip().lower()
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
        code = props.get("designator") or props.get("icaoCode") or props.get("code") or feature.get("id")
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
        for feature in features:
            source_countries = set(feature["properties"].get("flightTempoSourceCountries", []))
            if source_countries & wanted:
                props = feature["properties"]
                code = props.get("designator") or props.get("icaoCode") or props.get("code")
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
