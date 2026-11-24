#!/usr/bin/env python3
"""Validate every downloadable CSV declared by navigation_manifest.json.

This checks package integrity and CSV structure. It does not certify the
accuracy, currency, licensing or operational suitability of any source.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path


def parse_csv_bytes(raw: bytes, label: str = "<csv>") -> tuple[list[str], int]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label}: CSV is not valid UTF-8: {exc}") from exc

    # The first non-metadata line is the header in every app-facing export.
    # Detect only the two delimiters used in this repository from that header;
    # csv.Sniffer can misidentify quote characters when later text fields
    # contain punctuation or semicolons.
    header_line = next(
        (
            line for line in text.splitlines()
            if line.strip()
            and not line.lstrip().lower().startswith(("sep=", "#version"))
        ),
        "",
    )
    if not header_line:
        raise ValueError(f"{label}: no CSV header found")
    delimiter = ";" if header_line.count(";") > header_line.count(",") else ","

    # Feed the complete text stream to csv.reader. Splitting into physical
    # lines first corrupts valid CSV fields that contain quoted newlines.
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, quotechar='"')
    header = None
    for row in reader:
        if not row or not any(cell.strip() for cell in row):
            continue
        first = row[0].strip().lower()
        if first.startswith("sep=") or first.startswith("#version"):
            continue
        if first == "#columns":
            row = row[1:]
        header = [column.strip() for column in row]
        break

    if not header or not any(header):
        raise ValueError(f"{label}: empty CSV header")
    if len(set(header)) != len(header):
        raise ValueError(f"{label}: duplicate CSV column names")

    count = 0
    for row_number, row in enumerate(reader, start=2):
        if not row or not any(cell.strip() for cell in row):
            continue
        first = row[0].lstrip().lower()
        if first.startswith("sep=") or first.startswith("#version") or first.startswith("#"):
            continue
        if len(row) != len(header):
            raise ValueError(
                f"{label}: record {row_number} has {len(row)} fields; "
                f"expected {len(header)}"
            )
        count += 1
    return header, count

def validate_dataset(root: Path, dataset: dict) -> dict:
    relative = dataset.get("path")
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"{dataset.get('id', '<unknown>')}: missing path")

    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{relative}: path escapes repository root") from exc

    if not path.is_file():
        raise ValueError(f"{relative}: manifest file does not exist")

    raw = path.read_bytes()
    expected_size = dataset.get("sizeBytes")
    if expected_size is not None and len(raw) != int(expected_size):
        raise ValueError(
            f"{relative}: size mismatch: {len(raw)} != {expected_size}"
        )

    digest = hashlib.sha256(raw).hexdigest()
    expected_digest = dataset.get("sha256")
    if expected_digest and digest.lower() != str(expected_digest).lower():
        raise ValueError(f"{relative}: SHA-256 mismatch")

    result = {
        "id": dataset.get("id", relative),
        "path": relative,
        "sizeBytes": len(raw),
        "sha256": digest,
    }

    if path.suffix.lower() == ".csv":
        header, count = parse_csv_bytes(raw, relative)
        expected_count = dataset.get("recordCount")
        if expected_count is not None and count != int(expected_count):
            raise ValueError(
                f"{relative}: record-count mismatch: {count} != {expected_count}"
            )
        result.update({"recordCount": count, "columnCount": len(header)})
    return result


try:
    from .commercial_rights import personal_scope_active, redistribution_block_reason
except ImportError:
    from commercial_rights import personal_scope_active, redistribution_block_reason


def validate_manifest(root: Path, manifest_path: Path) -> list[dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    datasets = manifest.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError("Manifest datasets must be an array")

    results = []
    for dataset in datasets:
        if not isinstance(dataset, dict):
            raise ValueError("Manifest dataset entry must be an object")
        blocked_reason = redistribution_block_reason(dataset, personal_scope_active())
        if dataset.get("available", False) and "ofma_gul" in str(dataset.get("licenseStatus", "")).lower():
            if not dataset.get("commercialUseAllowed") or not dataset.get("licenseUrl") or not dataset.get("attribution"):
                raise ValueError(
                    f"{dataset.get('id', dataset.get('path'))}: OFMA GUL data must declare "
                    "commercial permission, licence URL and attribution before download"
                )
        if dataset.get("available", False) and blocked_reason:
            raise ValueError(
                f"{dataset.get('id', dataset.get('path'))}: marked downloadable "
                f"despite restricted/unconfirmed rights ({blocked_reason})"
            )
        if not dataset.get("available", False):
            if dataset.get("downloadUrl"):
                raise ValueError(
                    f"{dataset.get('id', dataset.get('path'))}: unavailable dataset "
                    "must not retain a downloadUrl"
                )
            continue
        relative = str(dataset.get("path", ""))
        if relative.lower().endswith(".csv"):
            results.append(validate_dataset(root, dataset))
    if not results:
        raise ValueError("No available CSV datasets were validated")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path, default=Path("navigation_manifest.json"))
    args = parser.parse_args()
    manifest_path = args.manifest if args.manifest.is_absolute() else args.root / args.manifest
    results = validate_manifest(args.root, manifest_path)
    for item in results:
        print(
            f"{item['id']}: {item.get('recordCount', 'n/a')} records, "
            f"{item['columnCount'] if 'columnCount' in item else 'binary'} columns, "
            f"{item['sizeBytes']} bytes, SHA-256 OK"
        )
    print(f"Validated {len(results)} downloadable CSV datasets.")


if __name__ == "__main__":
    main()
