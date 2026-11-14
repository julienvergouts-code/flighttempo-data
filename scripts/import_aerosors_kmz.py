#!/usr/bin/env python3
"""Export Aero.Sors Google Earth KMZ layers to experimental FlightTempo CSVs.

The KMZ/KML source is parsed as-is. Every Placemark is kept; point coordinates
are decoded only from KML Point geometry, while non-point/empty geometries remain
metadata-only records with original ExtendedData and description preserved.
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
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
import xml.etree.ElementTree as ET

HOME = "https://www.aero.sors.fr/index.html"
REFERER = "https://www.aero.sors.fr/GE.html"
SOURCES = {
    "aerosors_ge_navaids": {
        "url": "https://www.aero.sors.fr/hfiles/GENavaids.kmz",
        "page": REFERER,
        "path": "navigation/aerosors/ge_navaids.csv",
        "coverage": "Worldwide navaids Google Earth layer published by Aero.Sors",
        "kind": "NAVAID",
    },
    "aerosors_ge_airports": {
        "url": "https://www.aero.sors.fr/hfiles/GEAirports.kmz",
        "page": REFERER,
        "path": "navigation/aerosors/ge_airports.csv",
        "coverage": "Worldwide airports Google Earth layer published by Aero.Sors",
        "kind": "AIRPORT",
    },
}
FIELDS = [
    "source_file", "source_folder", "source_placemark", "source_cycle",
    "record_type", "record_status", "ident", "name", "facility_type",
    "airport_icao", "runway", "frequency", "frequency_unit",
    "latitude_deg", "longitude_deg", "altitude_m", "geometry_type",
    "description", "extended_data_json", "coordinates_raw",
]
ALIASES = {
    "ident": {"ident", "identifier", "identification", "id", "navaid_id", "loc_ident", "localizer_ident", "code"},
    "facility_type": {"type", "navaid_type", "facility_type", "aid_type", "class", "kind"},
    "airport_icao": {"airport", "airport_icao", "icao", "icao_code", "airport_id", "apt_icao"},
    "runway": {"runway", "runway_id", "rwy", "rwy_id", "runway_ident"},
    "frequency": {"frequency", "freq", "frequency_mhz", "freq_mhz", "frequency_khz", "freq_khz"},
    "frequency_unit": {"frequency_unit", "freq_unit", "unit"},
}


def text_of(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join(part.strip() for part in element.itertext() if part and part.strip())


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def listed_cycle(page: str) -> str:
    plain = html.unescape(re.sub(r"<[^>]+>", " ", page))
    plain = re.sub(r"\s+", " ", plain)
    patterns = (
        r"World\s+FSXP3D\s+package\s*\(?\s*(\d{4}-R\d+)\s*\)?",
        r"Google\s+Earth\s+(?:navaids|airports).*?\(?\s*(\d{4}-R\d+)\s*\)?",
        r"(?:VOR\s*/\s*NDB|ILS)\s*table\s*\(?\s*(\d{4}-R\d+)\s*\)?",
    )
    for pattern in patterns:
        match = re.search(pattern, plain, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return "unknown"


def download(url: str, referer: str, binary: bool = False) -> bytes:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 FlightTempo experimental data importer",
                    "Referer": referer,
                    "Accept": "application/vnd.google-earth.kmz, application/zip, application/octet-stream, */*",
                },
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = response.read()
            if binary and not zipfile.is_zipfile(BytesIO(payload)):
                prefix = payload[:200].decode("utf-8", errors="replace")
                raise ValueError(f"response is not a KMZ/ZIP archive ({len(payload)} bytes): {prefix!r}")
            return payload
        except Exception as exc:  # noqa: BLE001 - importer logs network/parser failures
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"download failed for {url}: {last_error}")


def parse_extended_data(placemark: ET.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for node in placemark.iter():
        kind = local_name(node.tag)
        if kind == "data":
            key = node.attrib.get("name", "")
            value = text_of(next((child for child in node if local_name(child.tag) == "value"), None))
            if key:
                values[key] = value
        elif kind == "simpledata":
            key = node.attrib.get("name", "")
            value = text_of(node)
            if key:
                values[key] = value
    return values


def point_coordinates(placemark: ET.Element) -> list[tuple[str, str, str, str]]:
    found: list[tuple[str, str, str, str]] = []
    for point in placemark.iter():
        if local_name(point.tag) != "point":
            continue
        coords = next((child for child in point if local_name(child.tag) == "coordinates"), None)
        raw = text_of(coords)
        for token in raw.split():
            parts = token.split(",")
            if len(parts) < 2:
                continue
            try:
                lon = float(parts[0])
                lat = float(parts[1])
                alt = float(parts[2]) if len(parts) > 2 and parts[2] else None
            except ValueError:
                continue
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                continue
            found.append((f"{lat:.8f}".rstrip("0").rstrip("."),
                          f"{lon:.8f}".rstrip("0").rstrip("."),
                          "" if alt is None else f"{alt:.3f}".rstrip("0").rstrip("."), raw))
    return found


def folder_placemarks(node: ET.Element, folders: list[str] | None = None) -> Iterable[tuple[list[str], ET.Element]]:
    folders = list(folders or [])
    tag = local_name(node.tag)
    if tag == "folder":
        folder_name = text_of(next((child for child in node if local_name(child.tag) == "name"), None))
        if folder_name:
            folders.append(folder_name)
    if tag == "placemark":
        yield folders, node
        return
    for child in list(node):
        yield from folder_placemarks(child, folders)


def extract_kmz(payload: bytes, kind: str, source_file: str, cycle: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    rows: list[dict[str, str]] = []
    kml_members: list[str] = []
    placemark_count = 0
    point_count = 0
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith((".kml", ".xml"))]
        if not members:
            raise RuntimeError("KMZ contains no KML/XML member")
        kml_members = members
        for member in members:
            try:
                root = ET.fromstring(archive.read(member))
            except ET.ParseError as exc:
                logging.warning("Skipping malformed KML member %s: %s", member, exc)
                continue
            for folder_path, placemark in folder_placemarks(root):
                placemark_count += 1
                placemark_name = text_of(next((child for child in placemark if local_name(child.tag) == "name"), None))
                description = text_of(next((child for child in placemark if local_name(child.tag) == "description"), None))
                extended = parse_extended_data(placemark)
                normalized = {normalize_key(key): value for key, value in extended.items()}
                mapped: dict[str, str] = {}
                for field, aliases in ALIASES.items():
                    mapped[field] = next((normalized[key] for key in normalized if key in aliases and normalized[key]), "")
                points = point_coordinates(placemark)
                geometry_names = sorted({local_name(node.tag) for node in placemark.iter()
                                          if local_name(node.tag) in {"point", "linestring", "polygon", "multigeometry", "model"}})
                geometry_type = "+".join(geometry_names) if geometry_names else "none"
                if not points:
                    points = [("", "", "", "")]
                    record_status = "metadata_only"
                else:
                    record_status = "point"
                    point_count += len(points)
                for index, (lat, lon, alt, coords_raw) in enumerate(points, start=1):
                    row = {field: "" for field in FIELDS}
                    row.update({
                        "source_file": member,
                        "source_folder": "/".join(folder_path),
                        "source_placemark": str(placemark_count) if len(points) == 1 else f"{placemark_count}:{index}",
                        "source_cycle": cycle,
                        "record_type": kind,
                        "record_status": record_status,
                        "name": placemark_name,
                        "latitude_deg": lat,
                        "longitude_deg": lon,
                        "altitude_m": alt,
                        "geometry_type": geometry_type,
                        "description": description,
                        "extended_data_json": json.dumps(extended, ensure_ascii=False, separators=(",", ":")),
                        "coordinates_raw": coords_raw,
                        **mapped,
                    })
                    if not row["ident"]:
                        row["ident"] = mapped.get("airport_icao", "")
                    if not row["facility_type"]:
                        row["facility_type"] = kind
                    if row["frequency"] and not row["frequency_unit"]:
                        freq_key = next((k for k in normalized if "freq" in k), "")
                        row["frequency_unit"] = "kHz" if "khz" in freq_key else "MHz" if "mhz" in freq_key else ""
                    rows.append(row)
    if not rows:
        raise RuntimeError("No placemark records found in KMZ")
    return rows, {
        "kmlMembers": kml_members,
        "placemarkCount": placemark_count,
        "recordCount": len(rows),
        "pointRecordCount": sum(row["record_status"] == "point" for row in rows),
        "coordinateCount": point_count,
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    payload = path.read_bytes()
    return {
        "recordCount": len(rows),
        "pointRecordCount": sum(row["record_status"] == "point" for row in rows),
        "metadataOnlyRecordCount": sum(row["record_status"] != "point" for row in rows),
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
    errors: list[str] = []
    try:
        home = download(HOME, REFERER).decode("utf-8", errors="replace")
        cycle = listed_cycle(home)
    except Exception as exc:  # noqa: BLE001
        logging.warning("Aero.Sors homepage cycle unavailable: %s", exc)
        cycle = "unknown"

    manifest_path = root / args.manifest
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"datasets": [], "dataSources": [], "capabilities": {}, "statistics": {}}
    datasets = {item.get("id"): item for item in manifest.get("datasets", [])}
    sources = {item.get("dataset"): item for item in manifest.get("dataSources", [])}
    exported: dict[str, dict[str, Any]] = {}

    for dataset_id, config in SOURCES.items():
        try:
            kmz = download(config["url"], config["page"], binary=True)
            rows, parsed = extract_kmz(kmz, config["kind"], config["url"].rsplit("/", 1)[-1], cycle)
            output = root / config["path"]
            counts = write_csv(output, rows)
            entry = {
                "id": dataset_id,
                "path": config["path"],
                "downloadUrl": "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/" + config["path"],
                "available": True,
                **counts,
                "sourceProvider": "Aero.Sors / Hervé Sors",
                "sourceUrl": config["url"],
                "sourcePageUrl": config["page"],
                "coverage": config["coverage"],
                "sourceTag": f"AEROSORS_{cycle}",
                "license": "Aero.Sors donationware; unchanged redistribution of original package permitted; derivative CSV republication permission not confirmed",
                "licenseStatus": "personal_development_test_only_derivative_redistribution_not_confirmed",
                "dataCycle": cycle,
                "effectiveDate": "",
                "expiryDate": "",
                "provenanceVerification": "Google_Earth_KML_exported; not independently cross-checked against AIP",
                "testDownloadAvailable": True,
                "downloadPurpose": "development_test_only",
                "operationallyAvailable": False,
                "status": "experimental_personal_test_only",
                "sourceKmzBytes": len(kmz),
                "sourceKmzSha256": hashlib.sha256(kmz).hexdigest(),
                **parsed,
            }
            datasets[dataset_id] = entry
            source = {
                "dataset": dataset_id,
                "provider": "Aero.Sors / Hervé Sors",
                "url": config["url"],
                "sourcePageUrl": config["page"],
                "downloadedAt": imported_at,
                "licenseStatus": entry["licenseStatus"],
                "sourceCycle": cycle,
                "sourceKmzBytes": len(kmz),
                "sourceKmzSha256": entry["sourceKmzSha256"],
                **counts,
                **parsed,
            }
            sources[dataset_id] = source
            exported[dataset_id] = source
            logging.info("Exported %s: %s placemark rows, %s point records, %s bytes, cycle %s",
                         dataset_id, counts["recordCount"], counts["pointRecordCount"], counts["sizeBytes"], cycle)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{dataset_id}: {exc}")
            logging.warning("Aero.Sors KMZ export failed for %s: %s", dataset_id, exc)

    if exported:
        manifest["datasets"] = list(datasets.values())
        manifest["dataSources"] = list(sources.values())
        capabilities = manifest.setdefault("capabilities", {})
        statistics = manifest.setdefault("statistics", {})
        for dataset_id, source in exported.items():
            capabilities[dataset_id] = True
            statistics[dataset_id] = source["recordCount"]
            statistics[dataset_id + "PointRecords"] = source["pointRecordCount"]
        manifest["aeroSorsGeospatialImportedAtUtc"] = imported_at
        manifest["generatedAtUtc"] = imported_at
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        source_manifest_path = root / "navigation/aerosors/source-manifest.json"
        source_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        existing = json.loads(source_manifest_path.read_text(encoding="utf-8")) if source_manifest_path.exists() else {}
        existing.update({
            "provider": "Aero.Sors / Hervé Sors",
            "sourceHome": HOME,
            "listedCycle": cycle,
            "geospatialExportedAtUtc": imported_at,
            "purpose": "experimental_personal_development_test_only",
            "operationallyAvailable": False,
            "redistributionRights": "not_confirmed_for_derived_csv_exports",
            "geospatialDatasets": exported,
            "geospatialLimitations": [
                "Only Placemark data from the published Google Earth KMZ layers is exported.",
                "No airway graph, IFR fix/intersection database, SID, STAR or approach is generated by these KMZ exports.",
                "Only KML Point geometries are assigned latitude/longitude; other geometry is retained as metadata-only.",
                "Coordinate altitude follows the KML altitude unit (metres) and is not converted into airport elevation feet.",
                "The source is simulator/reference material and has not been independently verified against national AIPs.",
                "Derived CSV republication rights are not confirmed; development-only label is not a licence grant.",
            ],
        })
        source_manifest_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if errors:
        logging.warning("Aero.Sors KMZ export completed with warnings: %s", "; ".join(errors))
        if not args.optional and len(exported) != len(SOURCES):
            raise RuntimeError("; ".join(errors))
    elif len(exported) != len(SOURCES) and not args.optional:
        raise RuntimeError("Aero.Sors KMZ export incomplete")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
