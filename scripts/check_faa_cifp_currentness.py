#!/usr/bin/env python3
"""Check the published FAA CIFP cycle against the cycle packaged in FlightTempo.

This is a currentness monitor, not an ARINC 424 parser or data importer. It
never replaces the packaged procedure CSVs.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAA_PAGE = "https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/cifp/download/"
OUT = ROOT / "procedures/faa-cifp-currentness.json"
APP_MANIFEST = ROOT / "navigation_manifest.json"
USER_AGENT = "FlightTempo-Data-Maintenance/1.0"


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.row is not None and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None
            self.cell = None


def cycle_date(token: str) -> date:
    if not re.fullmatch(r"\d{6}", token):
        raise ValueError(f"Invalid CIFP cycle token: {token}")
    return date(2000 + int(token[:2]), int(token[2:4]), int(token[4:6]))


def fetch_page() -> str:
    request = urllib.request.Request(FAA_PAGE, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_cycles(html: str) -> list[dict]:
    parser = TableParser()
    parser.feed(html)
    records = []
    for row in parser.rows:
        joined = " ".join(row)
        match = re.search(r"CIFP\s+(\d{6})\s*\(Zip\)", joined, re.IGNORECASE)
        if not match:
            continue
        token = match.group(1)
        dates = re.findall(r"\b[A-Z][a-z]{2}\s+\d{1,2},\s+20\d{2}\b", joined)
        if len(dates) < 2:
            continue
        effective = datetime.strptime(dates[0], "%b %d, %Y").date()
        ending = datetime.strptime(dates[1], "%b %d, %Y").date()
        records.append({
            "cycleToken": token,
            "effectiveDate": effective.isoformat(),
            "expiryDate": ending.isoformat(),
            "downloadUrl": f"https://aeronav.faa.gov/Upload_313-d/cifp/CIFP_{token}.zip",
        })
    # If the page layout changes, fail closed rather than guess a cycle from a URL.
    unique = {item["cycleToken"]: item for item in records}
    return sorted(unique.values(), key=lambda x: x["cycleToken"])


def packaged_cycle(manifest: dict) -> dict:
    procedure_sets = [
        item for item in manifest.get("datasets", [])
        if item.get("id") in {"sids", "stars", "approaches"}
    ]
    if not procedure_sets:
        raise ValueError("No packaged FAA procedure datasets found")
    urls = [str(item.get("sourceUrl", "")) for item in procedure_sets]
    tokens = {
        match.group(1)
        for url in urls
        for match in [re.search(r"CIFP_(\d{6})\.zip", url)]
        if match
    }
    if len(tokens) != 1:
        raise ValueError(f"Expected one consistent packaged CIFP cycle, found {sorted(tokens)}")
    token = tokens.pop()
    effective = {item.get("effectiveDate") for item in procedure_sets}
    expiry = {item.get("expiryDate") for item in procedure_sets}
    if len(effective) != 1 or len(expiry) != 1 or None in effective or None in expiry:
        raise ValueError("Packaged FAA procedure datasets have inconsistent/missing effective dates")
    return {
        "cycleToken": token,
        "effectiveDate": next(iter(effective)),
        "expiryDate": next(iter(expiry)),
    }


def build_status(manifest: dict, cycles: list[dict], today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    packaged = packaged_cycle(manifest)
    if not cycles:
        raise ValueError("FAA page contained no parseable CIFP cycle rows")
    latest = cycles[-1]
    current = next((x for x in cycles if x["cycleToken"] == packaged["cycleToken"]), None)
    expiry = date.fromisoformat(packaged["expiryDate"])
    next_future = next(
        (x for x in cycles if date.fromisoformat(x["effectiveDate"]) > today),
        None,
    )
    if today > expiry:
        status = "stale_update_required"
    elif latest["cycleToken"] != packaged["cycleToken"] and date.fromisoformat(latest["effectiveDate"]) <= today:
        status = "new_cycle_effective_import_required"
    elif next_future and next_future["cycleToken"] != packaged["cycleToken"]:
        status = "packaged_cycle_current_next_cycle_published"
    else:
        status = "packaged_cycle_current"
    return {
        "checkedAtUtc": datetime.now(timezone.utc).isoformat(),
        "source": "FAA AeroNav CIFP",
        "sourcePageUrl": FAA_PAGE,
        "updateFrequency": "28 days",
        "status": status,
        "packagedCycle": packaged,
        "packagedCycleListedByFaa": current is not None,
        "latestPublishedCycle": latest,
        "nextFutureCycle": next_future,
        "latestPublishedDownloadUrl": latest["downloadUrl"],
        "automaticImport": False,
        "automaticImportReason": (
            "The repository has a validated staging-only archive audit and partial procedure-header extractor. "
            "Full ARINC 424 leg semantics, CSV conversion, and end-to-end equivalence checks "
            "are not implemented. No packaged procedure dataset may be replaced."
        ),
        "operationalUse": False,
    }


def main():
    manifest = json.loads(APP_MANIFEST.read_text(encoding="utf-8"))
    try:
        cycles = parse_cycles(fetch_page())
        status = build_status(manifest, cycles)
    except Exception as exc:
        status = {
            "checkedAtUtc": datetime.now(timezone.utc).isoformat(),
            "source": "FAA AeroNav CIFP",
            "sourcePageUrl": FAA_PAGE,
            "status": "check_failed",
            "error": str(exc),
            "automaticImport": False,
            "operationalUse": False,
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(status, indent=2))
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2))
    if status["status"] in {"new_cycle_effective_import_required", "stale_update_required"}:
        raise SystemExit(
            "FAA CIFP update required: a newer cycle is effective or the packaged cycle has expired. "
            "This is an alert only; automatic ARINC 424 import is not implemented."
        )


if __name__ == "__main__":
    main()
