#!/usr/bin/env python3
"""Read-only inventory of OFMX/OFMX-like XML package feature types.

This is an exploratory audit tool, NOT a navigation-data importer. It never
writes source files or extracts operational data. Reports counts and XML tag
inventory only, with package hashes and bounded parsing safeguards.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_MEMBER_BYTES = 80 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024
MAX_MEMBERS = 5000
MAX_XML_BYTES = 80 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def inventory_xml(data: bytes) -> dict:
    # ElementTree does not resolve external entities; reject DTD/entity declarations
    # as an additional guard for untrusted aviation-source archives.
    upper = data[: min(len(data), 1024 * 1024)].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("DTD/entity declaration rejected")
    root = ET.fromstring(data)
    tags = Counter(local_name(node.tag) for node in root.iter())
    feature_counts = Counter()
    geometry_tags = Counter()
    coordinate_like = Counter()
    for node in root.iter():
        name = local_name(node.tag)
        # Report likely object/features, but do not assume these names are schema
        # classes or semantically equivalent across OFMX revisions.
        if len(node) or node.attrib:
            feature_counts[name] += 1
        if name.lower() in {"geo", "geometry", "polygon", "point", "line", "arc", "circle", "gml"}:
            geometry_tags[name] += 1
        for attr in node.attrib:
            a = local_name(attr).lower()
            if a in {"lat", "latitude", "lon", "long", "longitude", "geo", "coordinates", "coordinate"}:
                coordinate_like[a] += 1
    return {
        "root": local_name(root.tag),
        "namespace": root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else None,
        "tagCounts": dict(sorted(tags.items())),
        "objectCandidateCounts": dict(sorted(feature_counts.items())),
        "geometryTagCounts": dict(sorted(geometry_tags.items())),
        "coordinateAttributeCounts": dict(sorted(coordinate_like.items())),
    }


def audit_zip(path: Path) -> dict:
    package_sha = sha256_file(path)
    result = {"package": path.name, "sha256": package_sha, "memberReports": [], "errors": []}
    try:
        with zipfile.ZipFile(path) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if len(members) > MAX_MEMBERS:
                raise ValueError(f"archive member limit exceeded ({len(members)} > {MAX_MEMBERS})")
            total = sum(m.file_size for m in members)
            if total > MAX_TOTAL_BYTES:
                raise ValueError(f"uncompressed archive size exceeds limit ({total} bytes)")
            for member in members:
                name = member.filename
                if not name.lower().endswith((".xml", ".ofmx")):
                    continue
                if member.file_size > MAX_MEMBER_BYTES:
                    result["errors"].append({"member": name, "error": "member size limit exceeded"})
                    continue
                try:
                    raw = archive.read(member)
                    if len(raw) > MAX_XML_BYTES:
                        raise ValueError("XML byte limit exceeded")
                    report = inventory_xml(raw)
                    report.update({"member": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
                    result["memberReports"].append(report)
                except Exception as exc:  # per-member audit should continue
                    result["errors"].append({"member": name, "error": str(exc)})
    except Exception as exc:
        result["errors"].append({"archive": str(exc)})
    return result


def audit_path(path: Path) -> dict:
    if path.is_file() and path.suffix.lower() in {".zip"}:
        return audit_zip(path)
    if path.is_file() and path.suffix.lower() in {".xml", ".ofmx"}:
        raw = path.read_bytes()
        return {"file": path.name, "sha256": hashlib.sha256(raw).hexdigest(), **inventory_xml(raw)}
    if path.is_dir():
        reports = []
        for candidate in sorted(path.rglob("*")):
            if candidate.is_file() and candidate.suffix.lower() in {".zip", ".xml", ".ofmx"}:
                reports.append(audit_path(candidate))
        return {"directory": str(path), "reports": reports}
    raise ValueError(f"Unsupported input: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="OFMX ZIP, XML/OFMX file, or directory")
    parser.add_argument("--output", type=Path, help="Write JSON report (default: stdout)")
    args = parser.parse_args()
    report = audit_path(args.input)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
