#!/usr/bin/env python3
"""
FlightTempo Global Aviation Database Builder (Corrected Provenance Edition)
Strictly separates:
1. Airport & Physical Runway Data (OurAirports - Public Domain CC0)
2. Radio Navaids (OurAirports - Public Domain CC0)
3. En-Route Waypoints & Airway Segments (FlightGear fgdata - GNU GPLv2, actual upstream header cycle)
4. Commercial Airline Connections (OpenFlights - ODbL 1.0, for route discovery only)
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
import urllib.request

USER_AGENT = "FlightTempo-Data-Builder/3.2 (https://github.com/julienvergouts-code/flighttempo-data)"

LOCAL_FG_FIX = "/usr/share/games/flightgear/Navaids/fix.dat.gz"
LOCAL_FG_AWY = "/usr/share/games/flightgear/Navaids/awy.dat.gz"

FG_FIX_URLS = [
    "https://gitlab.com/flightgear/fgdata/-/raw/release/2024.1/Navaids/fix.dat.gz",
    "https://sourceforge.net/p/flightgear/fgdata/ci/next/tree/Navaids/fix.dat.gz?format=raw",
]
FG_AWY_URLS = [
    "https://gitlab.com/flightgear/fgdata/-/raw/release/2024.1/Navaids/awy.dat.gz",
    "https://sourceforge.net/p/flightgear/fgdata/ci/next/tree/Navaids/awy.dat.gz?format=raw",
]


def download_bytes(url: str, timeout: int = 90) -> bytes:
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
    for d in [
        "navigation/waypoints",
        "navigation/navaids",
        "navigation/airways",
        "navigation/runways",
        "navigation/airline_routes",
        "navigation/sources",
        "procedures/sids",
        "procedures/stars",
        "procedures/approaches",
        "procedures/source_data",
    ]:
        os.makedirs(d, exist_ok=True)


def extract_xp_header_metadata(lines: list) -> dict:
    spec_version = "unknown"
    data_cycle = "unknown"
    raw_header = ""
    for line in lines[:5]:
        s = line.strip()
        if not s or s in ("I", "A"):
            continue
        if re.match(r"^\d{3,4}\s+Version", s, re.IGNORECASE):
            raw_header = s
            parts = s.split()
            spec_version = parts[0]
            m = re.search(r"data cycle\s+([0-9.]+)", s, re.IGNORECASE)
            if m:
                data_cycle = m.group(1)
            break
    return {
        "specVersion": spec_version,
        "sourceDataCycle": data_cycle,
        "rawHeader": raw_header,
    }


def load_fg_file(local_path: str, urls: list):
    if os.path.exists(local_path):
        print(f"Loading local system package file: {local_path}")
        with open(local_path, "rb") as f:
            return f.read(), f"ubuntu:flightgear-data-base ({local_path})"
    for url in urls:
        try:
            print(f"Downloading from {url} ...")
            return download_bytes(url, timeout=120), url
        except Exception as e:
            print(f"Mirror failed ({url}): {e}")
    raise RuntimeError(f"Could not load {local_path} or any mirror URL")


def process_flightgear_navigation(manifest_sources: list):
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. En-Route Fixes (fix.dat.gz)
    fix_raw, used_fix_url = load_fg_file(LOCAL_FG_FIX, FG_FIX_URLS)
    with open("navigation/sources/fix.dat.gz", "wb") as f:
        f.write(fix_raw)

    try:
        text = gzip.decompress(fix_raw).decode("latin-1", errors="ignore")
    except Exception:
        text = fix_raw.decode("latin-1", errors="ignore")

    lines = text.splitlines()
    meta = extract_xp_header_metadata(lines)
    waypoints = []

    for line in lines[2:]:
        s = line.strip()
        if not s or s == "99":
            continue
        parts = s.split()
        if len(parts) >= 3:
            try:
                lat = float(parts[0])
                lon = float(parts[1])
                fix_id = parts[2].strip().upper()
                terminal_apt = parts[3].strip().upper() if len(parts) >= 4 else ""
                region = parts[4].strip().upper() if len(parts) >= 5 else ""
                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and 1 <= len(fix_id) <= 6:
                    waypoints.append((
                        fix_id,
                        round(lat, 6),
                        round(lon, 6),
                        terminal_apt,
                        region,
                        f"FG_FIX_{meta['sourceDataCycle']}",
                    ))
            except ValueError:
                continue

    wp_path = "navigation/waypoints/waypoints.csv"
    with open(wp_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#source_version", meta["sourceDataCycle"], "spec", meta["specVersion"]])
        w.writerow(["id", "latitude", "longitude", "terminal_airport", "icao_region", "source"])
        for row in waypoints:
            w.writerow(row)

    manifest_sources.append({
        "dataset": "waypoints",
        "name": "FlightGear / X-Plane Global En-Route Fixes",
        "file": wp_path,
        "originalSourceFile": "navigation/sources/fix.dat.gz",
        "url": used_fix_url,
        "provider": "FlightGear Open Scenery / X-Plane Robin Peel Navigation Database",
        "license": "GNU General Public License v2 (GPLv2)",
        "sourceVersionOrCycle": meta["sourceDataCycle"],
        "sourceHeader": meta["rawHeader"],
        "airacCycle": None,
        "recordCount": len(waypoints),
        "sizeBytes": os.path.getsize(wp_path),
        "sha256": sha256_file(wp_path),
        "coverage": "Global (Subject to source cycle coverage; not current operational AIRAC)",
        "downloadedAt": now_iso,
    })

    # 2. Published Airway Segments (awy.dat.gz)
    awy_raw, used_awy_url = load_fg_file(LOCAL_FG_AWY, FG_AWY_URLS)
    with open("navigation/sources/awy.dat.gz", "wb") as f:
        f.write(awy_raw)

    try:
        text = gzip.decompress(awy_raw).decode("latin-1", errors="ignore")
    except Exception:
        text = awy_raw.decode("latin-1", errors="ignore")

    lines = text.splitlines()
    meta = extract_xp_header_metadata(lines)
    awy_segments = []

    for line in lines[2:]:
        s = line.strip()
        if not s or s == "99":
            continue
        parts = s.split()
        if len(parts) >= 10:
            try:
                fix1 = parts[0].strip().upper()
                lat1 = round(float(parts[1]), 6)
                lon1 = round(float(parts[2]), 6)
                fix2 = parts[3].strip().upper()
                lat2 = round(float(parts[4]), 6)
                lon2 = round(float(parts[5]), 6)
                dir_code = parts[6].strip()
                layer_code = parts[7].strip()
                base_fl = int(float(parts[8]))
                top_fl = int(float(parts[9]))
                designators = parts[9 if len(parts) == 10 else 10].strip().upper().split("-")

                if not (-90.0 <= lat1 <= 90.0 and -180.0 <= lon1 <= 180.0):
                    continue
                if not (-90.0 <= lat2 <= 90.0 and -180.0 <= lon2 <= 180.0):
                    continue

                direction = "FORWARD_ONLY" if dir_code == "1" else "BIDIRECTIONAL"
                level = "HIGH" if layer_code == "2" else "LOW"

                for awy_id in designators:
                    if not awy_id or awy_id == "99":
                        continue
                    awy_segments.append((
                        awy_id,
                        fix1, lat1, lon1,
                        fix2, lat2, lon2,
                        direction,
                        level,
                        base_fl * 100,
                        top_fl * 100,
                        f"FG_AWY_{meta['sourceDataCycle']}",
                    ))
            except ValueError:
                continue

    awy_path = "navigation/airways/airways.csv"
    with open(awy_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#source_version", meta["sourceDataCycle"], "spec", meta["specVersion"]])
        w.writerow([
            "airway_id", "from_fix", "from_lat", "from_lon",
            "to_fix", "to_lat", "to_lon", "direction_restriction",
            "airspace_layer", "base_alt_ft", "top_alt_ft", "source"
        ])
        for seg in awy_segments:
            w.writerow(seg)

    manifest_sources.append({
        "dataset": "airways",
        "name": "FlightGear / X-Plane Global Airway Segments",
        "file": awy_path,
        "originalSourceFile": "navigation/sources/awy.dat.gz",
        "url": used_awy_url,
        "provider": "FlightGear Open Scenery / X-Plane Navigation Database",
        "license": "GNU General Public License v2 (GPLv2)",
        "sourceVersionOrCycle": meta["sourceDataCycle"],
        "sourceHeader": meta["rawHeader"],
        "airacCycle": None,
        "recordCount": len(awy_segments),
        "sizeBytes": os.path.getsize(awy_path),
        "sha256": sha256_file(awy_path),
        "coverage": "Global pairwise airway segments (Not operational current AIRAC)",
        "downloadedAt": now_iso,
    })


def build_factual_runways_table(runways_csv_bytes: bytes, manifest_sources: list):
    text = runways_csv_bytes.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    parsed_rows = []

    for row in reader:
        if row.get("closed") == "1":
            continue
        apt = (row.get("airport_ident") or "").strip().upper()
        length_ft_str = (row.get("length_ft") or "").strip()
        width_ft_str = (row.get("width_ft") or "").strip()
        surface = (row.get("surface") or "").strip().upper()
        lighted = (row.get("lighted") or "0").strip()
        le_ident = (row.get("le_ident") or "").strip().upper()
        he_ident = (row.get("he_ident") or "").strip().upper()
        le_hdg_str = (row.get("le_heading_degT") or "").strip()
        he_hdg_str = (row.get("he_heading_degT") or "").strip()
        le_lat_str = (row.get("le_latitude_deg") or "").strip()
        le_lon_str = (row.get("le_longitude_deg") or "").strip()
        he_lat_str = (row.get("he_latitude_deg") or "").strip()
        he_lon_str = (row.get("he_longitude_deg") or "").strip()

        if not apt or not le_ident:
            continue

        try:
            length_ft = int(float(length_ft_str)) if length_ft_str else 0
        except ValueError:
            length_ft = 0

        try:
            width_ft = int(float(width_ft_str)) if width_ft_str else 0
        except ValueError:
            width_ft = 0

        try:
            le_hdg = round(float(le_hdg_str), 1) if le_hdg_str else ""
        except ValueError:
            le_hdg = ""

        try:
            he_hdg = round(float(he_hdg_str), 1) if he_hdg_str else ""
        except ValueError:
            he_hdg = ""

        parsed_rows.append((
            apt,
            f"{le_ident}/{he_ident}" if he_ident else le_ident,
            le_ident,
            he_ident,
            le_hdg,
            he_hdg,
            length_ft,
            width_ft,
            surface,
            1 if lighted == "1" else 0,
            le_lat_str,
            le_lon_str,
            he_lat_str,
            he_lon_str,
            "OURAIRPORTS_CC0",
        ))

    out_path = "navigation/runways/runways_parsed.csv"
    today_iso = datetime.date.today().isoformat()
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#source_version", today_iso, "provider", "OurAirports"])
        w.writerow([
            "airport_icao", "runway_pair", "le_ident", "he_ident",
            "le_heading_degT", "he_heading_degT", "length_ft", "width_ft",
            "surface", "lighted", "le_lat", "le_lon", "he_lat", "he_lon", "source"
        ])
        for r in parsed_rows:
            w.writerow(r)

    manifest_sources.append({
        "dataset": "runways",
        "name": "OurAirports Factual Runway Geometry",
        "file": out_path,
        "originalSourceFile": "navigation/sources/runways.csv",
        "url": "https://davidmegginson.github.io/ourairports-data/runways.csv",
        "provider": "OurAirports",
        "license": "Public Domain (CC0 1.0)",
        "sourceVersionOrCycle": today_iso,
        "airacCycle": None,
        "recordCount": len(parsed_rows),
        "sizeBytes": os.path.getsize(out_path),
        "sha256": sha256_file(out_path),
        "coverage": "Global open-source airport runways (True headings, dimensions, coordinates)",
        "downloadedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })


def download_ourairports_and_openflights(manifest_sources: list):
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today_iso = datetime.date.today().isoformat()
    downloads = [
        (
            "navaids",
            "OurAirports Radio Navaids",
            "https://davidmegginson.github.io/ourairports-data/navaids.csv",
            "navigation/navaids/navaids.csv",
            "OurAirports",
            "Public Domain (CC0 1.0)",
            "Global community-maintained VOR, VOR/DME, DME, NDB, TACAN",
        ),
        (
            "runways_raw",
            "OurAirports Raw Runways & ILS",
            "https://davidmegginson.github.io/ourairports-data/runways.csv",
            "navigation/sources/runways.csv",
            "OurAirports",
            "Public Domain (CC0 1.0)",
            "Global community-maintained airport runways and thresholds",
        ),
        (
            "airline_routes",
            "OpenFlights Commercial Airline Connections (Route Discovery Only)",
            "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat",
            "navigation/airline_routes/routes.dat",
            "OpenFlights",
            "Open Database License (ODbL 1.0)",
            "Historical commercial airline airport-to-airport connections (NOT published airways)",
        ),
    ]

    for stale in [
        "navigation/airways/routes.dat",
        "procedures/sids/sids.csv",
        "procedures/stars/stars.csv",
        "procedures/approaches/approaches.csv",
    ]:
        if os.path.exists(stale):
            os.remove(stale)

    runways_bytes = None
    for ds_key, name, url, out_path, provider, lic, cov in downloads:
        print(f"Downloading {name} ...")
        data = download_bytes(url)
        if ds_key == "runways_raw":
            runways_bytes = data
        with open(out_path, "wb") as f:
            f.write(data)
        manifest_sources.append({
            "dataset": ds_key,
            "name": name,
            "file": out_path,
            "url": url,
            "provider": provider,
            "license": lic,
            "sourceVersionOrCycle": today_iso,
            "airacCycle": None,
            "recordCount": data.count(b"\n"),
            "sizeBytes": os.path.getsize(out_path),
            "sha256": sha256_file(out_path),
            "coverage": cov,
            "downloadedAt": now_iso,
        })

    if runways_bytes:
        build_factual_runways_table(runways_bytes, manifest_sources)


def main():
    ensure_dirs()
    manifest_sources = []

    download_ourairports_and_openflights(manifest_sources)
    process_flightgear_navigation(manifest_sources)

    manifest = {
        "schemaVersion": 5,
        "generatedAtUtc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "proceduresStatus": {
            "status": "UNAVAILABLE",
            "airacCycle": None,
            "note": "No redistributable global SID/STAR procedure source configured. Runway-aligned visual corridors are synthetic estimates, never published procedures."
        },
        "dataSources": manifest_sources,
    }

    with open("navigation_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print("Successfully built navigation_manifest.json with strict provenance.")


if __name__ == "__main__":
    main()
