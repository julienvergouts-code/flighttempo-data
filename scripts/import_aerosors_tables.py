#!/usr/bin/env python3
"""Export Aero.Sors VOR/NDB and ILS workbooks to experimental FlightTempo CSVs.

All non-empty worksheet rows are preserved. Recognized fields are mapped to
canonical columns; all source columns remain in raw_fields_json. This importer
does not parse the full World FSXP3D BGL package or create procedures.

The reviewed Aero.Sors terms permit distribution of the original package
unchanged on free media; explicit permission for derivative CSV republication
has not been confirmed. Keep these exports marked development-only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import logging
import re
import time
import urllib.request
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

HOME = "https://www.aero.sors.fr/index.html"
SOURCES = {
    "aerosors_vor_ndb": {
        "url": "https://www.aero.sors.fr/hfiles/VORNDB_Table.xlsx",
        "page": "https://www.aero.sors.fr/navaids.html",
        "path": "navigation/aerosors/vor_ndb.csv",
        "coverage": "Worldwide VOR/NDB table published by Aero.Sors",
    },
    "aerosors_ils": {
        "url": "https://www.aero.sors.fr/hfiles/ILS_Table.xlsx",
        "page": "https://www.aero.sors.fr/navaids.html",
        "path": "navigation/aerosors/ils.csv",
        "coverage": "Worldwide ILS table published by Aero.Sors",
    },
}
FIELDS = [
    "source_sheet", "source_row", "source_cycle", "record_status", "record_type",
    "ident", "name", "type", "frequency", "frequency_unit", "latitude_deg",
    "longitude_deg", "coordinate_status", "elevation_ft", "range_nm", "country",
    "airport_icao", "runway", "course_deg", "glide_slope_angle_deg",
    "dme_channel", "remarks", "raw_fields_json",
]
ALIASES = {
    "ident": {"ident", "identifier", "identification", "id", "beacon_id", "loc_ident", "localizer_ident"},
    "name": {"name", "navaid_name", "station_name", "airport_name", "site_name"},
    "type": {"type", "navaid_type", "facility_type", "aid_type", "class"},
    "frequency": {"frequency", "freq", "frequency_mhz", "freq_mhz", "frequency_khz", "freq_khz"},
    "latitude_deg": {"latitude", "lat", "latitude_deg", "lat_deg", "latitude_decimal", "lat_dd"},
    "longitude_deg": {"longitude", "lon", "long", "longitude_deg", "lon_deg", "long_deg", "longitude_decimal"},
    "elevation_ft": {"elevation_ft", "elev_ft", "altitude_ft", "elevation_feet", "elev_feet"},
    "range_nm": {"range_nm", "service_volume_nm", "coverage_nm"},
    "country": {"country", "country_code", "iso_country"},
    "airport_icao": {"airport", "airport_icao", "icao", "icao_code", "airport_id", "apt_icao"},
    "runway": {"runway", "runway_id", "rwy", "rwy_id", "runway_ident"},
    "course_deg": {"course", "course_deg", "true_course", "true_course_deg", "loc_course", "localizer_course", "heading_deg"},
    "glide_slope_angle_deg": {"glide_slope", "glide_slope_angle", "glide_slope_angle_deg", "gs_angle", "gs_angle_deg"},
    "dme_channel": {"dme_channel", "channel", "dme_ch"},
    "remarks": {"remarks", "remark", "comments", "notes", "description"},
}


def cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalized_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", cell_text(value).lower().replace("°", " deg ")).strip("_")


def decimal_coordinate(value: str, axis: str) -> str:
    """Return decimal degrees only when the source cell is unambiguous."""
    raw = cell_text(value).strip().upper()
    if not raw:
        return ""
    match = re.fullmatch(r"([NSEW])?\s*([+-]?\d+(?:\.\d+)?)\s*([NSEW])?", raw)
    if not match:
        # DMS or packed strings remain preserved in raw_fields_json.
        return ""
    hemisphere_a, number, hemisphere_b = match.groups()
    hemisphere = hemisphere_a or hemisphere_b
    if hemisphere_a and hemisphere_b and hemisphere_a != hemisphere_b:
        return ""
    try:
        numeric = float(number)
    except ValueError:
        return ""
    limit = 90 if axis == "lat" else 180
    if abs(numeric) > limit:
        return ""
    if hemisphere:
        if axis == "lat" and hemisphere not in {"N", "S"}:
            return ""
        if axis == "lon" and hemisphere not in {"E", "W"}:
            return ""
        numeric = abs(numeric) * (-1 if hemisphere in {"S", "W"} else 1)
    return f"{numeric:.8f}".rstrip("0").rstrip(".")


def fetch(url: str, binary: bool = False) -> bytes:
    last_error = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "FlightTempo-AeroSors-Importer/1.0"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
            if binary and (len(body) < 100 or not body.startswith(b"PK")):
                raise ValueError(f"not a valid XLSX archive ({len(body)} bytes)")
            return body
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"download failed: {url}: {last_error}")


def listed_cycle(page: str) -> str:
    plain = html.unescape(re.sub(r"<[^>]+>", " ", page))
    plain = re.sub(r"\s+", " ", plain)
    patterns = (
        r"VOR\s*/\s*NDB\s*table\s*\((\d{4}-R\d+)\)",
        r"ILS\s*table\s*\((\d{4}-R\d+)\)",
    )
    for pattern in patterns:
        match = re.search(pattern, plain, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return "unknown"


def pick_header(rows: list[tuple]) -> int:
    aliases = set().union(*ALIASES.values())
    best_score = (-1, -1, -1)
    best_index = 0
    for index, row in enumerate(rows[:40]):
        values = [normalized_header(value) for value in row if cell_text(value)]
        score = (sum(value in aliases for value in values), len(set(values)), len(values))
        if score > best_score:
            best_score, best_index = score, index
    return best_index


def workbook_records(payload: bytes, kind: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    workbook = load_workbook(BytesIO(payload), read_only=True, data_only=True)
    records: list[dict[str, str]] = []
    sheets: list[dict[str, Any]] = []
    embedded_cycles: list[str] = []

    try:
        for worksheet in workbook.worksheets:
            rows = list(worksheet.iter_rows(values_only=True))
            if not rows:
                continue
            for row in rows[:40]:
                for value in row:
                    cycle_match = re.search(r"\b(\d{4}-R\d+)\b", cell_text(value), re.IGNORECASE)
                    if cycle_match:
                        embedded_cycles.append(cycle_match.group(1).upper())

            header_index = pick_header(rows)
            headers: list[str] = []
            used: set[str] = set()
            for column_index, value in enumerate(rows[header_index]):
                key = normalized_header(value) or f"column_{column_index + 1:02d}"
                if key in used:
                    key = f"{key}_{column_index + 1:02d}"
                used.add(key)
                headers.append(key)

            exported = 0
            for row_number, row in enumerate(rows[header_index + 1 :], header_index + 2):
                raw = {
                    headers[index]: cell_text(row[index]) if index < len(row) else ""
                    for index in range(len(headers))
                }
                raw = {key: value for key, value in raw.items() if value}
                if not raw:
                    continue

                mapped: dict[str, str] = {}
                for field, accepted_headers in ALIASES.items():
                    mapped[field] = next(
                        (raw[key] for key in raw if key in accepted_headers and raw[key]), ""
                    )
                    if not mapped[field]:
                        for key, value in raw.items():
                            fuzzy_match = (
                                (field == "frequency" and "freq" in key)
                                or (field == "latitude_deg" and key.startswith("lat"))
                                or (field == "longitude_deg" and (key.startswith("lon") or key.startswith("long")))
                                or (field == "course_deg" and "course" in key)
                                or (field == "glide_slope_angle_deg" and ("glide" in key or key.startswith("gs_")))
                            )
                            if value and fuzzy_match:
                                mapped[field] = value
                                break

                source_latitude = mapped.get("latitude_deg", "")
                source_longitude = mapped.get("longitude_deg", "")
                mapped["latitude_deg"] = decimal_coordinate(source_latitude, "lat")
                mapped["longitude_deg"] = decimal_coordinate(source_longitude, "lon")
                if mapped["latitude_deg"] and mapped["longitude_deg"]:
                    coordinate_status = "decimal_degrees"
                elif source_latitude or source_longitude:
                    coordinate_status = "source_coordinate_text_unparsed"
                else:
                    coordinate_status = "not_supplied"

                frequency_column = next((key for key in raw if "freq" in key), "")
                type_text = " ".join(
                    (worksheet.title, mapped.get("type", ""), mapped.get("name", ""))
                ).upper()
                record_type = next(
                    (
                        value.replace("/", "-")
                        for value in (
                            "VORTAC", "VOR/DME", "VOR-DME", "VOR", "NDB/DME",
                            "NDB-DME", "NDB", "TACAN", "DME", "ILS", "LOC",
                            "LOCALIZER", "GLIDESLOPE",
                        )
                        if value in type_text
                    ),
                    "VOR_NDB" if kind == "vor_ndb" else "ILS",
                )
                is_navigation_record = bool(
                    mapped.get("ident")
                    or mapped.get("airport_icao")
                    or mapped.get("latitude_deg")
                    or mapped.get("longitude_deg")
                )
                record = {field: "" for field in FIELDS}
                record.update(
                    {
                        "source_sheet": worksheet.title,
                        "source_row": str(row_number),
                        "record_status": (
                            "navigation_record" if is_navigation_record else "metadata_or_note"
                        ),
                        "record_type": record_type,
                        "coordinate_status": coordinate_status,
                        **mapped,
                        "frequency_unit": (
                            "MHz" if "mhz" in frequency_column
                            else "kHz" if "khz" in frequency_column
                            else ""
                        ),
                        "raw_fields_json": json.dumps(
                            raw, ensure_ascii=False, separators=(",", ":")
                        ),
                    }
                )
                records.append(record)
                exported += 1

            sheets.append(
                {
                    "sheet": worksheet.title,
                    "rowsExported": exported,
                    "headerRowNumber": header_index + 1,
                    "headers": headers,
                }
            )
    finally:
        workbook.close()

    unique_cycles = sorted(set(embedded_cycles))
    return records, {
        "sheets": sheets,
        "embeddedCycles": unique_cycles,
        "embeddedCycle": unique_cycles[0] if len(unique_cycles) == 1 else "unknown",
    }


def write_csv(path: Path, records: list[dict[str, str]], cycle: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        for record in records:
            row = {field: record.get(field, "") for field in FIELDS}
            row["source_cycle"] = cycle
            writer.writerow(row)

    payload = path.read_bytes()
    return {
        "recordCount": len(records),
        "navigationalRecordCount": sum(
            record.get("record_status") == "navigation_record" for record in records
        ),
        "sizeBytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="navigation_manifest.json")
    parser.add_argument("--output-dir", default=".")
    parser.add_argument("--optional", action="store_true")
    args = parser.parse_args()

    root = Path(args.output_dir).resolve()
    imported_at = datetime.now(timezone.utc).isoformat()
    try:
        listed_cycle_value = listed_cycle(fetch(HOME).decode("utf-8", errors="replace"))
    except Exception as exc:
        logging.warning("Aero.Sors current-cycle listing unavailable: %s", exc)
        listed_cycle_value = "unknown"

    manifest_path = root / args.manifest
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {"datasets": [], "dataSources": [], "capabilities": {}, "statistics": {}}
    )
    datasets_by_id = {item.get("id"): item for item in manifest.get("datasets", [])}
    sources_by_id = {item.get("dataset"): item for item in manifest.get("dataSources", [])}
    exports: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for dataset_id, config in SOURCES.items():
        try:
            workbook_payload = fetch(config["url"], binary=True)
            kind = "vor_ndb" if dataset_id.endswith("vor_ndb") else "ils"
            records, workbook_info = workbook_records(workbook_payload, kind)
            if not records:
                raise RuntimeError("workbook contained no non-empty worksheet rows")

            embedded_cycle = workbook_info["embeddedCycle"]
            data_cycle = embedded_cycle if embedded_cycle != "unknown" else listed_cycle_value
            output_path = root / config["path"]
            counts = write_csv(output_path, records, data_cycle)
            entry = {
                "id": dataset_id,
                "path": config["path"],
                "downloadUrl": (
                    "https://raw.githubusercontent.com/julienvergouts-code/"
                    f"flighttempo-data/main/{config['path']}"
                ),
                "available": True,
                **counts,
                "sourceProvider": "Aero.Sors / Hervé Sors",
                "sourceUrl": config["url"],
                "sourcePageUrl": config["page"],
                "coverage": config["coverage"],
                "sourceTag": f"AEROSORS_{data_cycle}",
                "license": (
                    "Aero.Sors donationware; unchanged redistribution of the original "
                    "package is permitted, but derivative CSV republication permission "
                    "has not been confirmed"
                ),
                "licenseStatus": (
                    "personal_development_test_only_derivative_redistribution_not_confirmed"
                ),
                "dataCycle": data_cycle,
                "effectiveDate": "",
                "expiryDate": "",
                "provenanceVerification": (
                    "workbook_exported; not independently cross-checked against AIP"
                ),
                "testDownloadAvailable": True,
                "downloadPurpose": "development_test_only",
                "operationallyAvailable": False,
                "status": "experimental_personal_test_only",
                "sourceWorkbookBytes": len(workbook_payload),
                "sourceWorkbookSha256": hashlib.sha256(workbook_payload).hexdigest(),
                "sheetCount": len(workbook_info["sheets"]),
            }
            datasets_by_id[dataset_id] = entry
            summary = {
                "dataset": dataset_id,
                "provider": "Aero.Sors / Hervé Sors",
                "url": config["url"],
                "sourcePageUrl": config["page"],
                "licenseStatus": entry["licenseStatus"],
                "downloadedAt": imported_at,
                "sourceWorkbookBytes": len(workbook_payload),
                "sourceWorkbookSha256": entry["sourceWorkbookSha256"],
                "sourceCycle": data_cycle,
                **counts,
                "sheets": workbook_info["sheets"],
            }
            sources_by_id[dataset_id] = summary
            exports[dataset_id] = summary
            logging.info(
                "Exported %s: %s rows (%s navigation records), %s bytes, cycle %s",
                dataset_id,
                counts["recordCount"],
                counts["navigationalRecordCount"],
                counts["sizeBytes"],
                data_cycle,
            )
        except Exception as exc:
            errors.append(f"{dataset_id}: {exc}")
            logging.warning("Aero.Sors import failed for %s: %s", dataset_id, exc)

    if exports:
        manifest["datasets"] = list(datasets_by_id.values())
        manifest["dataSources"] = list(sources_by_id.values())
        capabilities = manifest.setdefault("capabilities", {})
        statistics = manifest.setdefault("statistics", {})
        for dataset_id, summary in exports.items():
            capabilities[dataset_id] = True
            statistics[dataset_id] = summary["recordCount"]
            statistics[dataset_id + "NavigationalRecords"] = summary["navigationalRecordCount"]
        capabilities["aeroSorsIlsFacilities"] = bool(
            datasets_by_id.get("aerosors_ils", {}).get("available")
        )
        manifest["aeroSors"] = {
            "provider": "Aero.Sors / Hervé Sors",
            "listedCycle": listed_cycle_value,
            "importedAtUtc": imported_at,
            "purpose": "experimental_personal_development_test_only",
            "operationallyAvailable": False,
            "redistributionRights": "not_confirmed_for_derived_csv_exports",
            "notes": (
                "Published VOR/NDB and ILS spreadsheets are exported for FlightTempo "
                "development testing. The reviewed terms permit unchanged redistribution "
                "of the original package but do not expressly grant derivative CSV "
                "republication. Do not release commercially or to users without written "
                "permission. This is not an AIP or operational dataset."
            ),
        }
        manifest["generatedAtUtc"] = imported_at
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        source_manifest = {
            "provider": "Aero.Sors / Hervé Sors",
            "sourceHome": HOME,
            "listedCycle": listed_cycle_value,
            "exportedAtUtc": imported_at,
            "purpose": "experimental_personal_development_test_only",
            "operationallyAvailable": False,
            "redistributionRights": "not_confirmed_for_derived_csv_exports",
            "datasets": exports,
            "limitations": [
                "Only the published VOR/NDB and ILS spreadsheets are included; the full World FSXP3D BGL package is not parsed.",
                "Airport/runway BGL records, intersections/fixes and airway segments are not included in these two exports.",
                "All non-empty worksheet rows are preserved in raw_fields_json; canonical fields are populated only where headers are recognized.",
                "Coordinate values are mapped to decimal-degree fields only when the source cell is unambiguous; other coordinate formats remain in raw_fields_json.",
                "No SIDs, STARs or approaches are created.",
                "Not approved for operational use.",
            ],
        }
        metadata_path = root / "navigation/aerosors/source-manifest.json"
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(source_manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    if errors:
        logging.warning("Aero.Sors import completed with warnings: %s", "; ".join(errors))
        if not args.optional and len(exports) != len(SOURCES):
            raise RuntimeError("; ".join(errors))
    elif len(exports) != len(SOURCES) and not args.optional:
        raise RuntimeError("Aero.Sors export incomplete")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
