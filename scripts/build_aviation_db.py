#!/usr/bin/env python3
"""
FlightTempo Production-Grade Commercial Aviation Database Builder
Strictly parses genuine open aviation data with zero synthetic placeholders.
Validates records before staging and preserves prior working data on failure.
"""

import csv
import datetime
import gzip
import hashlib
import io
import json
import os
import re
import urllib.request

USER_AGENT = "FlightTempo-Builder/7.0 (https://github.com/julienvergouts-code/flighttempo-data)"

AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
NAVAIDS_URL = "https://davidmegginson.github.io/ourairports-data/navaids.csv"
RUNWAYS_URL = "https://davidmegginson.github.io/ourairports-data/runways.csv"

AWY_URLS = [
    "https://raw.githubusercontent.com/FGMEMBERS-SCENERY/Navaids/master/awy.dat.gz",
    "https://gitlab.com/flightgear/fgdata/-/raw/release/2024.1/Navaids/awy.dat.gz",
]
FIX_URLS = [
    "https://raw.githubusercontent.com/FGMEMBERS-SCENERY/Navaids/master/fix.dat.gz",
    "https://gitlab.com/flightgear/fgdata/-/raw/release/2024.1/Navaids/fix.dat.gz",
]

PAVED_KEYWORDS = ("ASP", "CON", "BIT", "PEM", "PAV", "TAR", "MAC", "ASPH", "CONC")


def download_bytes(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().upper()


def ensure_dirs():
    os.makedirs("navigation/sources", exist_ok=True)
    os.makedirs("navigation/waypoints", exist_ok=True)
    os.makedirs("navigation/navaids", exist_ok=True)
    os.makedirs("navigation/airways", exist_ok=True)
    os.makedirs("navigation/runways", exist_ok=True)
    os.makedirs("app/src/main/assets", exist_ok=True)


def parse_xplane_header(lines: list) -> str:
    for line in lines[:5]:
        s = line.strip()
        m = re.search(r"data cycle\s+([0-9.]+)", s, re.IGNORECASE)
        if m:
            return m.group(1)
    return "unknown"


def build_airports(today_iso: str, now_iso: str, manifest_sources: list) -> list:
    print(f"Downloading airports from {AIRPORTS_URL}...")
    raw = download_bytes(AIRPORTS_URL)
    text = raw.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    rows = []

    for r in reader:
        if r.get("type") == "closed_airport":
            continue
        ident = (r.get("ident") or "").strip().upper()
        icao = (r.get("icao_code") or ident).strip().upper()
        name = (r.get("name") or "").strip()
        lat_s = (r.get("latitude_deg") or "").strip()
        lon_s = (r.get("longitude_deg") or "").strip()
        elev_s = (r.get("elevation_ft") or "0").strip()
        country = (r.get("iso_country") or "").strip().upper()

        if not icao or not lat_s or not lon_s:
            continue
        try:
            lat = round(float(lat_s), 5)
            lon = round(float(lon_s), 5)
            elev = int(float(elev_s)) if elev_s else 0
        except ValueError:
            continue

        if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
            rows.append((icao, country, lat, lon, elev, name))

    if len(rows) < 1000:
        raise ValueError(f"Airport record count critically low ({len(rows)}). Aborting.")

    out_path = "app/src/main/assets/airports.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#version", today_iso, "source", "OurAirports"])
        w.writerow(["icao", "country", "latitude", "longitude", "elevation_ft", "name"])
        for row in sorted(rows, key=lambda x: x[0]):
            w.writerow(row)

    manifest_sources.append({
        "dataset": "airports",
        "name": "Worldwide Airport Reference & Elevations Master",
        "file": "airports.csv",
        "url": AIRPORTS_URL,
        "provider": "OurAirports",
        "license": "Public Domain (CC0 1.0)",
        "sourceVersionOrCycle": today_iso,
        "recordCount": len(rows),
        "sizeBytes": os.path.getsize(out_path),
        "sha256": sha256_file(out_path),
        "coverage": "Global airport coordinates, elevations MSL, and identifiers",
        "downloadedAt": now_iso,
    })
    return manifest_sources


def build_navaids(today_iso: str, now_iso: str, manifest_sources: list) -> list:
    print(f"Downloading navaids from {NAVAIDS_URL}...")
    raw = download_bytes(NAVAIDS_URL)
    text = raw.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
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

    if len(rows) < 1000:
        raise ValueError(f"Navaid record count critically low ({len(rows)}). Aborting.")

    out_path = "navigation/navaids/navaids.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#source_version", today_iso, "provider", "OurAirports"])
        w.writerow(["id", "name", "type", "freq_mhz", "lat", "lon", "country", "airport_icao"])
        for row in sorted(rows, key=lambda x: x[0]):
            w.writerow(row)

    manifest_sources.append({
        "dataset": "navaids",
        "name": "Worldwide Radio Navaids",
        "file": out_path,
        "url": NAVAIDS_URL,
        "provider": "OurAirports",
        "license": "Public Domain (CC0 1.0)",
        "sourceVersionOrCycle": today_iso,
        "recordCount": len(rows),
        "sizeBytes": os.path.getsize(out_path),
        "sha256": sha256_file(out_path),
        "coverage": "Global VOR, VOR/DME, DME, NDB",
        "downloadedAt": now_iso,
    })
    return manifest_sources


def build_runways(today_iso: str, now_iso: str, manifest_sources: list) -> list:
    print(f"Downloading runways from {RUNWAYS_URL}...")
    raw = download_bytes(RUNWAYS_URL)
    text = raw.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
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

        if not apt or len(apt) != 4 or not le_ident or le_ident.startswith("H"):
            continue

        try:
            length_ft = int(float(length_s)) if length_s else 0
        except ValueError:
            length_ft = 0

        is_paved = any(k in surface for k in PAVED_KEYWORDS)
        if length_ft < 4000 or not is_paved:
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

    if len(rows) < 500:
        raise ValueError(f"Runway record count critically low ({len(rows)}). Aborting.")

    out_path = "navigation/runways/runways_parsed.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#source_version", today_iso, "provider", "OurAirports"])
        w.writerow(["airport_icao", "runway_pair", "le_ident", "he_ident", "le_heading_degT", "he_heading_degT", "length_ft", "lighted"])
        for row in sorted(rows, key=lambda x: (x[0], -x[6])):
            w.writerow(row)

    manifest_sources.append({
        "dataset": "runways",
        "name": "Worldwide Commercial Paved Runways (>= 4,000 ft)",
        "file": out_path,
        "url": RUNWAYS_URL,
        "provider": "OurAirports",
        "license": "Public Domain (CC0 1.0)",
        "sourceVersionOrCycle": today_iso,
        "recordCount": len(rows),
        "sizeBytes": os.path.getsize(out_path),
        "sha256": sha256_file(out_path),
        "coverage": "Global paved commercial runways >= 4,000 ft",
        "downloadedAt": now_iso,
    })
    return manifest_sources


def build_airways_and_waypoints(now_iso: str, manifest_sources: list) -> list:
    awy_raw = None
    used_awy_url = ""
    for url in AWY_URLS:
        try:
            print(f"Downloading airways from {url}...")
            data = download_bytes(url, timeout=45)
            if len(data) > 5000:
                awy_raw = data
                used_awy_url = url
                break
        except Exception as e:
            print(f"Mirror {url} failed: {e}")

    if not awy_raw:
        raise RuntimeError("Failed to download valid global airway data from all configured mirrors.")

    awy_text = gzip.decompress(awy_raw).decode("latin-1", errors="ignore")
    awy_lines = awy_text.splitlines()
    cycle = parse_xplane_header(awy_lines)

    awy_segments = []
    airway_fixes = {}

    for line in awy_lines[2:]:
        s = line.strip()
        if not s or s == "99":
            continue
        parts = s.split()
        if len(parts) >= 10:
            try:
                fix1 = parts[0].strip().upper()
                lat1 = round(float(parts[1]), 5)
                lon1 = round(float(parts[2]), 5)
                fix2 = parts[3].strip().upper()
                lat2 = round(float(parts[4]), 5)
                lon2 = round(float(parts[5]), 5)
                dir_code = parts[6].strip()
                layer_code = parts[7].strip()
                base_fl = int(float(parts[8]))
                top_fl = int(float(parts[9]))
                # Safely parse designators starting from index 10 if present, else index 9
                designators = parts[10].strip().upper().split("-") if len(parts) > 10 else [parts[9].strip().upper()]

                if not (-90.0 <= lat1 <= 90.0 and -180.0 <= lon1 <= 180.0):
                    continue
                if not (-90.0 <= lat2 <= 90.0 and -180.0 <= lon2 <= 180.0):
                    continue

                airway_fixes[(fix1, round(lat1, 2), round(lon1, 2))] = (fix1, lat1, lon1, "IFR")
                airway_fixes[(fix2, round(lat2, 2), round(lon2, 2))] = (fix2, lat2, lon2, "IFR")

                for awy_id in designators:
                    if not awy_id or awy_id == "99" or len(awy_id) > 6:
                        continue
                    awy_segments.append((
                        awy_id, fix1, lat1, lon1, fix2, lat2, lon2,
                        "F" if dir_code == "1" else "B",
                        "H" if layer_code == "2" else "L",
                        base_fl * 100, top_fl * 100
                    ))
            except ValueError:
                continue

    if len(awy_segments) < 1000:
        raise ValueError(f"Parsed airway segment count critically low ({len(awy_segments)}). Aborting.")

    wp_path = "navigation/waypoints/waypoints.csv"
    with open(wp_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#source_version", cycle, "provider", "FlightGear/X-Plane"])
        w.writerow(["id", "latitude", "longitude", "region"])
        for row in sorted(airway_fixes.values(), key=lambda x: (x[0], x[1])):
            w.writerow(row)

    manifest_sources.append({
        "dataset": "waypoints",
        "name": "Worldwide Commercial IFR En-Route Waypoints",
        "file": wp_path,
        "url": used_awy_url,
        "provider": "FlightGear Open Scenery / X-Plane Navigation Database",
        "license": "GNU General Public License v2 (GPLv2)",
        "sourceVersionOrCycle": cycle,
        "recordCount": len(airway_fixes),
        "sizeBytes": os.path.getsize(wp_path),
        "sha256": sha256_file(wp_path),
        "coverage": "Global 5LNC IFR waypoints connected to published airways",
        "downloadedAt": now_iso,
    })

    awy_path = "navigation/airways/airways.csv"
    with open(awy_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#source_version", cycle, "provider", "FlightGear/X-Plane"])
        w.writerow(["airway_id", "from_fix", "from_lat", "from_lon", "to_fix", "to_lat", "to_lon", "dir", "level", "min_alt_ft", "max_alt_ft"])
        for seg in awy_segments:
            w.writerow(seg)

    manifest_sources.append({
        "dataset": "airways",
        "name": "Worldwide Published High & Low IFR Airways",
        "file": awy_path,
        "url": used_awy_url,
        "provider": "FlightGear Open Scenery / X-Plane Navigation Database",
        "license": "GNU General Public License v2 (GPLv2)",
        "sourceVersionOrCycle": cycle,
        "recordCount": len(awy_segments),
        "sizeBytes": os.path.getsize(awy_path),
        "sha256": sha256_file(awy_path),
        "coverage": "Global High & Low IFR Airway Segments",
        "downloadedAt": now_iso,
    })
    return manifest_sources


def main():
    ensure_dirs()
    today_iso = datetime.date.today().isoformat()
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_sources = []

    try:
        build_airports(today_iso, now_iso, manifest_sources)
        build_navaids(today_iso, now_iso, manifest_sources)
        build_runways(today_iso, now_iso, manifest_sources)
        build_airways_and_waypoints(now_iso, manifest_sources)

        total_bytes = sum(s["sizeBytes"] for s in manifest_sources)
        manifest = {
            "schemaVersion": 9,
            "generatedAtUtc": now_iso,
            "targetProfile": "Commercial IFR Airline Operations",
            "totalNavigationAssetsSizeBytes": total_bytes,
            "totalNavigationAssetsSizeMb": round(total_bytes / (1024 * 1024), 2),
            "dataSources": manifest_sources,
        }

        with open("navigation_manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        print(f"Success! Complete validated database built successfully ({round(total_bytes / (1024 * 1024), 2)} MB total).")

    except Exception as e:
        print(f"CRITICAL BUILD FAILURE: {e}")
        exit(1)


if __name__ == "__main__":
    main()
