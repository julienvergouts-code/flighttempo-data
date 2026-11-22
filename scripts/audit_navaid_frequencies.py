#!/usr/bin/env python3
"""Non-destructive frequency plausibility audit for OurAirports navaids.

This is a QA flagger, not an authority or correction engine. Source records are
retained unchanged; out-of-range/missing frequencies are reported for review.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Source frequency field is in kHz. Audit only frequency families with clear
# expected ranges; DME/TACAN channel encoding varies and is intentionally not
# judged by this lightweight audit.
RANGES_KHZ = {
    "VOR": (108000, 117950),
    "VOR-DME": (108000, 117950),
    "VORTAC": (108000, 117950),
    "NDB": (190, 1750),
    "NDB-DME": (190, 1750),
}
REQUIRED_COLUMNS = {"ident", "type", "frequency_khz", "latitude_deg", "longitude_deg"}

def audit_rows(rows: list[dict]) -> dict:
    counts = Counter()
    anomalies = []
    seen = set()
    duplicates = 0
    for line, row in enumerate(rows, start=2):
        ident = (row.get("ident") or "").strip().upper()
        kind = (row.get("type") or "").strip().upper()
        counts[kind or "UNKNOWN"] += 1
        if not ident or not kind:
            anomalies.append({"line": line, "ident": ident, "type": kind, "issue": "missing_ident_or_type"})
            continue
        key = (ident, kind, (row.get("frequency_khz") or "").strip(),
               (row.get("latitude_deg") or "").strip(), (row.get("longitude_deg") or "").strip())
        if key in seen:
            duplicates += 1
        seen.add(key)
        if kind not in RANGES_KHZ:
            continue
        low, high = RANGES_KHZ[kind]
        raw = (row.get("frequency_khz") or "").strip()
        if not raw:
            anomalies.append({"line": line, "ident": ident, "type": kind, "issue": "missing_frequency"})
            continue
        try:
            freq = float(raw)
        except ValueError:
            anomalies.append({"line": line, "ident": ident, "type": kind, "frequency_khz": raw, "issue": "non_numeric_frequency"})
            continue
        if not math.isfinite(freq) or not low <= freq <= high:
            anomalies.append({"line": line, "ident": ident, "type": kind, "frequency_khz": raw,
                              "expected_khz": [low, high], "issue": "frequency_out_of_range"})
    return {
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "auditType": "source_frequency_plausibility_only",
        "source": "OurAirports",
        "sourceLicense": "Public Domain as stated by OurAirports",
        "operationalUse": False,
        "recordsAudited": len(rows),
        "typeCounts": dict(sorted(counts.items())),
        "identicalDuplicateRecords": duplicates,
        "anomalyCount": len(anomalies),
        "anomalies": anomalies,
        "note": "Flags do not prove a record is wrong. Do not auto-correct or delete source records based on this audit."
    }

def audit_file(input_path: Path) -> dict:
    with input_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - fields
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")
        return audit_rows(list(reader))

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("navigation/navaids/navaids.csv"))
    parser.add_argument("--output", type=Path, default=Path("navaid_frequency_audit.json"))
    args = parser.parse_args()
    report = audit_file(args.input)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Navaid frequency audit: {report['recordsAudited']} records; {report['anomalyCount']} review flags; {report['identicalDuplicateRecords']} identical duplicates")
    for item in report["anomalies"][:25]:
        print(f"REVIEW line {item['line']} {item.get('ident')} {item.get('type')}: {item['issue']} {item.get('frequency_khz','')}")
    if len(report["anomalies"]) > 25:
        print(f"... {len(report['anomalies']) - 25} more flags in {args.output}")
    print(f"Audit report: {args.output}")

if __name__ == "__main__":
    main()
