#!/usr/bin/env python3
"""Download a broad AIRAC.net world-data snapshot for FlightTempo experiments.

The API is queried through its documented JSON endpoints. Output is raw JSONL
so no source fields, procedure legs or transition details are discarded.
This is a development snapshot, not an operational navigation database.
"""
import concurrent.futures
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://airac.net/api/v1"
OUT = Path("navigation/airacnet")
UA = "FlightTempo/experimental-world-navdata (+https://github.com/julienvergouts-code/flighttempo-data)"
HEADERS = {"Accept": "application/json", "User-Agent": UA}
PAGE_SIZE = 100
WORKERS = 4
ERRORS = []

def get(path, params=None, attempts=4):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                payload = json.loads(r.read().decode("utf-8"))
                headers = {
                    "airac_cycle": r.headers.get("X-AIRAC-Cycle"),
                    "effective_date": r.headers.get("X-AIRAC-Effective-Date"),
                    "expiration_date": r.headers.get("X-AIRAC-Expiration-Date"),
                    "etag": r.headers.get("ETag"),
                }
                return payload, headers
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
            last = e
            if i + 1 < attempts:
                time.sleep(min(2 ** i, 8))
    raise RuntimeError(f"{url}: {last}")

def data(payload):
    value = payload.get("data", []) if isinstance(payload, dict) else []
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []

def paged(path, params=None):
    params = dict(params or {})
    page = 1
    all_rows = []
    cycle_meta = {}
    while True:
        q = {**params, "page": page, "per_page": PAGE_SIZE}
        payload, meta = get(path, q)
        cycle_meta = meta or cycle_meta
        rows = data(payload)
        all_rows.extend(rows)
        pagination = payload.get("pagination", {}) if isinstance(payload, dict) else {}
        if not rows or not pagination.get("has_more", False):
            break
        page += 1
        if page > 100000:
            raise RuntimeError(f"Pagination safety limit reached: {path}")
    return all_rows, cycle_meta

def write_jsonl(name, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return path.stat().st_size

def collect_detail(task):
    path, params = task
    return get(path, params)[0]

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    report = {
        "source": "AIRAC.net public API",
        "base_url": BASE,
        "downloaded_at_utc": started,
        "purpose": "Personal development / route-display experiment",
        "not_for_operational_use": True,
        "datasets": {},
        "errors": []
    }
    cycle, cycle_meta = get("/airac/current")
    (OUT / "airac_cycle.json").write_text(json.dumps(cycle, indent=2) + "\n", encoding="utf-8")
    report["airac_headers"] = cycle_meta
    report["airac_current"] = cycle

    def save_dataset(name, rows, meta=None):
        size = write_jsonl(name + ".jsonl", rows)
        report["datasets"][name] = {"records": len(rows), "bytes": size, "cycle": meta or cycle_meta}
        print(f"{name}: {len(rows)} records ({size} bytes)", flush=True)

    # Airports are indexed by country in the documented API.
    try:
        countries, meta = paged("/countries")
        save_dataset("countries", countries, meta)
        airport_rows = []
        for c in countries:
            code = c.get("code")
            if not code:
                continue
            try:
                rows, _ = paged("/airports", {"country": code})
                airport_rows.extend(rows)
            except Exception as e:
                report["errors"].append({"dataset": "airports", "country": code, "error": str(e)})
        # Deduplicate without changing source payloads.
        by_id = {}
        for row in airport_rows:
            key = row.get("icao") or row.get("iata") or row.get("url") or json.dumps(row, sort_keys=True)
            by_id[key] = row
        save_dataset("airports", list(by_id.values()))
    except Exception as e:
        report["errors"].append({"dataset": "countries/airports", "error": str(e)})

    # Worldwide waypoint and airway indexes.
    for name, path, params in [
        ("waypoints", "/waypoints", {}),
        ("airways", "/airways", {}),
    ]:
        try:
            rows, meta = paged(path, params)
            save_dataset(name, rows, meta)
        except Exception as e:
            report["errors"].append({"dataset": name, "error": str(e)})

    # Navaids are listed by type.
    navaids = []
    for kind in ("VOR", "VOR/DME", "DME", "TACAN", "VORTAC", "NDB"):
        try:
            rows, meta = paged("/navaids", {"type": kind})
            navaids.extend(rows)
        except Exception as e:
            report["errors"].append({"dataset": "navaids", "type": kind, "error": str(e)})
    nav_by_key = {}
    for row in navaids:
        key = row.get("url") or (row.get("identifier"), row.get("region"), row.get("type", {}).get("code"))
        nav_by_key[str(key)] = row
    save_dataset("navaids", list(nav_by_key.values()))

    # Download full airway segment sequences, retaining region distinctions.
    airway_rows = []
    try:
        airway_index, _ = paged("/airways")
        tasks = []
        for a in airway_index:
            ident = a.get("identifier")
            for region in a.get("regions", []) or [None]:
                if ident:
                    tasks.append((f"/airways/{urllib.parse.quote(ident, safe='')}", {"region": region} if region else None))
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for result in pool.map(collect_detail, tasks):
                airway_rows.append(result.get("data", result) if isinstance(result, dict) else result)
        save_dataset("airway_details", airway_rows)
    except Exception as e:
        report["errors"].append({"dataset": "airway_details", "error": str(e)})

    # Procedure search supports type-only global listings; avoid one query per airport.
    try:
        indexes = []
        for kind in ("SID", "STAR", "APP"):
            rows, meta = paged("/procedures", {"type": kind})
            indexes.extend(rows)
            print(f"procedure index {kind}: {len(rows)}", flush=True)
        save_dataset("procedures_index", indexes)
        detail_tasks = []
        for row in indexes:
            airport = row.get("airport")
            ident = row.get("identifier")
            if airport and ident:
                detail_tasks.append((f"/procedures/{airport}/{urllib.parse.quote(ident, safe='')}", None))
        details = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for result in pool.map(collect_detail, detail_tasks):
                details.append(result.get("data", result) if isinstance(result, dict) else result)
        save_dataset("procedures_full", details)
    except Exception as e:
        report["errors"].append({"dataset": "procedures", "error": str(e)})

    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["total_errors"] = len(report["errors"])
    (OUT / "download_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
    # Partial coverage is still useful; fail only if nothing beyond cycle was downloaded.
    if not report["datasets"]:
        raise SystemExit("No world datasets downloaded successfully")

if __name__ == "__main__":
    main()
