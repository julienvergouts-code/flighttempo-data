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
        report["sources"][key] = {
            "publicationPage": page,
            "downloadUrl": link["url"],
            "publicationLabel": link["label"],
            "downloadedBytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "workbook": inspect_workbook(raw),
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
