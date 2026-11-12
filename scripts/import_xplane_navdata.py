#!/usr/bin/env python3
"""Lossless import of X-Plane/FlightGear-compatible IFR navigation text files.

Reads user-provided earth_fix.dat, earth_nav.dat and earth_awy.dat files.
No source files are downloaded and no licence is inferred from their format.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_NAMES = {
    "fixes": ("earth_fix.dat", "fix.dat", "earth_fix.dat.gz", "fix.dat.gz"),
    "navaids": ("earth_nav.dat", "nav.dat", "earth_nav.dat.gz", "nav.dat.gz"),
    "airways": ("earth_awy.dat", "awy.dat", "earth_awy.dat.gz", "awy.dat.gz"),
}
OUTPUTS = {
    "flightgear_fixes": "navigation/waypoints/flightgear_fixes.csv",
    "flightgear_navaids": "navigation/navaids/flightgear_navaids.csv",
    "flightgear_airway_segments": "navigation/airways/flightgear_airway_segments.csv",
}
NAVAID_TYPES = {
    2: "NDB", 3: "VHF_NAVAID", 4: "ILS_LOCALIZER",
    5: "LOCALIZER_LDA_SDF", 6: "ILS_GLIDESLOPE",
    7: "ILS_OUTER_MARKER", 8: "ILS_MIDDLE_MARKER",
    9: "ILS_INNER_MARKER", 12: "DME_PAIRED",
    13: "DME_STANDALONE", 14: "SBAS_GBAS_FPAP",
    15: "GBAS_GROUND_STATION", 16: "SBAS_GBAS_LTP_FTP",
}
ENDPOINT_TYPES = {"11": "FIX", "2": "NDB", "3": "VHF_NAVAID"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def number(value: str):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or abs(result) == float("inf"):
        return None
    return result


def valid_coordinates(lat, lon) -> bool:
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180


def read_source_file(path: Path, kind: str):
    raw = path.read_bytes()
    compressed = raw.startswith(b"\x1f\x8b") or path.suffix.lower() == ".gz"
    try:
        payload = gzip.decompress(raw) if compressed else raw
    except OSError as exc:
        raise ValueError(f"{path}: invalid gzip-compressed source file: {exc}") from exc
    lines = payload.decode("utf-8-sig").splitlines()
    if len(lines) < 3:
        raise ValueError(f"{path}: file is too short")
    byte_order = lines[0].strip()
    if byte_order not in {"I", "A"}:
        raise ValueError(f"{path}: unsupported header marker {byte_order!r}")
    header = lines[1].strip()
    version_match = re.search(r"\b(\d{3,4})\s+Version\b", header, re.IGNORECASE)
    # Preserve the complete source token: X-Plane/FlightGear headers may use
    # values such as 2401, 201610 or 2013.10. Do not coerce these into AIRAC.
    cycle_match = re.search(
        r"\bdata\s+cycle\s+([0-9]{4,6}(?:\.[0-9]{1,2})?)\b",
        header,
        re.IGNORECASE,
    )
    build_match = re.search(r"\bbuild\s+(\d{8})\b", header, re.IGNORECASE)
    if not version_match:
        raise ValueError(f"{path}: cannot identify format version: {header}")
    version = version_match.group(1)
    allowed = {
        "fixes": {"600", "1101", "1200"},
        "navaids": {"1100", "1150", "1200"},
        # XP AWY1101 uses a 1100 data-file header; older regional datasets
        # may use the legacy 640 layout.
        "airways": {"640", "1100"},
    }[kind]
    if version not in allowed:
        raise ValueError(f"{path}: unsupported {kind} version {version}; expected {sorted(allowed)}")
    records, terminator = [], False
    for line_number, raw_line in enumerate(lines[2:], start=3):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line == "99" or line.startswith("99 "):
            terminator = True
            break
        records.append((line_number, line, line.split()))
    if not terminator:
        raise ValueError(f"{path}: missing 99 end-of-file record")
    return {
        "path": str(path), "file_name": path.name, "raw": raw,
        "payload_sha256": sha256(payload),
        "compression": "gzip" if compressed else "none",
        "header": header, "byte_order": byte_order,
        "format_version": version,
        "data_cycle": cycle_match.group(1) if cycle_match else "unknown",
        "build_date": build_match.group(1) if build_match else "unknown",
        "records": records,
    }


def locate_source_files(source_dir: Path):
    located, missing = {}, []
    for kind, candidates in INPUT_NAMES.items():
        path = next((source_dir / name for name in candidates if (source_dir / name).is_file()), None)
        if path is None:
            missing.append(" or ".join(candidates))
        else:
            located[kind] = path
    return located, missing


def parse_fixes(source):
    """Parse legacy XPFIX600 plus typed XPFIX1101 and named XPFIX1200."""
    rows, rejected = [], 0
    version = source.get("format_version", "1101")
    if version not in {"600", "1101", "1200"}:
        raise ValueError(f"Unsupported fix format version: {version}")
    for line_number, raw, fields in source["records"]:
        lat = number(fields[0]) if len(fields) > 0 else None
        lon = number(fields[1]) if len(fields) > 1 else None
        if not valid_coordinates(lat, lon):
            rejected += 1
            continue

        if version == "600":
            # Legacy FIX 600 carries only coordinates and an identifier.
            # Region, terminal/en-route scope and waypoint type are absent,
            # so they remain explicitly unknown rather than being inferred.
            if len(fields) != 3 or not fields[2]:
                rejected += 1
                continue
            ident = fields[2]
            area = region = waypoint_type = ""
            scope = "unknown"
            printed_name = ident
        else:
            minimum_fields = 6 if version == "1101" else 7
            if len(fields) < minimum_fields:
                rejected += 1
                continue
            ident, area, region, waypoint_type = fields[2:6]
            if not waypoint_type:
                rejected += 1
                continue
            scope = "enroute" if area.upper() == "ENRT" else "terminal"
            printed_name = ident if version == "1101" else " ".join(fields[6:]).strip()
            if version == "1200" and not printed_name:
                rejected += 1
                continue

        rows.append({
            "ident": ident.upper(),
            "terminal_area": area.upper(),
            "region_code": region.upper(),
            "scope": scope,
            "entity_type": "FIX",
            "waypoint_type_code": waypoint_type,
            "printed_name": printed_name,
            "latitude": f"{lat:.8f}",
            "longitude": f"{lon:.8f}",
            "source_file": source["file_name"],
            "source_line": line_number,
            "raw_record": raw,
        })
    return rows, rejected


def parse_navaids(source):
    """XPNAV: facility code, position, elevation, frequency and facility identity."""
    rows, rejected = [], 0
    for line_number, raw, fields in source["records"]:
        if len(fields) < 10:
            rejected += 1
            continue
        try:
            row_code = int(fields[0])
        except ValueError:
            rejected += 1
            continue
        lat, lon = number(fields[1]), number(fields[2])
        if not valid_coordinates(lat, lon):
            rejected += 1
            continue
        ident, area, region = fields[7:10]
        runway_based = row_code in {4, 5, 6, 7, 8, 9, 14, 15, 16}
        runway = fields[10] if runway_based and len(fields) > 10 else ""
        name_start = 11 if runway_based else 10
        name = " ".join(fields[name_start:]).strip()
        elevation = number(fields[3])
        frequency = number(fields[4])
        range_or_class = number(fields[5])
        parameter = number(fields[6])
        facility_type = NAVAID_TYPES.get(row_code, f"UNKNOWN_ROW_{row_code}")
        subtype = ""
        if row_code == 3:
            upper = name.upper()
            subtype = next((suffix for suffix in ("VORTAC", "VOR-DME", "TACAN", "VOR") if suffix in upper), "")
        if row_code == 2:
            frequency_unit, frequency_mhz = "kHz", ""
        elif row_code in {3, 4, 5, 6, 12, 13}:
            frequency_unit = "MHz_x100"
            frequency_mhz = f"{frequency / 100:.4f}" if frequency is not None else ""
        else:
            frequency_unit, frequency_mhz = "row_specific", ""
        rows.append({
            "row_code": row_code,
            "facility_type": facility_type,
            "facility_subtype": subtype,
            "ident": ident.upper(),
            "terminal_area": area.upper(),
            "region_code": region.upper(),
            "scope": "enroute" if area.upper() == "ENRT" else "terminal",
            "latitude": f"{lat:.8f}",
            "longitude": f"{lon:.8f}",
            "elevation_ft": elevation if elevation is not None else "",
            "frequency_source_value": frequency if frequency is not None else "",
            "frequency_unit": frequency_unit,
            "frequency_mhz": frequency_mhz,
            "range_or_class": range_or_class if range_or_class is not None else "",
            "parameter_source_value": parameter if parameter is not None else "",
            "runway_ident": runway,
            "name": name,
            "source_file": source["file_name"],
            "source_line": line_number,
            "raw_fields_json": json.dumps(fields, separators=(",", ":")),
            "raw_record": raw,
        })
    return rows, rejected


def resolve_endpoint(ident, region, type_code, fixes_index, navaids_index):
    key = (ident.upper(), region.upper())
    if type_code == "11":
        candidates = fixes_index.get(key, [])
    elif type_code in {"2", "3"}:
        candidates = navaids_index.get((key[0], key[1], int(type_code)), [])
    else:
        return {"status": "unsupported_type", "latitude": "", "longitude": ""}
    if not candidates:
        return {"status": "unresolved", "latitude": "", "longitude": ""}
    if len(candidates) != 1:
        return {"status": "ambiguous", "latitude": "", "longitude": ""}
    item = candidates[0]
    return {"status": "resolved", "latitude": item["latitude"], "longitude": item["longitude"]}


def parse_airways(source, fixes, navaids):
    fixes_index, navaids_index = defaultdict(list), defaultdict(list)
    for item in fixes:
        if item["scope"] == "enroute":
            fixes_index[(item["ident"], item["region_code"])].append(item)
    for item in navaids:
        if item["scope"] == "enroute" and item["row_code"] in {2, 3}:
            navaids_index[(item["ident"], item["region_code"], item["row_code"])].append(item)

    rows, rejected, unresolved_segments, ambiguous_endpoints = [], 0, 0, 0
    for line_number, raw, fields in source["records"]:
        if source.get("format_version") == "640":
            # Legacy AWY 640 stores the endpoint coordinates in each segment,
            # but has no endpoint region/type or low/high level classification.
            # Preserve the supplied coordinates and raw direction code without
            # pretending that these fields were resolved from typed fixes.
            if len(fields) < 10:
                rejected += 1
                continue
            from_ident, to_ident = fields[0], fields[3]
            from_lat, from_lon = number(fields[1]), number(fields[2])
            to_lat, to_lon = number(fields[4]), number(fields[5])
            direction = fields[6]
            minimum_fl, maximum_fl = number(fields[7]), number(fields[8])
            airway_names = " ".join(fields[9:]).strip()
            if (
                not from_ident or not to_ident
                or not valid_coordinates(from_lat, from_lon)
                or not valid_coordinates(to_lat, to_lon)
                or minimum_fl is None or maximum_fl is None
                or minimum_fl < 0 or maximum_fl < minimum_fl
                or not airway_names
            ):
                rejected += 1
                continue
            rows.append({
                "airway_names": airway_names,
                "airway_names_json": json.dumps(airway_names.split("-"), separators=(",", ":")),
                "from_ident": from_ident.upper(),
                "from_region": "",
                "from_type_code": "",
                "from_type": "UNKNOWN",
                "from_latitude": f"{from_lat:.8f}",
                "from_longitude": f"{from_lon:.8f}",
                "from_resolution": "source_coordinates",
                "to_ident": to_ident.upper(),
                "to_region": "",
                "to_type_code": "",
                "to_type": "UNKNOWN",
                "to_latitude": f"{to_lat:.8f}",
                "to_longitude": f"{to_lon:.8f}",
                "to_resolution": "source_coordinates",
                "direction_restriction": direction,
                "direction_semantics": "legacy_code_unmapped",
                "level_code": "",
                "level_classification": "unknown",
                "minimum_altitude_hundreds_ft": minimum_fl,
                "maximum_altitude_hundreds_ft": maximum_fl,
                "minimum_altitude_ft": round(minimum_fl * 100),
                "maximum_altitude_ft": round(maximum_fl * 100),
                "source_file": source["file_name"],
                "source_line": line_number,
                "raw_record": raw,
            })
            continue

        if len(fields) < 11:
            rejected += 1
            continue
        from_ident, from_region, from_type = fields[0:3]
        to_ident, to_region, to_type = fields[3:6]
        direction, level = fields[6:8]
        try:
            minimum_hundreds, maximum_hundreds = int(fields[8]), int(fields[9])
        except ValueError:
            rejected += 1
            continue
        if direction not in {"N", "F", "B"} or level not in {"1", "2"}:
            rejected += 1
            continue
        airway_names = fields[10]
        from_result = resolve_endpoint(from_ident, from_region, from_type, fixes_index, navaids_index)
        to_result = resolve_endpoint(to_ident, to_region, to_type, fixes_index, navaids_index)
        if from_result["status"] != "resolved" or to_result["status"] != "resolved":
            unresolved_segments += 1
        ambiguous_endpoints += sum(r["status"] == "ambiguous" for r in (from_result, to_result))
        rows.append({
            "airway_names": airway_names,
            "airway_names_json": json.dumps(airway_names.split("-"), separators=(",", ":")),
            "from_ident": from_ident.upper(),
            "from_region": from_region.upper(),
            "from_type_code": from_type,
            "from_type": ENDPOINT_TYPES.get(from_type, f"UNKNOWN_{from_type}"),
            "from_latitude": from_result["latitude"],
            "from_longitude": from_result["longitude"],
            "from_resolution": from_result["status"],
            "to_ident": to_ident.upper(),
            "to_region": to_region.upper(),
            "to_type_code": to_type,
            "to_type": ENDPOINT_TYPES.get(to_type, f"UNKNOWN_{to_type}"),
            "to_latitude": to_result["latitude"],
            "to_longitude": to_result["longitude"],
            "to_resolution": to_result["status"],
            "direction_restriction": direction,
            "level_code": level,
            "level_classification": "low" if level == "1" else "high",
            "minimum_altitude_hundreds_ft": minimum_hundreds,
            "maximum_altitude_hundreds_ft": maximum_hundreds,
            "minimum_altitude_ft": minimum_hundreds * 100,
            "maximum_altitude_ft": maximum_hundreds * 100,
            "source_file": source["file_name"],
            "source_line": line_number,
            "raw_record": raw,
        })
    return rows, rejected, unresolved_segments, ambiguous_endpoints


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else []
    if not fields:
        raise ValueError(f"Refusing to write headerless empty dataset: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def file_summary(root: Path, dataset_id: str, relative_path: str, source_meta=None):
    path = root / relative_path
    exists = path.is_file()
    count = 0
    if exists:
        with path.open("r", encoding="utf-8", newline="") as handle:
            count = max(0, sum(1 for _ in csv.reader(handle)) - 1)
    meta = source_meta or {}
    return {
        "id": dataset_id, "path": relative_path,
        "available": bool(exists and count > 0),
        "recordCount": count, "sizeBytes": path.stat().st_size if exists else 0,
        "sha256": sha256(path.read_bytes()) if exists else None,
        "sourceProvider": meta.get("provider", ""),
        "license": meta.get("license", ""),
        "licenseStatus": meta.get("licenseStatus", "not_applicable"),
        "dataCycle": meta.get("dataCycle", "unknown"),
    }


def update_manifest(manifest_path: Path, root: Path, import_meta=None):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    metadata_path = root / "navigation/sources/flightgear/import_metadata.json"
    if import_meta is not None:
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(import_meta, indent=2) + "\n", encoding="utf-8")
    elif metadata_path.exists():
        import_meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    else:
        import_meta = {}

    manifest.setdefault("schemaVersion", 12)
    datasets = [
        file_summary(root, "airports", "app/src/main/assets/airports.csv"),
        file_summary(root, "runways", "navigation/runways/runways_parsed.csv"),
        file_summary(root, "ourairports_navaids", "navigation/navaids/navaids.csv"),
        file_summary(root, "flightgear_fixes", OUTPUTS["flightgear_fixes"], import_meta),
        file_summary(root, "flightgear_navaids", OUTPUTS["flightgear_navaids"], import_meta),
        file_summary(root, "flightgear_airway_segments", OUTPUTS["flightgear_airway_segments"], import_meta),
    ]
    capabilities = manifest.setdefault("capabilities", {})
    for dataset_id, relative_path, capability in (
        ("sids", "procedures/sids/sids.csv", "sids"),
        ("stars", "procedures/stars/stars.csv", "stars"),
        ("approaches", "procedures/approaches/approaches.csv", "approaches"),
    ):
        summary = file_summary(root, dataset_id, relative_path)
        verified = bool(capabilities.get(capability, False))
        summary["available"] = bool(summary["available"] and verified)
        summary["status"] = "verified" if summary["available"] else (
            "present_but_unverified" if summary["recordCount"] > 0 else "not_imported"
        )
        datasets.append(summary)
    manifest["datasets"] = datasets
    if import_meta:
        manifest["flightgearImport"] = {
            key: import_meta.get(key, default)
            for key, default in (
                ("provider", "unverified"),
                ("sourceUrl", ""),
                ("license", ""),
                ("licenseStatus", "review_required"),
                ("licenseUrl", ""),
                ("dataCycle", "unknown"),
                ("formatVersions", {}),
                ("files", []),
                ("counts", {}),
                ("airwayResolution", {}),
            )
        }
    capabilities["independentWaypoints"] = datasets[3]["available"]
    capabilities["flightgearNavaids"] = datasets[4]["available"]
    capabilities["publishedAirways"] = datasets[5]["available"]

    # Keep manifest totals synchronized with the normalized datasets.
    statistics = manifest.setdefault("statistics", {})
    statistics["airports"] = datasets[0]["recordCount"]
    statistics["runways"] = datasets[1]["recordCount"]
    statistics["navaids"] = datasets[2]["recordCount"]
    statistics["ifrWaypoints"] = datasets[3]["recordCount"] if datasets[3]["available"] else 0
    statistics["flightgearNavaids"] = datasets[4]["recordCount"] if datasets[4]["available"] else 0
    airway_counts = (import_meta or {}).get("counts", {})
    statistics["airwaySegments"] = datasets[5]["recordCount"] if datasets[5]["available"] else 0
    statistics["lowAirwaySegments"] = airway_counts.get("lowAirwaySegments", 0)
    statistics["highAirwaySegments"] = airway_counts.get("highAirwaySegments", 0)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(temp_path, manifest_path)
    return manifest


def import_navdata(source_dir: Path, root: Path, manifest_path: Path, optional=False):
    located, missing = locate_source_files(source_dir)
    if missing:
        if not optional:
            raise FileNotFoundError(f"Missing IFR source files in {source_dir}: {', '.join(missing)}")
        update_manifest(manifest_path, root)
        print(f"[FlightTempo] IFR import skipped; missing: {', '.join(missing)}")
        return {"status": "skipped_missing_source", "missing": missing}

    sources = {kind: read_source_file(path, kind) for kind, path in located.items()}
    cycles_by_kind = {kind: src["data_cycle"] for kind, src in sources.items()}
    if "unknown" in cycles_by_kind.values() or len(set(cycles_by_kind.values())) != 1:
        raise ValueError(
            "All three IFR source headers must declare the same known data-cycle token; "
            f"found {cycles_by_kind}. Mixed or missing cycles must not be combined."
        )
    data_cycle = next(iter(cycles_by_kind.values()))

    fixes, rejected_fixes = parse_fixes(sources["fixes"])
    navaids, rejected_navaids = parse_navaids(sources["navaids"])
    airways, rejected_airways, unresolved_segments, ambiguous_endpoints = parse_airways(
        sources["airways"], fixes, navaids
    )
    if not fixes or not navaids or not airways:
        raise ValueError("One or more IFR source files produced zero valid records; refusing to publish")

    source_manifest = source_dir / "source-manifest.json"
    supplied = json.loads(source_manifest.read_text(encoding="utf-8")) if source_manifest.exists() else {}
    provider = supplied.get("provider", "Unverified X-Plane/FlightGear-compatible source")
    licence = supplied.get("license", "")
    redistributable = supplied.get("redistributable") is True
    if not redistributable or not licence:
        if optional:
            update_manifest(manifest_path, root)
            print("[FlightTempo] IFR sources found but not published: source-manifest.json must declare licence and redistributable=true")
            return {"status": "skipped_license_unverified"}
        raise PermissionError(
            "Refusing to publish navdata without an explicit source-manifest.json "
            "containing a verified license and redistributable=true"
        )

    metadata = {
        "provider": provider,
        "sourceUrl": supplied.get("sourceUrl", ""),
        "license": licence,
        "licenseStatus": "declared_redistributable_check_required",
        "redistributable": True,
        "licenseUrl": supplied.get("licenseUrl", ""),
        "dataCycle": data_cycle,
        "formatVersions": {kind: src["format_version"] for kind, src in sources.items()},
        "files": [{
            "kind": kind, "fileName": src["file_name"],
            "sha256": sha256(src["raw"]), "payloadSha256": src["payload_sha256"],
            "sizeBytes": len(src["raw"]), "compression": src["compression"],
            "byteOrder": src["byte_order"], "formatVersion": src["format_version"],
            "dataCycle": src["data_cycle"], "buildDate": src["build_date"],
            "copyrightHeader": src["header"],
        } for kind, src in sources.items()],
        "counts": {
            "fixes": len(fixes),
            "navaids": len(navaids),
            "airwaySegments": len(airways),
            "lowAirwaySegments": sum(row.get("level_code") == "1" for row in airways),
            "highAirwaySegments": sum(row.get("level_code") == "2" for row in airways),
            "unknownLevelAirwaySegments": sum(row.get("level_classification") == "unknown" for row in airways),
            "rejectedFixRows": rejected_fixes,
            "rejectedNavaidRows": rejected_navaids,
            "rejectedAirwayRows": rejected_airways,
        },
        "airwayResolution": {
            "segmentsWithAtLeastOneUnresolvedEndpoint": unresolved_segments,
            "ambiguousEndpoints": ambiguous_endpoints,
        },
    }

    with tempfile.TemporaryDirectory(prefix="flighttempo-ifr-") as temporary:
        staged = {
            "flightgear_fixes": Path(temporary) / "fixes.csv",
            "flightgear_navaids": Path(temporary) / "navaids.csv",
            "flightgear_airway_segments": Path(temporary) / "airways.csv",
        }
        for name, rows in (
            ("flightgear_fixes", fixes),
            ("flightgear_navaids", navaids),
            ("flightgear_airway_segments", airways),
        ):
            write_csv(staged[name], rows)
        # Replace all three normalized files only after all have been generated.
        for name, staged_path in staged.items():
            destination = root / OUTPUTS[name]
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_path, destination)

    update_manifest(manifest_path, root, metadata)
    print("[FlightTempo] IFR import complete: " + json.dumps(metadata["counts"] | metadata["airwayResolution"]))
    return {"status": "imported", **metadata["counts"], **metadata["airwayResolution"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / "navigation/sources/flightgear")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path, default=ROOT / "navigation_manifest.json")
    parser.add_argument("--optional", action="store_true")
    args = parser.parse_args()
    import_navdata(args.source_dir, args.root, args.manifest, optional=args.optional)


if __name__ == "__main__":
    main()
