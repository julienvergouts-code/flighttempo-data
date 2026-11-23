#!/usr/bin/env python3
"""Fail-closed audit of staged FAA CIFP ZIPs; does not convert or publish records.

ARINC 424 field mapping is intentionally not inferred here. This audit verifies
archive safety, text decoding, record-length distribution, and basic record
shape, producing an evidence report for parser-development validation.
"""
from __future__ import annotations
import argparse, hashlib, json, zipfile
from collections import Counter
from pathlib import Path

MAX_ARCHIVE_BYTES = 150_000_000
MAX_MEMBER_BYTES = 300_000_000
MAX_MEMBERS = 500
MAX_TEXT_MEMBER_BYTES = 100_000_000


def audit_archive(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("Archive is missing or empty")
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Archive exceeds configured maximum size")
    if not zipfile.is_zipfile(path):
        raise ValueError("Not a ZIP archive")
    members = []
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ValueError("Archive contains too many members")
        for info in infos:
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or any(part in {"..", ""} for part in name.split("/")[:-1]):
                raise ValueError(f"Unsafe archive path: {info.filename}")
            if info.file_size > MAX_MEMBER_BYTES:
                raise ValueError(f"Member too large: {name}")
            if info.is_dir():
                continue
            # Candidate CIFP text files: reasonably sized non-binary members.
            if info.file_size == 0:
                continue
            raw = zf.read(info)
            if len(raw) != info.file_size:
                raise ValueError(f"Member size mismatch: {name}")
            try:
                text = raw.decode("ascii")
            except UnicodeDecodeError:
                members.append({"name": name, "sizeBytes": len(raw), "classification": "non_ascii_or_binary", "sha256": hashlib.sha256(raw).hexdigest()})
                continue
            if len(raw) > MAX_TEXT_MEMBER_BYTES:
                raise ValueError(f"Text member too large to audit safely: {name}")
            lines = [line.rstrip("\r") for line in text.splitlines() if line.strip()]
            lengths = Counter(len(line) for line in lines)
            record_codes = Counter(line[:1] for line in lines if line)
            members.append({
                "name": name,
                "sizeBytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "classification": "ascii_text",
                "lineCount": len(lines),
                "lineLengthDistribution": {str(k): v for k, v in sorted(lengths.items())},
                "recordLeadingCharacterCounts": dict(sorted(record_codes.items())),
                "exact132CharacterLines": sum(v for k, v in lengths.items() if k == 132),
                "shortLinesUnder80": sum(v for k, v in lengths.items() if k < 80),
                "longLinesOver132": sum(v for k, v in lengths.items() if k > 132),
            })
    text_members = [m for m in members if m.get("classification") == "ascii_text" and m.get("lineCount", 0)]
    if not text_members:
        raise ValueError("ZIP contains no non-empty ASCII text member suitable for CIFP audit")
    return {
        "schemaVersion": 1,
        "stage": "audit_only_no_ARINC424_field_mapping",
        "archiveName": path.name,
        "archiveSizeBytes": path.stat().st_size,
        "archiveSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "zipIntegrity": "passed",
        "memberCount": len(members),
        "asciiTextMemberCount": len(text_members),
        "members": members,
        "conversionEnabled": False,
        "publicationEnabled": False,
        "limitations": [
            "This audit does not interpret ARINC 424 procedure fields.",
            "No CSVs or manifest entries are generated or replaced.",
            "Record format and field mapping require validated fixtures and regression checks."
        ]
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, default=Path("faa-cifp-audit.json"))
    args = parser.parse_args()
    report = audit_archive(args.archive)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\\n", encoding="utf-8")
    print(json.dumps({"archive": report["archiveName"], "sha256": report["archiveSha256"], "textMembers": report["asciiTextMemberCount"], "report": str(args.output), "conversionEnabled": False, "publicationEnabled": False}, indent=2))


if __name__ == "__main__":
    main()
