#!/usr/bin/env python3
"""Monitor EUROCONTROL FRA publication pages without redistributing source files.

The downloaded XLSX files are temporary CI inputs. The report contains source
URLs, workbook structure, header rows, row counts and hashes only. No point
records or workbook files are committed or uploaded as artifacts.
"""
from __future__ import annotations
import hashlib
import json
import re
import tempfile
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

SOURCES = {
    "ECAC": "https://www.eurocontrol.int/publication/free-route-airspace-fra-points-list-ecac-area",
    "MUAC": "https://www.eurocontrol.int/publication/free-route-airspace-fra-points-list-maastricht-uac",
}
USER_AGENT = "FlightTempo-FRA-Source-Monitor/1.0 (research metadata only)"
MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024


class DownloadLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current = None
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            attrs = dict(attrs)
            href = attrs.get("href", "")
            if href.lower().endswith((".xlsx", ".xls")):
                self.current = {"href": href, "text": ""}
    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data.strip() + " "
    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current is not None:
            self.links.append(self.current)
            self.current = None


def fetch(url: str, limit: int = MAX_DOWNLOAD_BYTES) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} for {url}")
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise RuntimeError(f"Download exceeds {limit} bytes: {url}")
    return raw


def find_latest_xlsx(page_url: str) -> dict:
    html = fetch(page_url, limit=4 * 1024 * 1024).decode("utf-8", "replace")
    parser = DownloadLinkParser()
    parser.feed(html)
    links = parser.links
    if not links:
        raise RuntimeError(f"No Excel download link found on publication page: {page_url}")
    # Drupal publication pages list the newest effective publication first.
    return {"url": urljoin(page_url, links[0]["href"]), "label": links[0]["text"].strip()}


def inspect_workbook(raw: bytes) -> dict:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("openpyxl missing; install requirements-aerosors.txt") from exc
    import io
    workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    sheets = []
    for ws in workbook.worksheets:
        header_candidates = []
        for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=min(ws.max_row or 1, 15), values_only=True), start=1):
            values = [str(v).strip() if v is not None else "" for v in row]
            norm = [re.sub(r"[^a-z0-9]+", " ", v.lower()).strip() for v in values]
            joined = " ".join(norm)
            # Keep only rows that look like column labels, never data rows.
            header_terms = (
                "point", "waypoint", "significant", "ident", "identifier", "name", "code",
                "lat", "latitude", "lon", "longitude", "coord", "availability", "level",
                "time", "route", "connection", "airport", "entry", "exit", "remarks",
                "description", "flos", "relevance",
            )
            matches = sum(any(term in cell for term in header_terms) for cell in norm if cell)
            if matches >= 2 and len(values) > 1:
                header_candidates.append({"row": row_idx, "columns": values})
        sheets.append({
            "sheetName": ws.title,
            "maxRows": ws.max_row,
            "maxColumns": ws.max_column,
            "candidateHeaderRows": header_candidates[:3],
        })
    workbook.close()
    return {"sheetCount": len(sheets), "sheets": sheets}


def parse_dms_coordinate(value, axis: str):
    """Parse EUROCONTROL FRA coordinate notation (hemisphere + DMS) or decimal."""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().upper().replace("°", " ").replace("'", " ").replace('"', " ")
    text = re.sub(r"\s+", " ", text)
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        number = float(text)
        limit = 90 if axis == "lat" else 180
        return number if abs(number) <= limit else None
    match = re.fullmatch(r"([NSEW])\s*(\d{6,7})", text.replace(" ", ""))
    if match:
        hemi, digits = match.groups()
        if axis == "lat" and hemi not in "NS" or axis == "lon" and hemi not in "EW":
            return None
        deg_digits = 2 if axis == "lat" else 3
        deg, minute, second = int(digits[:deg_digits]), int(digits[deg_digits:deg_digits+2]), int(digits[deg_digits+2:deg_digits+4])
    else:
        match = re.fullmatch(r"([NSEW])\s*(\d{1,3})\s+(\d{1,2})\s+(\d{1,2}(?:\.\d+)?)", text)
        if not match:
            return None
        hemi, deg_s, minute_s, second_s = match.groups()
        if axis == "lat" and hemi not in "NS" or axis == "lon" and hemi not in "EW":
            return None
        deg, minute, second = int(deg_s), int(minute_s), float(second_s)
    limit = 90 if axis == "lat" else 180
    if deg > limit or minute >= 60 or second >= 60:
        return None
    result = deg + minute / 60 + second / 3600
    if (axis == "lat" and hemi == "S") or (axis == "lon" and hemi == "W"):
        result = -result
    return result


def analyze_ecac_workbook(workbook) -> dict:
    ws = next((sheet for sheet in workbook.worksheets if sheet.title.strip().lower() == "fra points"), None)
    if ws is None:
        raise RuntimeError("ECAC workbook has no 'FRA Points' worksheet")
    header = [str(v).strip() if v is not None else "" for v in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    positions = {name: idx for idx, name in enumerate(header) if name}
    required = {"FRA Point", "FRA Point Latitude", "FRA Point Longitude"}
    if not required.issubset(positions):
        raise RuntimeError(f"Unexpected ECAC FRA sheet schema; missing {sorted(required - set(positions))}")
    count = 0
    identifiers = set()
    valid_coordinates = 0
    missing_coordinates = 0
    invalid_coordinates = 0
    point_types, enroute_relevance, arrdep_relevance, level_availability, time_availability = set(), set(), set(), set(), set()
    arrival_associations = departure_associations = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        point = row[positions["FRA Point"]] if positions["FRA Point"] < len(row) else None
        if point is None or not str(point).strip():
            continue
        count += 1
        identifiers.add(str(point).strip().upper())
        lat = row[positions["FRA Point Latitude"]] if positions["FRA Point Latitude"] < len(row) else None
        lon = row[positions["FRA Point Longitude"]] if positions["FRA Point Longitude"] < len(row) else None
        if lat is None or lon is None or not str(lat).strip() or not str(lon).strip():
            missing_coordinates += 1
        elif parse_dms_coordinate(lat, "lat") is None or parse_dms_coordinate(lon, "lon") is None:
            invalid_coordinates += 1
        else:
            valid_coordinates += 1
        for col, target in (("Point Type", point_types), ("FRA Relevance En-Route", enroute_relevance), ("FRA Relevance ARR/DEP", arrdep_relevance), ("Level Availability", level_availability), ("Time Availability", time_availability)):
            if col in positions and positions[col] < len(row) and row[positions[col]] not in (None, ""):
                target.add(str(row[positions[col]]).strip())
        if "Arrival Airport" in positions and row[positions["Arrival Airport"]] not in (None, ""):
            arrival_associations += 1
        if "Departure Airport" in positions and row[positions["Departure Airport"]] not in (None, ""):
            departure_associations += 1
    return {
        "rowCount": count,
        "uniquePointIdentifiers": len(identifiers),
        "validCoordinatePairs": valid_coordinates,
        "missingCoordinatePairs": missing_coordinates,
        "invalidCoordinatePairs": invalid_coordinates,
        "distinctPointTypes": len(point_types),
        "distinctEnRouteRelevanceValues": len(enroute_relevance),
        "distinctArrivalDepartureRelevanceValues": len(arrdep_relevance),
        "distinctLevelAvailabilityValues": len(level_availability),
        "distinctTimeAvailabilityValues": len(time_availability),
        "arrivalAirportAssociations": arrival_associations,
        "departureAirportAssociations": departure_associations,
        "schemaColumns": header,
    }


def analyze_muac_workbook(workbook) -> dict:
    ws = next((sheet for sheet in workbook.worksheets if sheet.title.strip().lower() == "fra points"), None)
    if ws is None:
        raise RuntimeError("MUAC workbook has no 'FRA Points' worksheet")
    header = [str(v).strip() if v is not None else "" for v in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    positions = {name: idx for idx, name in enumerate(header) if name}
    if "FRA Point" not in positions or "FRA Relevance" not in positions:
        raise RuntimeError(f"Unexpected MUAC FRA sheet schema: {header}")
    points, relevance, sources = set(), set(), set()
    rows = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        point = row[positions["FRA Point"]] if positions["FRA Point"] < len(row) else None
        if point is None or not str(point).strip():
            continue
        rows += 1
        points.add(str(point).strip().upper())
        rel = row[positions["FRA Relevance"]]
        if rel not in (None, ""):
            relevance.add(str(rel).strip())
        if "Source AIP" in positions and row[positions["Source AIP"]] not in (None, ""):
            sources.add(str(row[positions["Source AIP"]]).strip())
    return {"rowCount": rows, "uniquePointIdentifiers": len(points), "distinctRelevanceValues": len(relevance), "distinctSourceAipValues": len(sources), "schemaColumns": header}


def build_report() -> dict:
    report = {
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Source monitoring and schema discovery only; not an app dataset.",
        "redistributionStatus": "not_confirmed; source XLSX is not retained or republished",
        "sources": {},
    }
    for key, page in SOURCES.items():
        link = find_latest_xlsx(page)
        raw = fetch(link["url"])
        if len(raw) < 10_000:
            raise RuntimeError(f"{key}: suspiciously small workbook ({len(raw)} bytes)")
        import io
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        analysis = analyze_ecac_workbook(workbook) if key == "ECAC" else analyze_muac_workbook(workbook)
        workbook.close()
        report["sources"][key] = {
            "publicationPage": page,
            "downloadUrl": link["url"],
            "publicationLabel": link["label"],
            "downloadedBytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "workbook": inspect_workbook(raw),
            "aggregateAnalysis": analysis,
        }
    return report


def main():
    report = build_report()
    output = Path("fra_source_monitor_report.json")
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for key, source in report["sources"].items():
        print(f"{key}: {source['publicationLabel']} ({source['downloadedBytes']} bytes)")
        for sheet in source["workbook"]["sheets"]:
            print(f"  {sheet['sheetName']}: {sheet['maxRows']}x{sheet['maxColumns']} rows/cols; candidate headers={len(sheet['candidateHeaderRows'])}")
    print(f"Report written: {output}")


if __name__ == "__main__":
    main()
