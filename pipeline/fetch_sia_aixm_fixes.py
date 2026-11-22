#!/usr/bin/env python3
"""Fetch the latest public French SIA AIXM cycle and export designated points.

The CSV remains a separate France-and-overseas reference layer. DPN points
are not assumed to be VFR reporting points or current IFR route fixes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
import re
import tempfile
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.import_sia_aixm_fixes import extract_points

INDEX_URL = "https://data.cquest.org/dgac/aip/"
SIA_PRODUCT_URL = "https://www.sia.aviation-civile.gouv.fr/produits-numeriques-en-libre-disposition/les-bases-de-donnees-sia/"
OUT_CSV = Path("navigation/waypoints/fr_sia_designated_points.csv")
OUT_META = Path("navigation/waypoints/fr_sia_designated_points_meta.json")
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def release_date_from_name(name: str) -> date | None:
    match = re.search(r"(?<!\d)(20\d{2})[-_](\d{2})[-_](\d{2})(?!\d)", name)
    if not match:
        return None
    try:
        return date(*(int(value) for value in match.groups()))
    except ValueError:
        return None


def select_archive(hrefs: list[str], today: date) -> tuple[str, date]:
    candidates = []
    for href in hrefs:
        parsed = urlparse(href)
        name = parsed.path.rsplit("/", 1)[-1]
        if not name.lower().endswith(".zip") or not re.search(r"(?i)(sia|aixm|aip)", name):
            continue
        effective = release_date_from_name(name)
        if effective is None or effective < today - timedelta(days=28) or effective > today + timedelta(days=28):
            continue
        candidates.append((effective, href))
    if not candidates:
        observed = [href for href in hrefs if any(token in href.lower() for token in (".zip", "sia", "aixm", "xml"))]
        observed = (observed or hrefs)[:20]
        raise RuntimeError(
            "No current or upcoming dated SIA AIXM ZIP was found in the public mirror index; "
            f"observed links: {observed}"
        )
    effective, href = max(candidates)
    return href, effective


def fetch(url: str, limit: int) -> bytes:
    request = Request(url, headers={"User-Agent": "FlightTempo-data-reference/1.0", "Accept": "application/zip, text/html, */*"})
    with urlopen(request, timeout=60) as response:
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > limit:
            raise RuntimeError(f"Refusing unexpectedly large SIA response ({declared} bytes)")
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise RuntimeError(f"Refusing SIA archive larger than {limit} bytes")
    return raw


def latest_archive(index_url: str = INDEX_URL, today: date | None = None) -> tuple[str, date, bytes]:
    today = today or datetime.now(timezone.utc).date()
    html = fetch(index_url, 2 * 1024 * 1024).decode("utf-8", errors="replace")
    parser = LinkParser()
    parser.feed(html)
    archive_url, effective = select_archive([urljoin(index_url, href) for href in parser.hrefs], today)
    if urlparse(archive_url).hostname != urlparse(index_url).hostname or urlparse(archive_url).scheme != "https":
        raise RuntimeError("The SIA mirror index linked to a non-HTTPS or unexpected host")
    archive = fetch(archive_url, MAX_ARCHIVE_BYTES)
    if not archive.startswith(b"PK\x03\x04"):
        raise RuntimeError("The current SIA AIXM download is not a ZIP archive")
    return archive_url, effective, archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-url", default=INDEX_URL)
    parser.add_argument("--output", type=Path, default=OUT_CSV)
    parser.add_argument("--manifest", type=Path, default=OUT_META)
    args = parser.parse_args()

    source_file_url, effective, archive_bytes = latest_archive(args.index_url)
    expiry = effective + timedelta(days=27)
    with tempfile.TemporaryDirectory(prefix="flighttempo-sia-") as temp_dir:
        archive_path = Path(temp_dir) / Path(urlparse(source_file_url).path).name
        archive_path.write_bytes(archive_bytes)
        points, digest, member = extract_points(archive_path)
        if not points:
            raise RuntimeError("Current SIA AIXM package produced no WGS-84 designated points")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        import csv
        fields = list(points[0])
        with args.output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(points)
        import json
        identifier_counts = Counter(row["ident"] for row in points)
        metadata = {
            "schemaVersion": 1,
            "sourceProvider": "Service de l'Information Aeronautique (SIA France)",
            "sourceUrl": SIA_PRODUCT_URL,
            "sourceFileUrl": source_file_url,
            "sourceFile": archive_path.name,
            "sourceMember": member,
            "sha256": digest,
            "recordCount": len(points),
            "uniqueIdentifierCount": len({row["ident"] for row in points}),
            "ambiguousIdentifierCount": sum(count > 1 for count in identifier_counts.values()),
            "license": "Licence Ouverte / Open Licence (Etalab)",
            "attribution": "Service de l'Information Aeronautique - Donnees originales; cycle effectif " + effective.isoformat(),
            "dataCycle": effective.isoformat(),
            "effectiveDate": effective.isoformat(),
            "expiryDate": expiry.isoformat(),
            "status": "reference_designated_points_not_operationally_validated",
            "coverage": "France and French overseas AIP designated points (DPN); not classified as VFR reporting points",
            "downloadedAtUtc": datetime.now(timezone.utc).isoformat(),
        }
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(points)} French SIA designated points for cycle effective {effective.isoformat()} ({args.output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
