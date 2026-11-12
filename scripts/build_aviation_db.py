#!/usr/bin/env python3
"""
FlightTempo Ultra-Lightweight Global Aviation Builder (< 2 MB Total)
Designed specifically for fast mobile offline performance:
1. Compact Worldwide Paved Runways >= 2,500 ft (~450 KB, OurAirports CC0)
2. Compact Worldwide VOR / DME / NDB Navaids (~650 KB, OurAirports CC0)
3. Deduplicated Commercial Airline City-Pair Connections (~300 KB, OpenFlights ODbL)
Removes all multi-megabyte raw source duplicates so the Android APK stays tiny and fast.
"""

import csv
import datetime
import hashlib
import io
import json
import os
import shutil
import urllib.request

USER_AGENT = "FlightTempo-Lightweight-Builder/4.0 (https://github.com/julienvergouts-code/flighttempo-data)"

NAVAIDS_URL = "https://davidmegginson.github.io/ourairports-data/navaids.csv"
RUNWAYS_URL = "https://davidmegginson.github.io/ourairports-data/runways.csv"
ROUTES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"

PAVED_KEYWORDS = ("ASP", "CON", "BIT", "PEM", "PAV", "TAR", "MAC", "ASPH", "CONC")


def download_text(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().upper()


def clean_heavy_files():
    """Deletes any bloated raw files or empty folders from previous runs."""
    for folder in ["navigation/sources", "navigation/waypoints", "navigation/airways", "procedures"]:
        if os.path.exists(folder):
            shutil.rmtree(folder, ignore_errors=True)
    for old_file in ["navigation/airline_routes/routes.dat"]:
        if os.path.exists(old_file):
            os.remove(old_file)

    for d in [
        "navigation/navaids",
        "navigation/runways",
        "navigation/airline_routes",
    ]:
        os.makedirs(d, exist_ok=True)


def build_compact_navaids(today_iso: str, now_iso: str, manifest_sources: list):
    print("Downloading & compacting OurAirports Navaids...")
    raw_text = download_text(NAVAIDS_URL)
    reader = csv.DictReader(io.StringIO(raw_text))
    rows = []

    for r in reader:
        ident = (r.get("ident") or "").strip().upper()
        name = (r.get("name") or "").strip()
        nav_type = (r.get("type") or "").strip().upper()
        lat_s = (r.get("latitude_deg") or "").strip()
        lon_s = (r.get("longitude_deg") or "").strip()
        freq_khz = (r.get("frequency_khz") or "").strip()
        country = (r.get("iso_country") or "").strip().upper()
        apt = (r.get("associated_airport") or "").strip().upper()

        if not ident or not lat_s or not lon_s:
            continue
        try:
            lat = round(float(lat_s), 5)
            lon = round(float(lon_s), 5)
            freq_mhz = round(float(freq_khz) / 1000.0, 3) if freq_khz else ""
        except ValueError:
            continue

        if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
            rows.append((ident, name, nav_type, freq_mhz, lat, lon, country, apt))

    out_path = "navigation/navaids/navaids.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#source_version", today_iso, "provider", "OurAirports"])
        w.writerow(["id", "name", "type", "freq_mhz", "lat", "lon", "country", "airport_icao"])
        for row in rows:
            w.writerow(row)

    manifest_sources.append({
        "dataset": "navaids",
        "name": "Worldwide VOR, VOR/DME, DME & NDB Navaids (Compact)",
        "file": out_path,
        "url": NAVAIDS_URL,
        "provider": "OurAirports",
        "license": "Public Domain (CC0 1.0)",
        "sourceVersionOrCycle": today_iso,
        "recordCount": len(rows),
        "sizeBytes": os.path.getsize(out_path),
        "sha256": sha256_file(out_path),
        "coverage": "Global Radio Navigation Aids",
        "downloadedAt": now_iso,
    })


def build_compact_runways(today_iso: str, now_iso: str, manifest_sources: list):
    print("Downloading & compacting OurAirports Runways...")
    raw_text = download_text(RUNWAYS_URL)
    reader = csv.DictReader(io.StringIO(raw_text))
    rows = []

    for r in reader:
        if r.get("closed") == "1":
            continue
        apt = (r.get("airport_ident") or "").strip().upper()
        le_ident = (r.get("le_ident") or "").strip().upper()
        he_ident = (r.get("he_ident") or "").strip().upper()
        length_s = (r.get("length_ft") or "").strip()
        surface = (r.get("surface") or "").strip().upper()
        lighted = "1" if r.get("lighted") == "1" else "0"
        le_hdg_s = (r.get("le_heading_degT") or "").strip()
        he_hdg_s = (r.get("he_heading_degT") or "").strip()

        if not apt or len(apt) < 3 or not le_ident:
            continue
        # Skip helipads ("H1")
        if le_ident.startswith("H"):
            continue

        try:
            length_ft = int(float(length_s)) if length_s else 0
        except ValueError:
            length_ft = 0

        # Keep runways >= 2,200 ft (or any lighted/paved commercial/training runway)
        is_paved = any(k in surface for k in PAVED_KEYWORDS)
        if length_ft < 2200 and not is_paved:
            continue

        try:
            le_hdg = round(float(le_hdg_s), 1) if le_hdg_s else ""
        except ValueError:
            le_hdg = ""
        try:
            he_hdg = round(float(he_hdg_s), 1) if he_hdg_s else ""
        except ValueError:
            he_hdg = ""

        pair = f"{le_ident}/{he_ident}" if he_ident else le_ident
        rows.append((apt, pair, le_ident, he_ident, le_hdg, he_hdg, length_ft, lighted))

    out_path = "navigation/runways/runways_parsed.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#source_version", today_iso, "provider", "OurAirports"])
        w.writerow(["airport_icao", "runway_pair", "le_ident", "he_ident", "le_heading_degT", "he_heading_degT", "length_ft", "lighted"])
        for row in sorted(rows, key=lambda x: (x[0], -x[6])):
            w.writerow(row)

    manifest_sources.append({
        "dataset": "runways",
        "name": "Worldwide Operational Runways (Compact)",
        "file": out_path,
        "url": RUNWAYS_URL,
        "provider": "OurAirports",
        "license": "Public Domain (CC0 1.0)",
        "sourceVersionOrCycle": today_iso,
        "recordCount": len(rows),
        "sizeBytes": os.path.getsize(out_path),
        "sha256": sha256_file(out_path),
        "coverage": "Global operational runways >= 2,200 ft (headings, lengths, lighting)",
        "downloadedAt": now_iso,
    })


def build_compact_airline_routes(today_iso: str, now_iso: str, manifest_sources: list):
    print("Downloading & deduplicating OpenFlights Airline Connections...")
    raw_text = download_text(ROUTES_URL)
    pair_airlines = {}

    for line in raw_text.splitlines():
        parts = line.strip().split(",")
        # OpenFlights routes.dat: 0:airline, 1:id, 2:src_iata, 3:src_id, 4:dst_iata, 5:dst_id
        if len(parts) >= 5:
            airline = parts[0].strip().upper()
            dep = parts[2].strip().upper()
            arr = parts[4].strip().upper()
            if len(dep) in (3, 4) and len(arr) in (3, 4) and dep != arr:
                key = (dep, arr)
                if key not in pair_airlines:
                    pair_airlines[key] = set()
                if airline and airline != "\\N":
                    pair_airlines[key].add(airline)

    out_path = "navigation/airline_routes/airline_routes.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#source_version", today_iso, "provider", "OpenFlights"])
        w.writerow(["dep_code", "arr_code", "operators"])
        for (dep, arr), ops in sorted(pair_airlines.items()):
            w.writerow([dep, arr, "|".join(sorted(list(ops))[:8])])

    manifest_sources.append({
        "dataset": "airline_routes",
        "name": "Deduplicated Commercial City-Pair Connections",
        "file": out_path,
        "url": ROUTES_URL,
        "provider": "OpenFlights",
        "license": "Open Database License (ODbL 1.0)",
        "sourceVersionOrCycle": today_iso,
        "recordCount": len(pair_airlines),
        "sizeBytes": os.path.getsize(out_path),
        "sha256": sha256_file(out_path),
        "coverage": "Global commercial city pairs and operating airline codes",
        "downloadedAt": now_iso,
    })


def main():
    clean_heavy_files()
    today_iso = datetime.date.today().isoformat()
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_sources = []

    build_compact_navaids(today_iso, now_iso, manifest_sources)
    build_compact_runways(today_iso, now_iso, manifest_sources)
    build_compact_airline_routes(today_iso, now_iso, manifest_sources)

    total_bytes = sum(s["sizeBytes"] for s in manifest_sources)
    manifest = {
        "schemaVersion": 6,
        "generatedAtUtc": now_iso,
        "totalNavigationAssetsSizeBytes": total_bytes,
        "totalNavigationAssetsSizeMb": round(total_bytes / (1024 * 1024), 2),
        "dataSources": manifest_sources,
    }

    with open("navigation_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Done! Total size of all navigation datasets: {round(total_bytes / (1024 * 1024), 2)} MB")


if __name__ == "__main__":
    main()
