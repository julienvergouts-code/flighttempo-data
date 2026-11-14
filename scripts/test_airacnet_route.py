#!/usr/bin/env python3
"""Targeted, non-publishing smoke test of the public AIRAC.net API.

This deliberately downloads only the LFPG -> LANVI -> EDDM test context.
Provider responses are written to a local output directory and are NOT
committed to the public FlightTempo data repository.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://airac.net/api/v1"
UA = "FlightTempo-Navdata-Research/0.1 (personal development test)"
OUT_DEFAULT = Path("build/airacnet-test")

def get_json(path, params=None, retries=3):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    headers = {"Accept": "application/json", "User-Agent": UA}
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as response:
                body = response.read()
                result = json.loads(body.decode("utf-8"))
                meta = {
                    "url": url,
                    "http_status": response.status,
                    "airac_cycle": response.headers.get("X-AIRAC-Cycle"),
                    "effective_date": response.headers.get("X-AIRAC-Effective-Date"),
                    "expiration_date": response.headers.get("X-AIRAC-Expiration-Date"),
                    "etag": response.headers.get("ETag"),
                }
                return result, meta
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last}")

def data_of(payload):
    return payload.get("data", []) if isinstance(payload, dict) else []

def save(out, name, payload, meta):
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(
        json.dumps({"source": "AIRAC.net API", "request": meta, "response": payload},
                   indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(OUT_DEFAULT))
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "https://airac.net/",
        "purpose": "Personal development smoke test; not operational data",
        "route_test": {"origin": "LFPG", "departure_runway": "27R",
                       "enroute_fix": "LANVI", "destination": "EDDM",
                       "arrival_runway": "26R"},
        "results": {},
        "errors": []
    }

    requests = [
        ("current_cycle", "/airac/current", None),
        ("lfpg_airport", "/airports/LFPG", None),
        ("eddm_airport", "/airports/EDDM", None),
        ("lfpg_sids_rwy27r", "/procedures", {"airport": "LFPG", "type": "SID", "runway": "27R"}),
        ("eddm_stars_rwy26r", "/procedures", {"airport": "EDDM", "type": "STAR", "runway": "26R"}),
        ("lanvi_waypoint", "/waypoints/LANVI", None),
        ("airways_at_lanvi", "/airways", {"fix": "LANVI"}),
    ]
    payloads = {}
    for name, path, params in requests:
        try:
            payload, meta = get_json(path, params)
            payloads[name] = payload
            save(out, name, payload, meta)
            d = data_of(payload)
            count = len(d) if isinstance(d, list) else (1 if d else 0)
            report["results"][name] = {
                "url": meta["url"], "http_status": meta["http_status"],
                "airac_cycle": meta["airac_cycle"],
                "effective_date": meta["effective_date"],
                "expiration_date": meta["expiration_date"],
                "records": count
            }
            print(f"[AIRAC.net] {name}: {count} result(s); cycle={meta['airac_cycle']}")
        except Exception as exc:
            report["errors"].append({"request": name, "error": str(exc)})
            print(f"[AIRAC.net] ERROR {name}: {exc}", file=sys.stderr)

    # Fetch full details for every matching SID/STAR returned for the selected runway.
    for key, kind, airport in [
        ("lfpg_sids_rwy27r", "sid", "LFPG"),
        ("eddm_stars_rwy26r", "star", "EDDM"),
    ]:
        payload = payloads.get(key, {})
        records = data_of(payload)
        if not isinstance(records, list):
            records = []
        details = []
        for item in records:
            ident = item.get("identifier")
            if not ident:
                continue
            try:
                detail, meta = get_json(f"/procedures/{airport}/{urllib.parse.quote(ident, safe='')}")
                details.append({"identifier": ident, "request": meta, "response": detail})
            except Exception as exc:
                report["errors"].append({"request": f"{airport}/{ident}", "error": str(exc)})
        (out / f"{airport.lower()}_{kind}_details.json").write_text(
            json.dumps(details, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        report["results"][f"{airport.lower()}_{kind}_details"] = {
            "procedures_fetched": len(details)
        }

    # Ask the provider's own route parser to expand the waypoint/procedure tokens.
    sid_items = data_of(payloads.get("lfpg_sids_rwy27r", {}))
    star_items = data_of(payloads.get("eddm_stars_rwy26r", {}))
    sid = next((x.get("identifier") for x in sid_items if x.get("identifier")), None) if isinstance(sid_items, list) else None
    star = next((x.get("identifier") for x in star_items if x.get("identifier")), None) if isinstance(star_items, list) else None
    if sid and star:
        route = f"{sid} LANVI {star}"
        try:
            payload, meta = get_json("/routes/parse", {
                "origin": "LFPG", "destination": "EDDM", "route": route,
                "departure_runway": "27R", "arrival_runway": "26R"
            })
            save(out, "lfpg_lanvi_eddm_route_parse", payload, meta)
            route_data = payload.get("data", {}) if isinstance(payload, dict) else {}
            report["route_parse"] = {
                "route_string": route,
                "total_distance_nm": route_data.get("total_distance"),
                "segment_count": len(route_data.get("segments", [])),
                "errors": route_data.get("errors", []),
                "url": meta["url"],
                "airac_cycle": meta["airac_cycle"]
            }
        except Exception as exc:
            report["errors"].append({"request": "route_parse", "error": str(exc)})
    else:
        report["route_parse"] = {
            "skipped": True,
            "reason": "No runway-matching SID or STAR returned by the API; no procedure identifiers invented."
        }

    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    # A partial dataset is still useful evidence; fail only if all primary calls failed.
    if not report["results"]:
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
