#!/usr/bin/env python3
"""Extract structured IFR procedure legs from official French SIA AIP DATA PDFs.

The importer deliberately stores published leg attributes without generating
coordinates, paths, or missing constraints. Optional fix coordinates are linked
only when a supplied source-backed fix file has exactly one matching ident.
This is reference-data ingestion for simulator development, not an operational
navigation database.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FIELDS = [
    "country", "airport_icao", "procedure_type", "procedure_identifier",
    "procedure_selector", "leg_sequence_label", "leg_number",
    "path_terminator", "waypoint_ident", "fly_over",
    "magnetic_course_deg", "true_course_deg", "distance_nm", "turn_direction",
    "minimum_altitude_raw", "maximum_altitude_raw", "maximum_ias_kt",
    "vertical_angle_tch_raw", "navigation_accuracy_nm",
    "fix_latitude", "fix_longitude", "fix_resolution",
    "source_provider", "source_license", "source_file", "source_url",
    "source_document_date", "airac_effective_date", "source_sha256",
    "raw_row_json",
]

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def clean(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\n", " ").replace("\r", " ")).strip()


def normalise_header(value: str) -> str:
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def header_key(value: str) -> str | None:
    text = normalise_header(value)
    if "path terminator" in text:
        return "path_terminator"
    if "waypoint identification" in text or text in {"waypoint", "waypoint ident"}:
        return "waypoint_ident"
    if "fly over" in text:
        return "fly_over"
    if "direction mag" in text or "magnetic direction" in text:
        return "magnetic_course_deg"
    if "direction true" in text or "true direction" in text:
        return "true_course_deg"
    if "distance" in text and ("nm" in text or text == "distance"):
        return "distance_nm"
    if "turn direction" in text:
        return "turn_direction"
    if ("mnm altitude" in text or "min altitude" in text or "minimum altitude" in text
            or "min level" in text):
        return "minimum_altitude_raw"
    if "max altitude" in text or "maximum altitude" in text or "max level" in text:
        return "maximum_altitude_raw"
    if "max ias" in text or "maximum ias" in text:
        return "maximum_ias_kt"
    if "navigation accuracy" in text or "nav spec" in text:
        return "navigation_accuracy_nm"
    if "vertical angle" in text or "tch" in text:
        return "vertical_angle_tch_raw"
    if "leg sequence" in text:
        return "leg_sequence_label"
    if "procedure identification" in text:
        return "procedure_selector"
    if text == "rmk":
        return "remark"
    return None


def identify_table_header(row: list[str]) -> dict[str, int] | None:
    mapped = {}
    for index, value in enumerate(row):
        key = header_key(value)
        if key and key not in mapped:
            mapped[key] = index
    required = {"path_terminator", "waypoint_ident", "fly_over"}
    if required.issubset(mapped) and (
        "magnetic_course_deg" in mapped or "true_course_deg" in mapped
    ):
        return mapped
    return None


def parse_doc_identity(path: Path) -> tuple[str, str] | None:
    name = path.stem.upper()
    match = re.match(r"AD_2_([A-Z0-9]{4})_DATA_(.+)", name)
    if not match:
        return None
    airport = match.group(1)
    remainder = match.group(2)
    if remainder.startswith("SID_"):
        return airport, "SID"
    if remainder.startswith("STAR_"):
        return airport, "STAR"
    # A complete RNAV/RNP approach DATA sheet is distinct from an FNA-only
    # final-approach precoding sheet. FNA and RNP FASDB sheets are excluded.
    if remainder.startswith("RWY") and "RNP_CODE" in remainder and "_FNA_" not in remainder:
        return airport, "APPROACH"
    return None


def parse_aip_date(text: str) -> str:
    match = re.search(r"\b(\d{1,2})\s+([A-Z]{3})\s+(\d{4})\b", text.upper())
    if not match:
        return ""
    day, month_name, year = match.groups()
    month = MONTHS.get(month_name)
    if not month:
        return ""
    try:
        return datetime(int(year), month, int(day)).date().isoformat()
    except ValueError:
        return ""


def cell(row: list[str], mapping: dict[str, int], key: str) -> str:
    index = mapping.get(key)
    if index is None or index >= len(row):
        return ""
    return clean(row[index])


def _single_nonempty_cell(row: list[str]) -> str:
    nonempty = [clean(v) for v in row if clean(v)]
    return nonempty[0] if len(nonempty) == 1 else ""


def parse_table_rows(
    table: list[list[str | None]],
    *,
    airport_icao: str,
    procedure_type: str,
    source_file: str,
    source_url: str,
    source_document_date: str,
    airac_effective_date: str,
    source_sha256: str,
    fix_index: dict[str, list[tuple[str, str]]] | None = None,
) -> list[dict[str, str]]:
    """Convert one pdfplumber table to row-preserving procedure-leg records."""
    rows = [[clean(v) for v in (row or [])] for row in table]
    header_at = None
    mapping = None
    for index, row in enumerate(rows):
        candidate = identify_table_header(row)
        if candidate:
            header_at, mapping = index, candidate
            break
    if mapping is None or header_at is None:
        return []

    records: list[dict[str, str]] = []
    active_procedure = ""
    leg_number = 0
    for raw_row in rows[header_at + 1:]:
        if not any(raw_row):
            continue
        # A merged heading row (e.g. "BAXIR 7B") names the procedure branch.
        heading = _single_nonempty_cell(raw_row)
        if heading:
            h = normalise_header(heading)
            if h not in {"sid rnav", "star rnav", "procedure identification"}:
                active_procedure = heading
                leg_number = 0
            continue

        waypoint = cell(raw_row, mapping, "waypoint_ident")
        path_terminator = cell(raw_row, mapping, "path_terminator").upper()
        if not waypoint or not path_terminator:
            continue
        leg_number += 1

        selector = cell(raw_row, mapping, "procedure_selector")
        sequence = cell(raw_row, mapping, "leg_sequence_label")
        # For SID/STAR sheets, the selector cell usually identifies a runway
        # row or contains '-'. Preserve it verbatim; '-' means shared/unspecified
        # scope and is never expanded into multiple synthetic runway branches.
        selector = "" if selector == "-" else selector

        fix_matches = (fix_index or {}).get(waypoint.upper(), [])
        if len(fix_matches) == 1:
            fix_lat, fix_lon = fix_matches[0]
            fix_resolution = "unique_source_fix"
        elif len(fix_matches) > 1:
            fix_lat, fix_lon, fix_resolution = "", "", "ambiguous_source_fix"
        else:
            fix_lat, fix_lon, fix_resolution = "", "", "not_linked"

        raw_values = {
            "procedure_heading": active_procedure,
            "table_row": raw_row,
            "table_header": list(mapping.keys()),
        }
        records.append({
            "country": "FR",
            "airport_icao": airport_icao,
            "procedure_type": procedure_type,
            "procedure_identifier": active_procedure,
            "procedure_selector": selector,
            "leg_sequence_label": sequence,
            "leg_number": str(leg_number),
            "path_terminator": path_terminator,
            "waypoint_ident": waypoint.upper(),
            "fly_over": cell(raw_row, mapping, "fly_over"),
            "magnetic_course_deg": cell(raw_row, mapping, "magnetic_course_deg"),
            "true_course_deg": cell(raw_row, mapping, "true_course_deg"),
            "distance_nm": cell(raw_row, mapping, "distance_nm"),
            "turn_direction": cell(raw_row, mapping, "turn_direction"),
            "minimum_altitude_raw": cell(raw_row, mapping, "minimum_altitude_raw"),
            "maximum_altitude_raw": cell(raw_row, mapping, "maximum_altitude_raw"),
            "maximum_ias_kt": cell(raw_row, mapping, "maximum_ias_kt"),
            "vertical_angle_tch_raw": cell(raw_row, mapping, "vertical_angle_tch_raw"),
            "navigation_accuracy_nm": cell(raw_row, mapping, "navigation_accuracy_nm"),
            "fix_latitude": fix_lat,
            "fix_longitude": fix_lon,
            "fix_resolution": fix_resolution,
            "source_provider": "Service de l'Information Aeronautique (SIA France)",
            "source_license": "Licence Ouverte / Open Licence (Etalab)",
            "source_file": source_file,
            "source_url": source_url,
            "source_document_date": source_document_date,
            "airac_effective_date": airac_effective_date,
            "source_sha256": source_sha256,
            "raw_row_json": json.dumps(raw_values, ensure_ascii=False, separators=(",", ":")),
        })
    return records


def load_fix_index(path: Path | None) -> dict[str, list[tuple[str, str]]]:
    index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    if path is None:
        return index
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"ident", "latitude", "longitude"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError("Fix CSV must contain ident, latitude and longitude columns")
        for row in reader:
            ident = clean(row.get("ident", "")).upper()
            lat, lon = clean(row.get("latitude", "")), clean(row.get("longitude", ""))
            if ident and lat and lon:
                index[ident].append((lat, lon))
    return index


def pdf_tables(path: Path) -> tuple[list[list[list[str | None]]], str]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError(
            "pdfplumber is required; install with: pip install -r requirements-sia-procedures.txt"
        ) from exc

    tables: list[list[list[str | None]]] = []
    document_text = []
    settings_candidates = [
        {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "snap_tolerance": 4,
            "join_tolerance": 4,
            "intersection_tolerance": 5,
            "edge_min_length": 3,
        },
        {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "min_words_vertical": 1,
            "min_words_horizontal": 1,
            "snap_tolerance": 3,
            "join_tolerance": 3,
        },
    ]
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            document_text.append(page.extract_text() or "")
            page_tables: list[list[list[str | None]]] = []
            for settings in settings_candidates:
                try:
                    candidate = page.extract_tables(table_settings=settings) or []
                except Exception:
                    candidate = []
                if any(identify_table_header([clean(v) for v in row]) for table in candidate for row in table):
                    page_tables = candidate
                    break
            tables.extend(page_tables)
    return tables, "\n".join(document_text)


def source_url_for(base_url: str, airport: str, filename: str) -> str:
    if not base_url:
        return ""
    return f"{base_url.rstrip('/')}/{airport}/{filename}"


def read_files(args) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    fix_index = load_fix_index(args.fixes_csv)
    all_rows: list[dict[str, str]] = []
    source_records: list[dict[str, str]] = []
    pdf_paths = sorted(args.pdf_dir.glob("*.pdf"))
    for path in pdf_paths:
        identity = parse_doc_identity(path)
        if identity is None:
            continue
        airport, procedure_type = identity
        tables, text = pdf_tables(path)
        doc_date = parse_aip_date(text)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        source_url = source_url_for(args.source_base_url, airport, path.name)
        rows_for_file = []
        for table in tables:
            rows_for_file.extend(parse_table_rows(
                table,
                airport_icao=airport,
                procedure_type=procedure_type,
                source_file=path.name,
                source_url=source_url,
                source_document_date=doc_date,
                airac_effective_date=args.airac_effective_date,
                source_sha256=digest,
                fix_index=fix_index,
            ))
        if not rows_for_file:
            source_records.append({
                "source_file": path.name,
                "airport_icao": airport,
                "procedure_type": procedure_type,
                "status": "no_recognised_leg_table",
                "record_count": 0,
                "sha256": digest,
                "document_date": doc_date,
                "source_url": source_url,
            })
            continue
        all_rows.extend(rows_for_file)
        source_records.append({
            "source_file": path.name,
            "airport_icao": airport,
            "procedure_type": procedure_type,
            "status": "parsed_not_independently_validated",
            "record_count": len(rows_for_file),
            "sha256": digest,
            "document_date": doc_date,
            "source_url": source_url,
        })
    return all_rows, source_records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", type=Path, required=True, help="Directory containing SIA DATA PDF files")
    parser.add_argument("--airac-effective-date", required=True, help="AIP package effective date YYYY-MM-DD")
    parser.add_argument("--output", type=Path, required=True, help="Output CSV path")
    parser.add_argument("--manifest", type=Path, help="Optional JSON provenance report path")
    parser.add_argument("--fixes-csv", type=Path, help="Optional source-backed fix file with ident/latitude/longitude")
    parser.add_argument(
        "--source-base-url",
        default="",
        help="Official AIP Cartes base URL before /{ICAO}/{filename}",
    )
    args = parser.parse_args()

    if not args.pdf_dir.is_dir():
        parser.error(f"PDF input directory does not exist: {args.pdf_dir}")
    try:
        datetime.strptime(args.airac_effective_date, "%Y-%m-%d")
    except ValueError:
        parser.error("--airac-effective-date must be YYYY-MM-DD")

    rows, sources = read_files(args)
    if not rows:
        print("No recognised SID/STAR/complete RNP approach leg tables were extracted; output not written.", file=sys.stderr)
        for source in sources:
            print(json.dumps(source, ensure_ascii=False), file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "schemaVersion": 1,
            "provider": "Service de l'Information Aeronautique (SIA France)",
            "license": "Licence Ouverte / Open Licence (Etalab)",
            "attribution": "Service de l'Information Aeronautique (SIA France); include the source and last update date.",
            "airacEffectiveDate": args.airac_effective_date,
            "status": "parsed_not_independently_validated",
            "operationallyAvailable": False,
            "procedureCapabilitiesEnabled": False,
            "recordCount": len(rows),
            "airportCount": len({row["airport_icao"] for row in rows}),
            "procedureTypeCounts": {
                kind: sum(row["procedure_type"] == kind for row in rows)
                for kind in sorted({row["procedure_type"] for row in rows})
            },
            "sourceDocuments": sources,
            "notes": [
                "Leg attributes are transcribed from SIA AIP DATA tables.",
                "Fix coordinates are linked only when a supplied fix source has a unique exact ident match.",
                "Shared/blank runway selectors are preserved and are not expanded into guessed branches.",
                "Missing values remain blank; no synthetic route legs or constraints are generated.",
                "Source charts, AIP text, fix coordinates, procedure sequencing and cycle validity require review before wider release.",
                "This dataset is not an operational navigation source.",
            ],
        }
        args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "output": str(args.output),
        "recordCount": len(rows),
        "airportCount": len({row["airport_icao"] for row in rows}),
        "procedureTypes": sorted({row["procedure_type"] for row in rows}),
        "sourceDocumentsParsed": sum(s["record_count"] > 0 for s in sources),
        "sourceDocumentsSkipped": sum(s["record_count"] == 0 for s in sources),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
