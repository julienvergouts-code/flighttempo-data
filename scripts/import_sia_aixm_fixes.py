#!/usr/bin/env python3
"""Export France SIA AIXM 4.5 designated points as an auditable fix CSV.

Only explicitly published WGS-84 (WGE) DPN coordinates are emitted. Duplicate
identifiers are retained so the procedure importer can mark them ambiguous
instead of choosing one. This tool does not infer coordinates from route tracks.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

FIELDS = [
    "ident", "latitude", "longitude", "code_type", "name", "remarks",
    "airport_icao_association", "datum", "source_provider", "source_file",
    "source_sha256",
]


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def find_text(element: ET.Element, name: str) -> str:
    for child in element.iter():
        if local_name(child.tag) == name and child.text and child.text.strip():
            return child.text.strip()
    return ""


def parse_aixm_coordinate(value: str, axis: str) -> str:
    """Convert AIXM DDMMSS.sH / DDDMMSS.sH into signed decimal degrees."""
    value = re.sub(r"\s+", "", value or "").upper()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([NSEW])", value)
    if not match:
        raise ValueError(f"Invalid AIXM coordinate: {value!r}")
    body, hemisphere = match.groups()
    degree_digits = 2 if axis == "lat" else 3
    if len(body) < degree_digits + 4:
        raise ValueError(f"Coordinate has too few digits: {value!r}")
    degrees = int(body[:degree_digits])
    minutes = int(body[degree_digits:degree_digits + 2])
    seconds = float(body[degree_digits + 2:])
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"Invalid minutes/seconds in coordinate: {value!r}")
    limit = 90 if axis == "lat" else 180
    if degrees > limit or (degrees == limit and (minutes or seconds)):
        raise ValueError(f"Coordinate outside {axis} range: {value!r}")
    decimal = degrees + minutes / 60.0 + seconds / 3600.0
    if hemisphere in {"S", "W"}:
        decimal = -decimal
    return f"{decimal:.8f}".rstrip("0").rstrip(".")


def iter_aixm_stream(path: Path):
    if path.suffix.lower() == ".zip":
        archive = zipfile.ZipFile(path)
        candidates = [
            name for name in archive.namelist()
            if name.upper().startswith("AIXM4.5") and name.lower().endswith(".xml")
        ]
        if len(candidates) != 1:
            archive.close()
            raise ValueError(
                f"Expected exactly one AIXM4.5 XML member in {path.name}; found {len(candidates)}"
            )
        handle = archive.open(candidates[0])
        return archive, handle, candidates[0]
    handle = path.open("rb")
    return None, handle, path.name


def extract_points(path: Path) -> tuple[list[dict[str, str]], str, str]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    archive, stream, member_name = iter_aixm_stream(path)
    points = []
    try:
        for event, element in ET.iterparse(stream, events=("end",)):
            if local_name(element.tag) != "Dpn":
                continue
            ident = find_text(element, "codeId").upper()
            lat_raw = find_text(element, "geoLat")
            lon_raw = find_text(element, "geoLong")
            datum = find_text(element, "codeDatum").upper()
            code_type = find_text(element, "codeType").upper()
            if not ident or not lat_raw or not lon_raw:
                element.clear()
                continue
            if datum not in {"WGE", "WGS84", "WGS 84"}:
                element.clear()
                continue
            try:
                latitude = parse_aixm_coordinate(lat_raw, "lat")
                longitude = parse_aixm_coordinate(lon_raw, "lon")
            except ValueError:
                element.clear()
                continue
            association = ""
            for child in element.iter():
                if local_name(child.tag) == "AhpUidAssoc":
                    association = find_text(child, "codeId").upper()
                    break
            points.append({
                "ident": ident,
                "latitude": latitude,
                "longitude": longitude,
                "code_type": code_type,
                "name": find_text(element, "txtName"),
                "remarks": find_text(element, "txtRmk"),
                "airport_icao_association": association,
                "datum": "WGS84",
                "source_provider": "Service de l'Information Aeronautique (SIA France)",
                "source_file": f"{path.name}:{member_name}",
                "source_sha256": digest,
            })
            element.clear()
    finally:
        stream.close()
        if archive is not None:
            archive.close()
    return points, digest, member_name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="AIXM4.5 XML file or SIA ZIP export")
    parser.add_argument("--output", type=Path, required=True, help="Output fix CSV path")
    parser.add_argument("--manifest", type=Path, help="Optional provenance JSON path")
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"Input file does not exist: {args.input}")
    try:
        points, digest, member = extract_points(args.input)
    except (OSError, zipfile.BadZipFile, ET.ParseError, ValueError) as exc:
        print(f"Unable to parse SIA AIXM fix source: {exc}", file=sys.stderr)
        return 2
    if not points:
        print("No WGS-84 DPN designated points were extracted; output not written.", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(points)

    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps({
            "schemaVersion": 1,
            "sourceProvider": "Service de l'Information Aeronautique (SIA France)",
            "license": "Licence Ouverte / Open Licence (Etalab)",
            "sourceFile": args.input.name,
            "sourceMember": member,
            "sha256": digest,
            "recordCount": len(points),
            "uniqueIdentifierCount": len({p["ident"] for p in points}),
            "ambiguousIdentifierCount": len({
                ident for ident in {p["ident"] for p in points}
                if sum(p2["ident"] == ident for p2 in points) > 1
            }),
            "status": "reference_fix_dataset_not_operationally_validated",
            "attribution": "Service de l'Information Aeronautique (SIA France); cite the source and last update date.",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "output": str(args.output),
        "recordCount": len(points),
        "uniqueIdentifierCount": len({p["ident"] for p in points}),
        "ambiguousIdentifierCount": len({
            ident for ident in {p["ident"] for p in points}
            if sum(p2["ident"] == ident for p2 in points) > 1
        }),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
