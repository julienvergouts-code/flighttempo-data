#!/usr/bin/env python3
"""Enrich FlightTempo's airport reference with the complete useful OurAirports fields.

The existing first nine columns are preserved for the current Android parser.
New airport metadata and runway-detail columns are appended for future app use.
The normalized source CSVs remain the authoritative full per-record exports.
"""
import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "airports/airports.csv"
SOURCE_AIRPORTS = ROOT / "navigation/sources/airports.csv"
SOURCE_RUNWAYS = ROOT / "navigation/sources/runways.csv"
MANIFEST = ROOT / "navigation_manifest.json"

AIRPORT_FIELDS = [
    ("ourairportsId", "id"),
    ("airportType", "type"),
    ("continent", "continent"),
    ("isoCountry", "iso_country"),
    ("isoRegion", "iso_region"),
    ("municipality", "municipality"),
    ("scheduledService", "scheduled_service"),
    ("gpsCode", "gps_code"),
    ("localCode", "local_code"),
    ("homeLink", "home_link"),
    ("wikipediaLink", "wikipedia_link"),
    ("keywords", "keywords"),
]

RUNWAY_FIELDS = [
    ("allRunwaySourceIds", "id"),
    ("allRunwayWidthsFt", "width_ft"),
    ("allRunwaySurfaces", "surface"),
    ("allRunwayLighted", "lighted"),
    ("allRunwayLELatitudes", "le_latitude_deg"),
    ("allRunwayLELongitudes", "le_longitude_deg"),
    ("allRunwayLEElevationsFt", "le_elevation_ft"),
    ("allRunwayLEDisplacedThresholdsFt", "le_displaced_threshold_ft"),
    ("allRunwayLEHeadingsDegT", "le_heading_degT"),
    ("allRunwayHELatitudes", "he_latitude_deg"),
    ("allRunwayHELongitudes", "he_longitude_deg"),
    ("allRunwayHEElevationsFt", "he_elevation_ft"),
    ("allRunwayHEDisplacedThresholdsFt", "he_displaced_threshold_ft"),
    ("allRunwayHEHeadingsDegT", "he_heading_degT"),
]

def clean(value):
    return (value or "").strip()

def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None

def read_rows(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))

def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def build_airport_lookups(airports):
    elevations = {}
    metadata = {}
    for row in airports:
        ident = clean(row.get("ident")).upper()
        icao = clean(row.get("icao_code")).upper()
        gps = clean(row.get("gps_code")).upper()
        elevation = number(row.get("elevation_ft"))
        if elevation is not None:
            if ident:
                elevations.setdefault(ident, int(round(elevation)))
            if icao:
                elevations[icao] = int(round(elevation))

        details = {
            output: clean(row.get(source))
            for output, source in AIRPORT_FIELDS
        }
        for key in (icao, ident, gps):
            if key:
                metadata.setdefault(key, details)
    return elevations, metadata

def build_runway_lookup(runways):
    by_airport = {}
    for row in runways:
        if clean(row.get("closed")) == "1":
            continue

        airport = clean(row.get("airport_ident")).upper()
        low = clean(row.get("le_ident")).upper()
        high = clean(row.get("he_ident")).upper()
        length = number(row.get("length_ft"))

        # Keep any open runway with a usable length and at least one identified
        # end. Unpaired source records remain available in the full runway CSV.
        if not airport or not low or length is None or length <= 0:
            continue

        pair = f"{low}/{high}" if high else low
        item = {
            "pair": pair,
            "heading": number(row.get("le_heading_degT")),
            "length": int(round(length)),
        }
        for output, source in RUNWAY_FIELDS:
            item[output] = clean(row.get(source))
        by_airport.setdefault(airport, []).append(item)

    for airport, items in by_airport.items():
        deduped = {}
        for item in items:
            old = deduped.get(item["pair"])
            if old is None or item["length"] > old["length"]:
                deduped[item["pair"]] = item
        by_airport[airport] = sorted(
            deduped.values(),
            key=lambda x: (-x["length"], x["pair"])
        )
    return by_airport

def pipe_values(items, key):
    # Keep positional alignment between runway fields. Empty values are
    # intentionally retained as empty tokens between pipe separators.
    return "|".join(item.get(key, "") for item in items)

def main():
    for required in (REFERENCE, SOURCE_AIRPORTS, SOURCE_RUNWAYS, MANIFEST):
        if not required.is_file():
            raise RuntimeError(f"Required input is missing: {required}")

    source_airports = read_rows(SOURCE_AIRPORTS)
    source_runways = read_rows(SOURCE_RUNWAYS)
    elevations, airport_metadata = build_airport_lookups(source_airports)
    runways = build_runway_lookup(source_runways)

    with REFERENCE.open("r", encoding="utf-8-sig", newline="") as handle:
        existing_rows = list(csv.reader(handle))

    records = []
    for row in existing_rows:
        if not row:
            continue
        if row[0].strip().lower().startswith(("#version", "#columns", "#source")):
            continue
        if row[0].strip().lower().startswith("sep="):
            continue
        if len(row) < 6:
            continue
        row = list(row) + [""] * max(0, 9 - len(row))
        records.append(row[:9])

    if len(records) < 1000:
        raise RuntimeError(f"Airport reference has too few records: {len(records)}")

    updated = []
    elevation_matches = 0
    runway_matches = 0
    multiple_runway_matches = 0
    airport_metadata_matches = 0

    for row in records:
        iata, icao, timezone_id, name, lat, lon, old_elev, old_pair, old_heading = row
        code = clean(icao).upper()

        elevation = elevations.get(code)
        runway_items = runways.get(code, [])
        airport_details = airport_metadata.get(code, {})

        if elevation is not None:
            old_elev = str(elevation)
            elevation_matches += 1

        if airport_details:
            airport_metadata_matches += 1

        if runway_items:
            runway_matches += 1
            if len(runway_items) > 1:
                multiple_runway_matches += 1

            primary = next((r for r in runway_items if r["heading"] is not None), runway_items[0])
            old_pair = primary["pair"]
            old_heading = str(int(round(primary["heading"]))) if primary["heading"] is not None and 0 <= primary["heading"] <= 360 else "-1"
            all_pairs = "|".join(r["pair"] for r in runway_items)
            all_headings = "|".join(
                "" if r["heading"] is None or not 0 <= r["heading"] <= 360 else str(int(round(r["heading"])))
                for r in runway_items
            )
            all_lengths = "|".join(str(r["length"]) for r in runway_items)
        else:
            all_pairs = old_pair
            all_headings = old_heading
            all_lengths = ""

        airport_values = [airport_details.get(output, "") for output, _ in AIRPORT_FIELDS]
        runway_values = [pipe_values(runway_items, output) for output, _ in RUNWAY_FIELDS]

        updated.append([
            iata, icao, timezone_id, name, lat, lon, old_elev,
            old_pair, old_heading, all_pairs, all_headings,
            all_lengths, str(len(runway_items))
        ] + airport_values + runway_values)

    timestamp = datetime.now(timezone.utc).isoformat()
    version = datetime.now(timezone.utc).strftime("%Y%m%d")
    temp = REFERENCE.with_suffix(".csv.tmp")

    header = [
        "#columns", "iata", "icao", "timeZone", "name", "latitude",
        "longitude", "elevationFt", "runwayPair", "runwayHeadingDeg",
        "allRunwayPairs", "allRunwayHeadingsDeg", "allRunwayLengthsFt",
        "runwayCount"
    ] + [output for output, _ in AIRPORT_FIELDS] + [output for output, _ in RUNWAY_FIELDS]

    with temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["#version", version])
        writer.writerow(header)
        writer.writerows(updated)

    temp.replace(REFERENCE)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    datasets = manifest.setdefault("datasets", [])
    dataset = next((d for d in datasets if d.get("id") == "airport_reference"), None)
    if dataset is None:
        dataset = {
            "id": "airport_reference",
            "path": "airports/airports.csv",
            "downloadUrl": "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/airports/airports.csv",
            "available": True
        }
        datasets.append(dataset)

    dataset.update({
        "path": "airports/airports.csv",
        "downloadUrl": "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/airports/airports.csv",
        "available": True,
        "recordCount": len(updated),
        "sizeBytes": REFERENCE.stat().st_size,
        "sha256": sha256_file(REFERENCE),
        "sourceProvider": "FlightTempo airport reference with OurAirports enrichment",
        "sourceUrl": "https://ourairports.com/data/",
        "coverage": "Global airport reference; airport metadata, elevation and runway details enriched where source identifiers match",
        "license": "OurAirports enrichment is Public Domain/CC0; original IATA/time-zone reference provenance remains under review",
        "licenseStatus": "mixed_source_review_required",
        "dataCycle": "daily_source_snapshot",
        "effectiveDate": "",
        "expiryDate": "",
        "provenanceVerification": "partial"
    })

    manifest.setdefault("statistics", {}).update({
        "airportReferenceRecords": len(updated),
        "airportReferenceOurAirportsElevationMatches": elevation_matches,
        "airportReferenceRunwayMatches": runway_matches,
        "airportReferenceMultipleRunwayAirports": multiple_runway_matches,
        "airportReferenceOurAirportsMetadataMatches": airport_metadata_matches
    })
    manifest["airportReferenceEnrichment"] = {
        "provider": "OurAirports",
        "airportSource": "https://davidmegginson.github.io/ourairports-data/airports.csv",
        "runwaySource": "https://davidmegginson.github.io/ourairports-data/runways.csv",
        "license": "Public Domain / CC0 as stated by OurAirports",
        "downloadedAtUtc": timestamp,
        "matchedElevationRecords": elevation_matches,
        "matchedAirportMetadataRecords": airport_metadata_matches,
        "matchedAirportsWithRunways": runway_matches,
        "matchedAirportsWithMultipleRunways": multiple_runway_matches,
        "airportMetadataFields": [output for output, _ in AIRPORT_FIELDS],
        "runwayDetailFields": [output for output, _ in RUNWAY_FIELDS],
        "runwaySelection": "All matched open runway ends with a usable length are retained in aligned pipe-delimited airport reference columns; complete individual runway records are retained in navigation/runways/runways_parsed.csv.",
        "limitations": "Community-maintained source data; no guarantee of accuracy or operational fitness. Full source snapshots and normalized records are retained separately."
    }

    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "airportRecords": len(updated),
        "elevationMatches": elevation_matches,
        "airportMetadataMatches": airport_metadata_matches,
        "airportsWithRunways": runway_matches,
        "airportsWithMultipleRunways": multiple_runway_matches,
        "airportFileBytes": REFERENCE.stat().st_size,
        "airportFileSha256": sha256_file(REFERENCE)
    }, indent=2))

if __name__ == "__main__":
    main()
