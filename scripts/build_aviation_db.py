
#!/usr/bin/env python3
"""
FlightTempo Aviation Database Builder

Source: OurAirports
Datasets: Airports, runways, navaids

No fabricated aviation records.
No assumed AIRAC cycle.
No synthetic SID, STAR or airway data.
"""

import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SOURCE_BASE = "https://davidmegginson.github.io/ourairports-data"

DATASETS = {
    "airports": f"{SOURCE_BASE}/airports.csv",
    "runways": f"{SOURCE_BASE}/runways.csv",
    "navaids": f"{SOURCE_BASE}/navaids.csv",
}

USER_AGENT = "FlightTempo-Aviation-Database/1.0"

MINIMUM_RECORDS = {
    "airports": 1000,
    "runways": 500,
    "navaids": 1000,
}


def log(message):
    print(f"[FlightTempo] {message}", flush=True)


def download(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT}
    )

    with urllib.request.urlopen(request, timeout=90) as response:
        if response.status != 200:
            raise RuntimeError(
                f"HTTP error {response.status}: {url}"
            )

        data = response.read()

    if len(data) < 1000:
        raise RuntimeError(
            f"Downloaded file unexpectedly small: {url}"
        )

    return data


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_csv(data, name):
    try:
        text = data.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))

        if not reader.fieldnames:
            raise ValueError("Missing CSV header")

        return list(reader)

    except Exception as exc:
        raise RuntimeError(
            f"Unable to parse {name}: {exc}"
        ) from exc


def number(value):
    if value is None or str(value).strip() == "":
        return None

    try:
        result = float(value)
        if result != result or abs(result) == float("inf"):
            return None
        return result
    except (ValueError, TypeError):
        return None


def valid_coordinates(lat, lon):
    return (
        lat is not None
        and lon is not None
        and -90 <= lat <= 90
        and -180 <= lon <= 180
    )


def write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w",
        newline="",
        encoding="utf-8"
    ) as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def build_airports(records, stage):
    rows = []
    seen = set()
    source_fields = list(records[0].keys()) if records else []

    for record in records:
        if record.get("type") == "closed_airport":
            continue

        ident = (
            record.get("icao_code")
            or record.get("ident")
            or ""
        ).strip().upper()

        source_id = str(record.get("id") or "").strip()
        record_key = ("id", source_id) if source_id else ("ident", ident)
        if not ident or record_key in seen:
            continue

        lat = number(record.get("latitude_deg"))
        lon = number(record.get("longitude_deg"))
        elevation = number(record.get("elevation_ft"))

        if not valid_coordinates(lat, lon):
            continue

        seen.add(record_key)

        # Keep the stable normalized columns first, then retain every original
        # OurAirports airport field with a source_ prefix for future use.
        rows.append((
            ident,
            (record.get("iso_country") or "").strip().upper(),
            round(lat, 5),
            round(lon, 5),
            round(elevation) if elevation is not None else "",
            (record.get("name") or "").strip()
        ) + tuple(record.get(field, "") for field in source_fields))

    if len(rows) < MINIMUM_RECORDS["airports"]:
        raise RuntimeError(
            f"Airport count too low: {len(rows)}"
        )

    rows.sort(key=lambda row: row[0])

    write_csv(
        stage / "navigation/airports/ourairports_airports.csv",
        [
            "icao",
            "country",
            "latitude",
            "longitude",
            "elevation_ft",
            "name"
        ] + [f"source_{field}" for field in source_fields],
        rows
    )

    return len(rows)


def build_navaids(records, stage):
    rows = []
    seen = set()
    type_counts = {}
    source_fields = list(records[0].keys()) if records else []

    for record in records:
        ident = (record.get("ident") or "").strip().upper()
        nav_type = (record.get("type") or "").strip().upper()

        lat = number(record.get("latitude_deg"))
        lon = number(record.get("longitude_deg"))

        if not ident or not nav_type or not valid_coordinates(lat, lon):
            continue

        source_id = str(record.get("id") or "").strip()
        key = ("id", source_id) if source_id else (
            "nav", ident, nav_type, round(lat, 6), round(lon, 6)
        )
        if key in seen:
            continue
        seen.add(key)

        frequency_khz = number(record.get("frequency_khz"))
        dme_frequency_khz = number(record.get("dme_frequency_khz"))
        dme_lat = number(record.get("dme_latitude_deg"))
        dme_lon = number(record.get("dme_longitude_deg"))
        elevation = number(record.get("elevation_ft"))
        dme_elevation = number(record.get("dme_elevation_ft"))
        slaved_variation = number(record.get("slaved_variation_deg"))
        magnetic_variation = number(record.get("magnetic_variation_deg"))

        normalized = (
            ident,
            (record.get("name") or "").strip(),
            nav_type,
            round(frequency_khz, 3) if frequency_khz is not None else "",
            round(frequency_khz / 1000, 6) if frequency_khz is not None else "",
            round(dme_frequency_khz, 3) if dme_frequency_khz is not None else "",
            round(dme_frequency_khz / 1000, 6) if dme_frequency_khz is not None else "",
            (record.get("dme_channel") or "").strip().upper(),
            round(lat, 6),
            round(lon, 6),
            round(elevation, 1) if elevation is not None else "",
            round(dme_lat, 6) if dme_lat is not None else "",
            round(dme_lon, 6) if dme_lon is not None else "",
            round(dme_elevation, 1) if dme_elevation is not None else "",
            (record.get("iso_country") or "").upper(),
            round(slaved_variation, 3) if slaved_variation is not None else "",
            round(magnetic_variation, 3) if magnetic_variation is not None else "",
            (record.get("usageType") or "").strip().upper(),
            (record.get("power") or "").strip().upper(),
            (record.get("associated_airport") or "").strip().upper()
        )
        rows.append(normalized + tuple(record.get(field, "") for field in source_fields))

        type_counts[nav_type] = type_counts.get(nav_type, 0) + 1

    if len(rows) < MINIMUM_RECORDS["navaids"]:
        raise RuntimeError(
            f"Navaid count too low: {len(rows)}"
        )

    rows.sort(key=lambda row: (row[0], row[2], row[8], row[9]))

    write_csv(
        stage / "navigation/navaids/navaids.csv",
        [
            "ident", "name", "type",
            "frequency_khz", "frequency_mhz",
            "dme_frequency_khz", "dme_frequency_mhz", "dme_channel",
            "latitude_deg", "longitude_deg", "elevation_ft",
            "dme_latitude_deg", "dme_longitude_deg", "dme_elevation_ft",
            "iso_country", "slaved_variation_deg", "magnetic_variation_deg",
            "usage_type", "power", "associated_airport"
        ] + [f"source_{field}" for field in source_fields],
        rows
    )

    return len(rows), dict(sorted(type_counts.items()))


def build_runways(records, stage):
    rows = []
    seen = set()
    source_fields = list(records[0].keys()) if records else []

    for record in records:
        if str(record.get("closed", "")).strip() == "1":
            continue

        airport = (
            record.get("airport_ident") or ""
        ).strip().upper()

        low = (record.get("le_ident") or "").strip().upper()
        high = (record.get("he_ident") or "").strip().upper()

        if not airport or not low:
            continue

        length = number(record.get("length_ft"))
        width = number(record.get("width_ft"))

        low_heading = number(record.get("le_heading_degT"))
        high_heading = number(record.get("he_heading_degT"))

        # Preserve the runway record, but do not publish impossible source headings.
        if low_heading is not None and not 0 <= low_heading <= 360:
            low_heading = None
        if high_heading is not None and not 0 <= high_heading <= 360:
            high_heading = None

        source_id = str(record.get("id") or "").strip()
        key = ("id", source_id) if source_id else ("runway", airport, low, high)
        if key in seen:
            continue
        seen.add(key)

        normalized = (
            airport,
            f"{low}/{high}" if high else low,
            low,
            high,
            round(low_heading, 1) if low_heading is not None else "",
            round(high_heading, 1) if high_heading is not None else "",
            round(length) if length is not None else "",
            round(width) if width is not None else "",
            (record.get("surface") or "").strip(),
            "1" if str(record.get("lighted", "")) == "1" else "0"
        )
        # Every source field is retained, including runway-end coordinates,
        # runway-end elevations, displaced thresholds, closure flag and source IDs.
        rows.append(normalized + tuple(record.get(field, "") for field in source_fields))

    if len(rows) < MINIMUM_RECORDS["runways"]:
        raise RuntimeError(
            f"Runway count too low: {len(rows)}"
        )

    rows.sort(key=lambda row: (row[0], row[1]))

    write_csv(
        stage / "navigation/runways/runways_parsed.csv",
        [
            "airport_icao",
            "runway_pair",
            "le_ident",
            "he_ident",
            "le_heading_degT",
            "he_heading_degT",
            "length_ft",
            "width_ft",
            "surface",
            "lighted"
        ] + [f"source_{field}" for field in source_fields],
        rows
    )

    return len(rows)


def validate_csv(path, minimum_records):
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"Missing or empty file: {path}")

    with path.open(encoding="utf-8") as file:
        count = sum(1 for _ in csv.reader(file)) - 1

    if count < minimum_records:
        raise RuntimeError(
            f"Invalid record count in {path}: {count}"
        )

    return count


def main():
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat()

    log("Starting aviation database build")

    with tempfile.TemporaryDirectory(
        prefix="flighttempo-nav-"
    ) as temporary:

        temp = Path(temporary)
        stage = temp / "staging"
        stage.mkdir()

        sources = {}
        counts = {}

        # Download original files first.
        for name, url in DATASETS.items():
            log(f"Downloading {name}: {url}")

            data = download(url)
            sources[name] = {
                "url": url,
                "provider": "OurAirports",
                "license": "CC0 / Public Domain as stated by OurAirports",
                "downloadedAt": timestamp,
                "sizeBytes": len(data),
                "sha256": sha256(data)
            }

            raw_path = stage / "navigation/sources" / f"{name}.csv"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(data)

        # Parse and normalize.
        airports = read_csv(
            (stage / "navigation/sources/airports.csv").read_bytes(),
            "airports"
        )

        navaids = read_csv(
            (stage / "navigation/sources/navaids.csv").read_bytes(),
            "navaids"
        )

        runways = read_csv(
            (stage / "navigation/sources/runways.csv").read_bytes(),
            "runways"
        )

        counts["airports"] = build_airports(airports, stage)
        counts["navaids"], navaid_type_counts = build_navaids(navaids, stage)
        counts["runways"] = build_runways(runways, stage)

        # Validate all generated files.
        generated = {
            "airports": stage / "navigation/airports/ourairports_airports.csv",
            "navaids": stage / "navigation/navaids/navaids.csv",
            "runways": stage / "navigation/runways/runways_parsed.csv"
        }

        for name, path in generated.items():
            validate_csv(path, MINIMUM_RECORDS[name])
            log(f"Validated {name}: {counts[name]} records")

        manifest = {
            "schemaVersion": 13,
            "generatedAtUtc": timestamp,
            "procedureAiracCycle": "unknown",
            "navaidTypeCounts": navaid_type_counts,
            "targetProfile": "FlightTempo downloadable aviation reference data",
            "statistics": {
                "airports": counts["airports"],
                "runways": counts["runways"],
                "navaids": counts["navaids"],
                "ifrWaypoints": 0,
                "flightgearNavaids": 0,
                "airwaySegments": 0,
                "lowAirwaySegments": 0,
                "highAirwaySegments": 0
            },
            "dataSources": [
                {
                    "dataset": name,
                    **metadata,
                    "recordCount": counts[name]
                }
                for name, metadata in sources.items()
            ],
            "capabilities": {
                "airports": True,
                "airlineProfiles": True,
                "rosterClassificationRules": True,
                "runways": True,
                "navaids": True,
                "vor": sum(navaid_type_counts.get(t, 0) for t in ("VOR", "VOR-DME", "VORTAC")) > 0,
                "dme": sum(navaid_type_counts.get(t, 0) for t in ("DME", "NDB-DME", "TACAN", "VOR-DME", "VORTAC")) > 0,
                "ndb": sum(navaid_type_counts.get(t, 0) for t in ("NDB", "NDB-DME")) > 0,
                "tacan": sum(navaid_type_counts.get(t, 0) for t in ("TACAN", "VORTAC")) > 0,
                "ilsFacilities": False,
                "independentWaypoints": False,
                "publishedAirways": False,
                "sids": False,
                "stars": False,
                "ilsApproaches": False,
                "rnavApproaches": False,
                "approaches": False
            }
        }

        manifest_path = stage / "navigation_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8"
        )

        # Publish only after every dataset has passed validation.
        destinations = [
            "navigation/airports/ourairports_airports.csv",
            "navigation/navaids/navaids.csv",
            "navigation/runways/runways_parsed.csv",
            "navigation/sources/airports.csv",
            "navigation/sources/navaids.csv",
            "navigation/sources/runways.csv",
            "navigation_manifest.json"
        ]

        backups = temp / "backups"
        backups.mkdir()
        installed = []

        try:
            for relative in destinations:
                source = stage / relative
                destination = ROOT / relative

                destination.parent.mkdir(
                    parents=True,
                    exist_ok=True
                )

                backup = backups / relative

                if destination.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup)

                os.replace(source, destination)
                installed.append((destination, backup))

        except Exception:
            for destination, backup in reversed(installed):
                if backup.exists():
                    shutil.copy2(backup, destination)
                elif destination.exists():
                    destination.unlink()
            raise

        log("Database successfully installed")
        log(json.dumps(counts, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        log(f"BUILD FAILED: {error}")
        raise
