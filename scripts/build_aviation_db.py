#!/usr/bin/env python3
"""
FlightTempo Automated Aviation Navigation & Airport Data Builder
Downloads and validates genuine public-domain datasets:
1. OurAirports (airports, runways, navaids) - Public Domain (CC0)
2. FAA Coded Instrument Flight Procedures (CIFP ARINC 424-18) - US Public Domain
3. OpenFlights Commercial Airline Route Connections (reclassified under airline_routes)
"""

import csv
import datetime
import hashlib
import io
import json
import os
import urllib.request
import zipfile

USER_AGENT = "FlightTempo-Data-Updater/1.0 (https://github.com/julienvergouts-code/flighttempo-data)"

# AIRAC epoch: Cycle 2601 effective 2026-01-22 (28-day cycle)
AIRAC_EPOCH = datetime.date(2026, 1, 22)


def get_active_airac(target_date: datetime.date = None):
    if target_date is None:
        target_date = datetime.date.today()
    days = (target_date - AIRAC_EPOCH).days
    idx = (days // 28)
    eff_date = AIRAC_EPOCH + datetime.timedelta(days=idx * 28)
    exp_date = eff_date + datetime.timedelta(days=27)
    year_short = eff_date.year % 100
    jan1 = datetime.date(eff_date.year, 1, 1)
    cycle_in_year = ((eff_date - jan1).days // 28) + 1
    cycle_id = f"{year_short:02d}{cycle_in_year:02d}"
    cifp_zip_name = f"CIFP_{eff_date.strftime('%y%m%d')}.zip"
    return {
        "cycleId": cycle_id,
        "effectiveDate": eff_date.isoformat(),
        "expiryDate": exp_date.isoformat(),
        "cifpZipName": cifp_zip_name,
        "cifpUrl": f"https://aeronav.faa.gov/Upload_313-d/cifp/{cifp_zip_name}",
    }


def download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().upper()


def parse_arinc_lat_lon(lat_str: str, lon_str: str):
    """Parses ARINC 424 DDMMSSssN / DDDMMSSssW coordinates into decimal degrees."""
    if len(lat_str) < 9 or len(lon_str) < 10:
        return None, None
    try:
        lat_hem = lat_str[0]
        lat_d = int(lat_str[1:3])
        lat_m = int(lat_str[3:5])
        lat_s = int(lat_str[5:9]) / 100.0
        lat = lat_d + (lat_m / 60.0) + (lat_s / 3600.0)
        if lat_hem == "S":
            lat = -lat

        lon_hem = lon_str[0]
        lon_d = int(lon_str[1:4])
        lon_m = int(lon_str[4:6])
        lon_s = int(lon_str[6:10]) / 100.0
        lon = lon_d + (lon_m / 60.0) + (lon_s / 3600.0)
        if lon_hem == "W":
            lon = -lon
        return round(lat, 6), round(lon, 6)
    except ValueError:
        return None, None


def ensure_dirs():
    dirs = [
        "navigation/waypoints",
        "navigation/navaids",
        "navigation/airways",
        "navigation/airline_routes",
        "navigation/sources",
        "procedures/sids",
        "procedures/stars",
        "procedures/approaches",
        "procedures/source_data",
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)


def process_faa_cifp(airac_info: dict, manifest_sources: list):
    url = airac_info["cifpUrl"]
    print(f"Downloading FAA CIFP from {url} ...")
    try:
        raw_zip = download_bytes(url)
    except Exception as e:
        print(f"WARNING: Could not download {url}: {e}")
        return False

    waypoints = {}
    airways = []
    sids = []
    stars = []
    approaches = []

    with zipfile.ZipFile(io.BytesIO(raw_zip), "r") as z:
        cifp_member = next((m for m in z.namelist() if "FAACIFP" in m.upper()), None)
        if not cifp_member:
            print("WARNING: FAACIFP18 not found inside CIFP zip.")
            return False

        with z.open(cifp_member) as raw_arinc:
            for raw_line in io.TextIOWrapper(raw_arinc, encoding="latin-1", errors="ignore"):
                if len(raw_line) < 120 or not raw_line.startswith("SUS"):
                    continue

                sec = raw_line[4]
                sub_col6 = raw_line[5]      # Used by En-route (EA, ER)
                sub_col13 = raw_line[12]    # Used by Airport (PC, PD, PE, PF)
                cont_no = raw_line[38]      # Primary record continuation number ('0' or '1')

                # 1. En-route Waypoints (Section EA) & Terminal Waypoints (Section PC)
                if (sec == "E" and sub_col6 == "A") or (sec == "P" and sub_col13 == "C"):
                    fix_id = raw_line[13:18].strip()
                    region = raw_line[19:21].strip()
                    lat, lon = parse_arinc_lat_lon(raw_line[32:41], raw_line[41:51])
                    name = raw_line[98:123].strip()
                    src_tag = "FAA_CIFP_EA" if sec == "E" else "FAA_CIFP_PC"
                    if fix_id and lat is not None and lon is not None:
                        waypoints[f"{fix_id}_{region}"] = (fix_id, name or fix_id, lat, lon, region, src_tag)

                # 2. En-route Airways (Section ER)
                elif sec == "E" and sub_col6 == "R":
                    if cont_no not in ("0", "1", " "):
                        continue
                    awy_id = raw_line[13:18].strip()
                    seq_no = raw_line[25:29].strip()
                    fix_id = raw_line[29:34].strip()
                    region = raw_line[34:36].strip()
                    min_alt = raw_line[83:88].strip()
                    max_alt = raw_line[93:98].strip()
                    if awy_id and fix_id and seq_no.isdigit():
                        airways.append((awy_id, int(seq_no), fix_id, region, min_alt, max_alt, "FAA_CIFP_ER"))

                # 3. Airport Procedures: SIDs (PD), STARs (PE), Approaches (PF)
                # In ARINC 424-18, sec (index 4) is 'P', index 5 is ' ', and subsection (index 12) is 'D', 'E', or 'F'
                elif sec == "P" and sub_col13 in ("D", "E", "F"):
                    # Only parse primary leg records (continuation number '0' or '1' at index 38)
                    if cont_no not in ("0", "1"):
                        continue
                    apt_icao = raw_line[6:10].strip()
                    proc_id = raw_line[13:19].strip()
                    route_type = raw_line[19].strip()
                    trans_id = raw_line[20:25].strip()
                    seq_no = raw_line[26:29].strip()
                    fix_id = raw_line[29:34].strip()
                    path_term = raw_line[47:49].strip()
                    alt_desc = raw_line[82].strip()
                    alt1 = raw_line[84:89].strip()
                    spd_limit = raw_line[99:102].strip()

                    if not apt_icao or not proc_id or not seq_no.isdigit():
                        continue

                    row = (
                        apt_icao,
                        proc_id,
                        route_type,
                        trans_id,
                        int(seq_no),
                        fix_id,
                        path_term,
                        alt_desc,
                        alt1,
                        spd_limit,
                        f"FAA_CIFP_{airac_info['cycleId']}",
                    )
                    if sub_col13 == "D":
                        sids.append(row)
                    elif sub_col13 == "E":
                        stars.append(row)
                    elif sub_col13 == "F":
                        approaches.append(row)

    print(f"Parsed counts -> Waypoints: {len(waypoints)}, Airways raw: {len(airways)}, SIDs: {len(sids)}, STARs: {len(stars)}, Approaches: {len(approaches)}")

    # Write Waypoints CSV
    wp_path = "navigation/waypoints/waypoints.csv"
    with open(wp_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#version", airac_info["cycleId"]])
        w.writerow(["id", "name", "latitude", "longitude", "region", "source"])
        for row in sorted(waypoints.values(), key=lambda x: (x[0], x[4])):
            w.writerow(row)

    # Convert sequential ER records into connected (from_fix -> to_fix) segments
    awy_path = "navigation/airways/airways.csv"
    airways.sort(key=lambda x: (x[0], x[1]))
    awy_segments = []
    for i in range(len(airways) - 1):
        curr = airways[i]
        nxt = airways[i + 1]
        if curr[0] == nxt[0]:  # Same airway_id
            awy_segments.append((curr[0], curr[1], curr[2], nxt[2], curr[4], curr[5], curr[6]))

    with open(awy_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#version", airac_info["cycleId"]])
        w.writerow(["airway_id", "seq", "from_fix", "to_fix", "min_alt_ft", "max_alt_ft", "source"])
        for seg in awy_segments:
            w.writerow(seg)

    # Write SIDs, STARs, Approaches
    proc_header = ["airport_icao", "procedure_id", "route_type", "transition_id", "seq", "fix_id", "path_terminator", "alt_desc", "alt1", "speed_limit_kt", "source"]
    for p_list, out_path in [
        (sids, "procedures/sids/sids.csv"),
        (stars, "procedures/stars/stars.csv"),
        (approaches, "procedures/approaches/approaches.csv"),
    ]:
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["#version", airac_info["cycleId"]])
            w.writerow(proc_header)
            for r in p_list:
                w.writerow(r)

    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for label, path, count, cov in [
        ("FAA CIFP En-Route & Terminal Waypoints", wp_path, len(waypoints), "US & FAA NAS 5LNC En-Route (EA) & Terminal (PC) Fixes"),
        ("FAA CIFP Published Airways", awy_path, len(awy_segments), "US & Oceanic Published En-Route Airways (ER)"),
        ("FAA CIFP Published SIDs (ARINC 424 PD)", "procedures/sids/sids.csv", len(sids), "US Departure Procedures with Path Terminators"),
        ("FAA CIFP Published STARs (ARINC 424 PE)", "procedures/stars/stars.csv", len(stars), "US Arrival Procedures with Path Terminators"),
        ("FAA CIFP Instrument Approaches (ARINC 424 PF)", "procedures/approaches/approaches.csv", len(approaches), "US Instrument Approaches"),
    ]:
        manifest_sources.append({
            "name": label,
            "file": path,
            "url": url,
            "license": "US Government Public Domain (FAA AeroNav)",
            "airacCycle": airac_info["cycleId"],
            "effectiveDate": airac_info["effectiveDate"],
            "expiryDate": airac_info["expiryDate"],
            "recordCount": count,
            "sizeBytes": os.path.getsize(path),
            "sha256": sha256_file(path),
            "coverage": cov,
            "downloadedAt": now_iso,
        })

    return len(sids) > 0 and len(stars) > 0


def download_ourairports_and_openflights(manifest_sources: list):
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    downloads = [
        (
            "OurAirports Worldwide Navaids",
            "https://davidmegginson.github.io/ourairports-data/navaids.csv",
            "navigation/navaids/navaids.csv",
            "Public Domain / CC0",
            "Worldwide VOR, VOR/DME, DME, NDB, TACAN & Radio Navaids",
        ),
        (
            "OurAirports Worldwide Runways & ILS",
            "https://davidmegginson.github.io/ourairports-data/runways.csv",
            "navigation/sources/runways.csv",
            "Public Domain / CC0",
            "Worldwide Airport Runways, Thresholds, Surface Types & ILS Frequencies",
        ),
        (
            "OpenFlights Commercial Airline Route Connections (Not Published Airways)",
            "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat",
            "navigation/airline_routes/routes.dat",
            "Open Database License (ODbL 1.0)",
            "Commercial Airline Airport-to-Airport Connections (For Airline Route Research Only)",
        ),
    ]

    old_routes_path = "navigation/airways/routes.dat"
    if os.path.exists(old_routes_path):
        os.remove(old_routes_path)

    for name, url, out_path, lic, cov in downloads:
        print(f"Downloading {name} ...")
        data = download_bytes(url)
        with open(out_path, "wb") as f:
            f.write(data)
        line_count = data.count(b"\n")
        manifest_sources.append({
            "name": name,
            "file": out_path,
            "url": url,
            "license": lic,
            "recordCount": line_count,
            "sizeBytes": os.path.getsize(out_path),
            "sha256": sha256_file(out_path),
            "coverage": cov,
            "downloadedAt": now_iso,
        })


def main():
    ensure_dirs()
    airac = get_active_airac()
    manifest_sources = []

    download_ourairports_and_openflights(manifest_sources)
    cifp_ok = process_faa_cifp(airac, manifest_sources)

    manifest = {
        "schemaVersion": 2,
        "airacCycle": airac["cycleId"] if cifp_ok else "unknown",
        "effectiveDate": airac["effectiveDate"] if cifp_ok else "unknown",
        "expiryDate": airac["expiryDate"] if cifp_ok else "unknown",
        "generatedAtUtc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "europeanProceduresStatus": "Unavailable under open redistribution licence — fallback to Great-Circle / Recorded ADS-B",
        "dataSources": manifest_sources,
    }

    with open("navigation_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print("Successfully updated navigation_manifest.json")


if __name__ == "__main__":
    main()
