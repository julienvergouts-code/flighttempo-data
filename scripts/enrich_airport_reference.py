#!/usr/bin/env python3
"""Enrich FlightTempo's airport reference with OurAirports elevations and runway ends.

The existing first nine columns are preserved for the current Android parser.
Additional columns retain all matched runway pairs for later multi-runway UI support.
Source snapshots are refreshed by build_aviation_db.py before this script runs.
"""
import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "airports.csv"
SOURCE_AIRPORTS = ROOT / "navigation/sources/airports.csv"
SOURCE_RUNWAYS = ROOT / "navigation/sources/runways.csv"
MANIFEST = ROOT / "navigation_manifest.json"

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
    for row in airports:
        ident = clean(row.get("ident")).upper()
        icao = clean(row.get("icao_code")).upper()
        elevation = number(row.get("elevation_ft"))
        if elevation is None:
            continue
        if ident:
            elevations.setdefault(ident, int(round(elevation)))
        if icao:
            elevations[icao] = int(round(elevation))
    return elevations

def build_runway_lookup(runways):
    by_airport = {}
    for row in runways:
        if clean(row.get("closed")) == "1":
            continue

        airport = clean(row.get("airport_ident")).upper()
        low = clean(row.get("le_ident")).upper()
        high = clean(row.get("he_ident")).upper()
        length = number(row.get("length_ft"))

        # Only real, paired runway records with a usable length are put into
        # the airport's runway list. Full raw runway records remain in the
        # separate runways dataset, including unpaired and unusual surfaces.
        if not airport or not low or not high or length is None or length <= 0:
            continue

        pair = f"{low}/{high}"
        heading = number(row.get("le_heading_degT"))
        item = {
            "pair": pair,
            "heading": int(round(heading)) if heading is not None and 0 <= heading <= 360 else None,
            "length": int(round(length)),
        }
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

def main():
    for required in (REFERENCE, SOURCE_AIRPORTS, SOURCE_RUNWAYS, MANIFEST):
        if not required.is_file():
            raise RuntimeError(f"Required input is missing: {required}")

    source_airports = read_rows(SOURCE_AIRPORTS)
    source_runways = read_rows(SOURCE_RUNWAYS)
    elevations = build_airport_lookups(source_airports)
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

    for row in records:
        iata, icao, timezone_id, name, lat, lon, old_elev, old_pair, old_heading = row
        code = clean(icao).upper()

        elevation = elevations.get(code)
        runway_items = runways.get(code, [])

        if elevation is not None:
            old_elev = str(elevation)
            elevation_matches += 1

        if runway_items:
            runway_matches += 1
            if len(runway_items) > 1:
                multiple_runway_matches += 1

            primary = next((r for r in runway_items if r["heading"] is not None), runway_items[0])
            old_pair = primary["pair"]
            old_heading = str(primary["heading"]) if primary["heading"] is not None else "-1"
            all_pairs = "|".join(r["pair"] for r in runway_items)
            all_headings = "|".join("" if r["heading"] is None else str(r["heading"]) for r in runway_items)
            all_lengths = "|".join(str(r["length"]) for r in runway_items)
        else:
            all_pairs = old_pair
            all_headings = old_heading
            all_lengths = ""

        updated.append([
            iata, icao, timezone_id, name, lat, lon, old_elev,
            old_pair, old_heading, all_pairs, all_headings,
            all_lengths, str(len(runway_items))
        ])

    timestamp = datetime.now(timezone.utc).isoformat()
    version = datetime.now(timezone.utc).strftime("%Y%m%d")
    temp = REFERENCE.with_suffix(".csv.tmp")

    with temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["#version", version])
        writer.writerow([
            "#columns", "iata", "icao", "timeZone", "name", "latitude",
            "longitude", "elevationFt", "runwayPair", "runwayHeadingDeg",
            "allRunwayPairs", "allRunwayHeadingsDeg", "allRunwayLengthsFt",
            "runwayCount"
        ])
        writer.writerows(updated)

    temp.replace(REFERENCE)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    datasets = manifest.setdefault("datasets", [])
    dataset = next((d for d in datasets if d.get("id") == "airport_reference"), None)
    if dataset is None:
        dataset = {
            "id": "airport_reference",
            "path": "airports.csv",
            "downloadUrl": "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/airports.csv",
            "available": True
        }
        datasets.append(dataset)

    dataset.update({
        "path": "airports.csv",
        "downloadUrl": "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/airports.csv",
        "available": True,
        "recordCount": len(updated),
        "sizeBytes": REFERENCE.stat().st_size,
        "sha256": sha256_file(REFERENCE),
        "sourceProvider": "FlightTempo airport reference with OurAirports enrichment",
        "sourceUrl": "https://ourairports.com/data/",
        "coverage": "Global airport reference; elevation and all paired open runways enriched where ICAO/OurAirports identifiers match",
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
        "airportReferenceMultipleRunwayAirports": multiple_runway_matches
    })
    manifest["airportReferenceEnrichment"] = {
        "provider": "OurAirports",
        "airportSource": "https://davidmegginson.github.io/ourairports-data/airports.csv",
        "runwaySource": "https://davidmegginson.github.io/ourairports-data/runways.csv",
        "license": "Public Domain / CC0 as stated by OurAirports",
        "downloadedAtUtc": timestamp,
        "matchedElevationRecords": elevation_matches,
        "matchedAirportsWithRunways": runway_matches,
        "matchedAirportsWithMultipleRunways": multiple_runway_matches,
        "runwaySelection": "Longest open paired runway is placed in legacy primary fields; all matched pairs/headings/lengths are retained in appended pipe-delimited columns.",
        "limitations": "Community-maintained source data; no guarantee of accuracy or operational fitness. Full runway records remain in navigation/runways/runways_parsed.csv."
    }

    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "airportRecords": len(updated),
        "elevationMatches": elevation_matches,
        "airportsWithRunways": runway_matches,
        "airportsWithMultipleRunways": multiple_runway_matches,
        "airportFileBytes": REFERENCE.stat().st_size,
        "airportFileSha256": sha256_file(REFERENCE)
    }, indent=2))

if __name__ == "__main__":
    main()
