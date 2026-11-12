#!/usr/bin/env python3
"""
FlightTempo Master IFR Aviation Database Builder (Schema v12)
Fetches, normalizes, and packages:
- Airports & Runways (OurAirports)
- Navaids: VOR, DME, NDB (OurAirports)
- IFR Fixes & Waypoints (FlightGear / X-Plane)
- Low & High Airways (FlightGear / X-Plane)
"""

import csv
import datetime
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_BASE = "https://davidmegginson.github.io/ourairports-data"

AIRPORTS_URL = f"{SOURCE_BASE}/airports.csv"
RUNWAYS_URL = f"{SOURCE_BASE}/runways.csv"
NAVAIDS_URL = f"{SOURCE_BASE}/navaids.csv"

AWY_URLS = [
    "https://raw.githubusercontent.com/FGMEMBERS-SCENERY/Navaids/master/awy.dat.gz",
    "https://gitlab.com/flightgear/fgdata/-/raw/release/2024.1/Navaids/awy.dat.gz",
]
FIX_URLS = [
    "https://raw.githubusercontent.com/FGMEMBERS-SCENERY/Navaids/master/fix.dat.gz",
    "https://gitlab.com/flightgear/fgdata/-/raw/release/2024.1/Navaids/fix.dat.gz",
]

USER_AGENT = "FlightTempo-Aviation-Database/12.0"


def log(message):
    print(f"[FlightTempo] {message}", flush=True)


def download(url, timeout=90):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP error {response.status}: {url}")
        return response.read()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def valid_coordinates(lat, lon):
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180


def write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def parse_xplane_header(lines):
    spec_version = "1100"
    data_cycle = "unknown"
    for line in lines[:5]:
        s = line.strip()
        m = re.search(r"data cycle\s+([0-9.]+)", s, re.IGNORECASE)
        if m:
            data_cycle = m.group(1)
        if re.match(r"^\d{3,4}\s+Version", s, re.IGNORECASE):
            spec_version = s.split()[0]
    return spec_version, data_cycle


def build_airports(records, stage):
    rows = []
    seen = set()
    for record in records:
        if record.get("type") == "closed_airport":
            continue
        ident = (record.get("icao_code") or record.get("ident") or "").strip().upper()
        if not ident or ident in seen:
            continue
        try:
            lat = float(record.get("latitude_deg"))
            lon = float(record.get("longitude_deg"))
            elevation = float(record.get("elevation_ft") or 0)
        except (ValueError, TypeError):
            continue

        if not valid_coordinates(lat, lon):
            continue
        seen.add(ident)
        rows.append((
            ident,
            (record.get("iso_country") or "").strip().upper(),
            round(lat, 5),
            round(lon, 5),
            round(elevation),
            (record.get("name") or "").strip()
        ))

    rows.sort(key=lambda row: row[0])
    write_csv(
        stage / "app/src/main/assets/airports.csv",
        ["icao", "country", "latitude", "longitude", "elevation_ft", "name"],
        rows
    )
    return len(rows)


def build_navaids(records, stage):
    rows = []
    seen = set()
    type_counts = {}

    for record in records:
        ident = (record.get("ident") or "").strip().upper()
        nav_type = (record.get("type") or "").strip().upper()
        try:
            lat = float(record.get("latitude_deg"))
            lon = float(record.get("longitude_deg"))
        except (ValueError, TypeError):
            continue

        if not ident or not nav_type or not valid_coordinates(lat, lon):
            continue

        key = (ident, nav_type, round(lat, 6), round(lon, 6))
        if key in seen:
            continue
        seen.add(key)

        try:
            freq_khz = float(record.get("frequency_khz")) if record.get("frequency_khz") else None
        except ValueError:
            freq_khz = None

        rows.append((
            ident,
            (record.get("name") or "").strip(),
            nav_type,
            round(freq_khz, 3) if freq_khz is not None else "",
            round(freq_khz / 1000, 6) if freq_khz is not None else "",
            round(lat, 6),
            round(lon, 6),
            (record.get("iso_country") or "").upper(),
            (record.get("associated_airport") or "").strip().upper()
        ))
        type_counts[nav_type] = type_counts.get(nav_type, 0) + 1

    rows.sort(key=lambda row: (row[0], row[2]))
    write_csv(
        stage / "navigation/navaids/navaids.csv",
        ["ident", "name", "type", "frequency_khz", "frequency_mhz", "latitude_deg", "longitude_deg", "iso_country", "associated_airport"],
        rows
    )
    return len(rows), dict(sorted(type_counts.items()))


def build_runways(records, stage):
    rows = []
    seen = set()
    for record in records:
        if str(record.get("closed", "")).strip() == "1":
            continue
        airport = (record.get("airport_ident") or "").strip().upper()
        low = (record.get("le_ident") or "").strip().upper()
        high = (record.get("he_ident") or "").strip().upper()
        if not airport or not low:
            continue

        try:
            length = float(record.get("length_ft") or 0)
            width = float(record.get("width_ft") or 0)
        except ValueError:
            length, width = 0, 0

        key = (airport, low, high)
        if key in seen:
            continue
        seen.add(key)

        rows.append((
            airport,
            f"{low}/{high}" if high else low,
            low,
            high,
            round(length),
            round(width),
            (record.get("surface") or "").strip(),
            "1" if str(record.get("lighted", "")) == "1" else "0"
        ))

    rows.sort(key=lambda row: (row[0], row[1]))
    write_csv(
        stage / "navigation/runways/runways_parsed.csv",
        ["airport_icao", "runway_pair", "le_ident", "he_ident", "length_ft", "width_ft", "surface", "lighted"],
        rows
    )
    return len(rows)


def build_airways_and_waypoints(stage):
    log("Downloading FlightGear en-route fix and airway data...")
    fix_raw, awy_raw = None, None

    for url in FIX_URLS:
        try:
            fix_raw = download(url, timeout=45)
            break
        except Exception:
            continue

    for url in AWY_URLS:
        try:
            awy_raw = download(url, timeout=45)
            break
        except Exception:
            continue

    fixes = {}
    if fix_raw:
        fix_text = gzip.decompress(fix_raw).decode("latin-1", errors="ignore")
        for line in fix_text.splitlines():
            parts = line.strip().split()
            if len(parts) >= 3:
                try:
                    lat, lon = float(parts[0]), float(parts[1])
                    fix_id = parts[2].strip().upper()
                    region = parts[4].strip().upper() if len(parts) >= 5 else "IFR"
                    if valid_coordinates(lat, lon) and len(fix_id) <= 5:
                        fixes[fix_id] = (fix_id, round(lat, 5), round(lon, 5), region)
                except ValueError:
                    continue

    low_segments, high_segments = [], []
    cycle = "unknown"
    spec_ver = "1100"

    if awy_raw:
        awy_text = gzip.decompress(awy_raw).decode("latin-1", errors="ignore")
        awy_lines = awy_text.splitlines()
        spec_ver, cycle = parse_xplane_header(awy_lines)

        for line in awy_lines[2:]:
            s = line.strip()
            if not s or s == "99":
                continue
            parts = s.split()
            if len(parts) >= 10:
                try:
                    f1, lat1, lon1 = parts[0].upper(), float(parts[1]), float(parts[2])
                    f2, lat2, lon2 = parts[3].upper(), float(parts[4]), float(parts[5])
                    dir_code, layer_code = parts[6], parts[7]
                    base_fl, top_fl = int(float(parts[8])), int(float(parts[9]))

                    desigs = []
                    if len(parts) > 10:
                        for token in parts[10:]:
                            for d in token.split("-"):
                                if d.strip() and d.strip() != "99":
                                    desigs.append(d.strip().upper())

                    if f1 not in fixes: fixes[f1] = (f1, round(lat1, 5), round(lon1, 5), "IFR")
                    if f2 not in fixes: fixes[f2] = (f2, round(lat2, 5), round(lon2, 5), "IFR")

                    row = (desigs[0] if desigs else "UNKNOWN", f1, round(lat1, 5), round(lon1, 5), f2, round(lat2, 5), round(lon2, 5), "F" if dir_code == "1" else "B", base_fl * 100, top_fl * 100)
                    if layer_code == "2":
                        high_segments.append(row)
                    else:
                        low_segments.append(row)
                except ValueError:
                    continue

    # Write Waypoints
    write_csv(stage / "navigation/waypoints/waypoints.csv", ["id", "latitude", "longitude", "region"], sorted(fixes.values(), key=lambda x: x[0]))
    # Write Low Airways
    write_csv(stage / "navigation/airways/low_airways.csv", ["airway_id", "from_fix", "from_lat", "from_lon", "to_fix", "to_lat", "to_lon", "dir", "min_alt_ft", "max_alt_ft"], low_segments)
    # Write High Airways
    write_csv(stage / "navigation/airways/high_airways.csv", ["airway_id", "from_fix", "from_lat", "from_lon", "to_fix", "to_lat", "to_lon", "dir", "min_alt_ft", "max_alt_ft"], high_segments)

    return len(fixes), len(low_segments), len(high_segments), cycle


def main():
    timestamp = datetime.now(timezone.utc).isoformat()
    log("Starting master IFR database compilation...")

    with tempfile.TemporaryDirectory(prefix="flighttempo-") as temp_dir:
        stage = Path(temp_dir) / "staging"
        stage.mkdir()

        # Download base data
        airports_raw = download(AIRPORTS_URL)
        runways_raw = download(RUNWAYS_URL)
        navaids_raw = download(NAVAIDS_URL)

        airports = list(csv.DictReader(io.StringIO(airports_raw.decode("utf-8-sig"))))
        runways = list(csv.DictReader(io.StringIO(runways_raw.decode("utf-8-sig"))))
        navaids = list(csv.DictReader(io.StringIO(navaids_raw.decode("utf-8-sig"))))

        airport_count = build_airports(airports, stage)
        runway_count = build_runways(runways, stage)
        navaid_count, navaid_types = build_navaids(navaids, stage)
        fix_count, low_awy, high_awy, cycle = build_airways_and_waypoints(stage)

        manifest = {
            "schemaVersion": 12,
            "generatedAtUtc": timestamp,
            "procedureAiracCycle": cycle,
            "navaidTypeCounts": navaid_types,
            "statistics": {
                "airports": airport_count,
                "runways": runway_count,
                "navaids": navaid_count,
                "ifrWaypoints": fix_count,
                "lowAirwaySegments": low_awy,
                "highAirwaySegments": high_awy,
            },
            "capabilities": {
                "airports": True,
                "runways": True,
                "navaids": True,
                "independentWaypoints": True,
                "publishedAirways": True,
            }
        }

        (stage / "navigation_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # Install files securely into root repository
        destinations = [
            "app/src/main/assets/airports.csv",
            "navigation/runways/runways_parsed.csv",
            "navigation/navaids/navaids.csv",
            "navigation/waypoints/waypoints.csv",
            "navigation/airways/low_airways.csv",
            "navigation/airways/high_airways.csv",
            "navigation_manifest.json"
        ]

        for rel in destinations:
            src = stage / rel
            dest = ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                shutil.copy2(src, dest)

        log("Master database build and folder organization completed successfully!")


if __name__ == "__main__":
    main()
