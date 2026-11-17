#!/usr/bin/env python3
"""Metadata-only probe for NOAA Aviation Weather Center public weather feeds.

The script records availability, counts and field names only. It does not
persist or redistribute METAR, TAF, SIGMET or PIREP records.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://aviationweather.gov"
USER_AGENT = "FlightTempo-NOAA-AWC-metadata-probe/1.0 (aviation weather integration research)"


def fetch(url: str) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, application/xml, text/csv, */*"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 204:
            return 204, b""
        raise


def json_summary(payload: bytes) -> dict:
    if not payload:
        return {"record_count": 0, "field_names": []}
    obj = json.loads(payload.decode("utf-8"))
    if isinstance(obj, list):
        rows = obj
    elif isinstance(obj, dict):
        rows = obj.get("features") or obj.get("records") or obj.get("data") or []
    else:
        rows = []
    first = rows[0] if rows else {}
    if isinstance(first, dict) and "properties" in first:
        first = first.get("properties") or {}
    return {
        "record_count": len(rows),
        "field_names": sorted(first.keys()) if isinstance(first, dict) else [],
    }


def csv_summary(payload: bytes) -> dict:
    if not payload:
        return {"record_count": 0, "field_names": []}
    text = payload.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    count = sum(1 for _ in reader)
    return {"record_count": count, "field_names": list(reader.fieldnames or [])}


def probe_json_endpoint(product: str, path: str, params: str) -> dict:
    url = f"{BASE}/api/data/{path}?{params}"
    try:
        status, payload = fetch(url)
        summary = json_summary(payload) if status == 200 else {"record_count": 0, "field_names": []}
        return {"url": url, "http_status": status, "status": "ok" if status == 200 else "no_data", **summary}
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"url": url, "status": "error", "error": str(exc)[:500]}


def probe_sigmet_cache() -> dict:
    url = f"{BASE}/data/cache/sigmets.cache.json.gz"
    try:
        status, compressed = fetch(url)
        payload = gzip.decompress(compressed)
        summary = json_summary(payload)
        return {"url": url, "http_status": status, "status": "ok", **summary}
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"url": url, "status": "error", "error": str(exc)[:500]}


def probe_pirep_cache() -> dict:
    url = f"{BASE}/data/cache/aircraftreports.cache.csv.gz"
    try:
        status, compressed = fetch(url)
        payload = gzip.decompress(compressed)
        summary = csv_summary(payload)
        return {"url": url, "http_status": status, "status": "ok", **summary}
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, csv.Error) as exc:
        return {"url": url, "status": "error", "error": str(exc)[:500]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("weather/noaa/awc-probe-report.json"))
    args = parser.parse_args()

    report = {
        "provider": "NOAA Aviation Weather Center",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "metadata_only_access_probe",
        "weather_records_downloaded_for_publication": False,
        "products": {
            "metar_ebbr": probe_json_endpoint("METAR", "metar", "ids=EBBR&format=json"),
            "taf_ebbr": probe_json_endpoint("TAF", "taf", "ids=EBBR&format=json"),
            "isigmet_geojson": probe_json_endpoint("International SIGMET", "isigmet", "format=geojson"),
            "legacy_sigmet_geojson": probe_json_endpoint("Legacy SIGMET", "sigmet", "format=geojson"),
            "airsigmet_geojson": probe_json_endpoint("Domestic SIGMET", "airsigmet", "format=geojson"),
            "surface_analysis_geojson": probe_json_endpoint("Surface analysis", "surface", "format=geojson"),
            "global_sigmet_cache": probe_sigmet_cache(),
            "pirep_cache": probe_pirep_cache(),
        },
        "coverage_notes": {
            "metar": "Worldwide",
            "taf": "Worldwide",
            "sigmet": "Worldwide",
            "pirep": "Primarily US and North Atlantic",
        },
        "service_limits": {
            "max_requests_per_minute": 100,
            "typical_max_results_per_query": 400,
            "cors_enabled": False,
            "recommended_large_query_method": "provider cache files",
        },
    }
    successful = sum(item.get("status") == "ok" for item in report["products"].values())
    report["successful_product_probes"] = successful
    report["service_status"] = "reachable" if successful >= 2 else "partial_or_unavailable"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if successful >= 2 else 2


if __name__ == "__main__":
    raise SystemExit(main())
