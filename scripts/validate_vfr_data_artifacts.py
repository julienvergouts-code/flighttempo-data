#!/usr/bin/env python3
"""Validate the published OFMA VFR reference CSV against its manifest."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "navigation_manifest.json"
META_PATH = ROOT / "data/ofma_ofmx_vfr_points_meta.json"
DATASET_ID = "ofma_ofmx_vfr_reference_points"


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
metadata = json.loads(META_PATH.read_text(encoding="utf-8"))
matches = [item for item in manifest.get("datasets", []) if item.get("id") == DATASET_ID]
if len(matches) != 1:
    fail(f"expected exactly one {DATASET_ID} dataset entry, found {len(matches)}")
dataset = matches[0]

if dataset.get("path") != "data/ofma_ofmx_vfr_points.csv":
    fail(f"unexpected manifest path: {dataset.get('path')!r}")
if dataset.get("available") is not True:
    fail("OFMA VFR dataset must be marked available")
if dataset.get("licenseStatus") != "commercial_use_permitted_subject_to_OFMA_GUL":
    fail("OFMA GUL license status is missing or unexpected")
if dataset.get("commercialUseAllowed") is not True:
    fail("commercial-use permission must remain explicitly recorded")
if dataset.get("downloadPurpose") != "reference_only" or dataset.get("operationallyAvailable") is not False:
    fail("OFMA data must remain reference-only and unavailable for operational use")
if not dataset.get("attribution") or not dataset.get("licenseConditions"):
    fail("OFMA attribution and license conditions must be preserved")

csv_path = ROOT / dataset["path"]
if not csv_path.is_file():
    fail(f"manifest dataset file is missing: {dataset['path']}")
raw = csv_path.read_bytes()
actual_size = len(raw)
actual_sha = hashlib.sha256(raw).hexdigest()
if actual_size != dataset.get("sizeBytes"):
    fail(f"manifest byte count mismatch: actual={actual_size} expected={dataset.get('sizeBytes')}")
if actual_sha != str(dataset.get("sha256", "")).lower():
    fail(f"manifest SHA-256 mismatch: actual={actual_sha} expected={dataset.get('sha256')}")

if actual_size != metadata.get("sizeBytes") or actual_sha != str(metadata.get("sha256", "")).lower():
    fail("OFMA metadata byte count or SHA-256 does not match the CSV")
if dataset.get("recordCount") != metadata.get("count"):
    fail("manifest recordCount does not match OFMA metadata count")
if dataset.get("dataCycle") != metadata.get("airac"):
    fail("manifest dataCycle does not match OFMA metadata AIRAC")

text = raw.decode("utf-8-sig")
# The generated CSV intentionally begins with a #version metadata line.
data_lines = [line for line in text.splitlines() if line and not line.startswith("#")]
if not data_lines:
    fail("CSV contains no header or data")
reader = csv.DictReader(io.StringIO("\n".join(data_lines)))
required = {"point_id", "code", "lat", "lon", "kind", "source", "license", "cycle"}
if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
    fail(f"CSV is missing required columns: {sorted(required - set(reader.fieldnames or []))}")

count = 0
for line_number, row in enumerate(reader, start=2):
    count += 1
    if not (row.get("point_id") or "").strip() or not (row.get("code") or "").strip():
        fail(f"row {line_number}: empty point_id or code")
    try:
        lat = float(row["lat"])
        lon = float(row["lon"])
    except (TypeError, ValueError):
        fail(f"row {line_number}: invalid latitude/longitude")
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        fail(f"row {line_number}: coordinates outside valid bounds")
    if row["source"] != "OFMA" or row["license"] != "OFMA_GUL":
        fail(f"row {line_number}: missing OFMA source/license provenance")
    if row["cycle"] != str(metadata["airac"]):
        fail(f"row {line_number}: cycle differs from metadata AIRAC")

if count == 0 or count != dataset.get("recordCount"):
    fail(f"CSV row count mismatch: actual={count} expected={dataset.get('recordCount')}")
if manifest.get("statistics", {}).get("ofmaOfmxVfrReferencePoints") != count:
    fail("manifest statistics count does not match the CSV")

print(
    f"OFMA VFR artifact valid: {count} rows, AIRAC {metadata['airac']}, "
    f"{actual_size} bytes, SHA-256 {actual_sha}"
)
