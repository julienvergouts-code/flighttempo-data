#!/usr/bin/env python3
"""Staging-only extraction of FAA CIFP procedure record headers.

Based on the FAA CIFP Readme record types (SIDs PD, STARs PE, approaches PF)
and verified against the staged 261126 FAACIFP18 fixed-width sample. This does
not decode ARINC leg semantics or publish app datasets.
"""
from __future__ import annotations
import argparse, json, zipfile
from collections import Counter
from pathlib import Path

RECORD_WIDTH = 132
PROCEDURE_CODES = {"D": "SID", "E": "STAR", "F": "APPROACH"}
AIRPORT_SECTION_SUBSECTION = "AP"


def parse_procedure_record(line: str, line_number: int) -> dict | None:
    if len(line) != RECORD_WIDTH:
        raise ValueError(f"Line {line_number}: expected {RECORD_WIDTH} columns, got {len(line)}")
    if line[0] != "S" or line[3:5] != AIRPORT_SECTION_SUBSECTION:
        return None
    kind = line[12]
    if kind not in PROCEDURE_CODES:
        return None
    airport = line[6:10].strip()
    procedure_id = line[13:19].strip()
    sequence_raw = line[26:29].strip()
    if not airport or not procedure_id:
        raise ValueError(f"Line {line_number}: procedure record has missing airport/procedure identifier")
    sequence = int(sequence_raw) if sequence_raw.isdigit() else None
    return {
        "sourceLine": line_number,
        "recordSection": line[3:5],
        "procedureTypeCode": kind,
        "procedureType": PROCEDURE_CODES[kind],
        "airportId": airport,
        "icaoRegion": line[10:12].strip(),
        "procedureIdentifier": procedure_id,
        "routeType": line[19:20].strip() or None,
        "routeQualifier": line[20:21].strip() or None,
        "transitionIdentifier": line[21:26].strip() or None,
        "sequenceNumber": sequence,
        "sequenceRaw": sequence_raw or None,
        "legFixIdentifier": line[29:34].strip() or None,
        "legFixRegion": line[34:36].strip() or None,
        "rawRecordIncluded": False,
        "decodeStatus": "header_fields_only_unvalidated_leg_semantics",
    }


def parse_file(path: Path, out_dir: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "procedure-records.ndjson"
    counts = Counter()
    airports = set()
    groups = set()
    width_counts = Counter()
    total = 0
    with path.open("r", encoding="ascii", newline="") as src, output.open("w", encoding="utf-8") as dst:
        for line_number, raw in enumerate(src, 1):
            line = raw.rstrip("\r\n")
            total += 1
            width_counts[len(line)] += 1
            if len(line) != RECORD_WIDTH:
                raise ValueError(f"Line {line_number}: expected {RECORD_WIDTH} columns, got {len(line)}")
            record = parse_procedure_record(line, line_number)
            if record is None:
                continue
            counts[record["procedureType"]] += 1
            airports.add(record["airportId"])
            groups.add((record["airportId"], record["procedureTypeCode"], record["procedureIdentifier"], record["routeType"], record["routeQualifier"], record["transitionIdentifier"]))
            dst.write(json.dumps(record, separators=(",", ":")) + "\n")
    if not counts:
        raise ValueError("No SID/STAR/approach records identified; refusing to produce empty output")
    summary = {
        "schemaVersion": 1,
        "sourceProvider": "FAA AeroNav CIFP",
        "sourceArchive": path.name,
        "sourceFile": path.name,
        "recordWidth": RECORD_WIDTH,
        "recordsScanned": total,
        "procedureRecordCounts": dict(sorted(counts.items())),
        "uniqueAirportIds": len(airports),
        "procedureTransitionGroups": len(groups),
        "stagedOutput": output.name,
        "outputRecords": sum(counts.values()),
        "conversionStatus": "partial_header_field_extraction",
        "legSemanticsDecoded": False,
        "appPublicationEnabled": False,
        "datasetReplacementEnabled": False,
        "notes": [
            "Record classification and header slices are staging-only.",
            "Leg types, path terminators, altitude/speed constraints, and ARINC 424 field semantics are not decoded.",
            "The FAA CIFP is U.S. coverage and should not be presented as global procedure coverage."
        ],
        "lineWidthDistribution": {str(k): v for k, v in sorted(width_counts.items())},
    }
    (out_dir / "procedure-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cifp_text", type=Path)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    summary = parse_file(args.cifp_text, args.output_dir)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
