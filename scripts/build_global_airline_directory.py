#!/usr/bin/env python3
"""Build FlightTempo's worldwide airline directory from Wikidata structured data.

Wikidata structured data is CC0. This directory is descriptive reference data,
not an airline schedule, live route network, or operational source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://query.wikidata.org/sparql"
SOURCE_URL = "https://www.wikidata.org/"
LICENSE = "CC0-1.0"
USER_AGENT = (
    "FlightTempoData/1.0 "
    "(https://github.com/julienvergouts-code/flighttempo-data; "
    "automated public airline directory refresh)"
)
QUERY = """
SELECT ?item ?itemLabel
       (GROUP_CONCAT(DISTINCT STR(?iataRaw); separator="|") AS ?iataValues)
       (GROUP_CONCAT(DISTINCT STR(?icaoRaw); separator="|") AS ?icaoValues)
       (GROUP_CONCAT(DISTINCT STR(?callsignRaw); separator="|") AS ?callsignValues)
       (GROUP_CONCAT(DISTINCT STR(?countryLabel); separator="|") AS ?countryValues)
       (SAMPLE(?inceptionRaw) AS ?inception)
       (SAMPLE(?dissolvedRaw) AS ?dissolved)
WHERE {
  ?item wdt:P31/wdt:P279* wd:Q46970 .
  OPTIONAL { ?item wdt:P229 ?iataRaw . }
  OPTIONAL { ?item wdt:P230 ?icaoRaw . }
  OPTIONAL { ?item wdt:P240 ?callsignRaw . }
  OPTIONAL {
    ?item wdt:P17 ?country .
    ?country rdfs:label ?countryLabel .
    FILTER(LANG(?countryLabel) = "en")
  }
  OPTIONAL { ?item wdt:P571 ?inceptionRaw . }
  OPTIONAL { ?item wdt:P576 ?dissolvedRaw . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
  FILTER(BOUND(?iataRaw) || BOUND(?icaoRaw) || BOUND(?callsignRaw))
}
GROUP BY ?item ?itemLabel
ORDER BY LCASE(STR(?itemLabel))
LIMIT 20000
"""


def split_values(value: str | None, pattern: str) -> list[str]:
    if not value:
        return []
    values = sorted({part.strip().upper() for part in value.split("|") if part.strip()})
    return [item for item in values if re.fullmatch(pattern, item)]


def normalize_binding(binding: dict[str, Any]) -> dict[str, Any] | None:
    item_url = binding.get("item", {}).get("value", "")
    match = re.search(r"/(Q[0-9]+)$", item_url)
    if not match:
        return None
    name = binding.get("itemLabel", {}).get("value", "").strip()
    if not name:
        return None

    def raw(key: str) -> str:
        return binding.get(key, {}).get("value", "")

    iata = split_values(raw("iataValues"), r"[A-Z0-9]{2}")
    icao = split_values(raw("icaoValues"), r"[A-Z0-9]{3}")
    callsigns = sorted({x.strip().upper() for x in raw("callsignValues").split("|") if x.strip()})
    countries = sorted({x.strip() for x in raw("countryValues").split("|") if x.strip()})
    dissolved = raw("dissolved")
    inception = raw("inception")
    return {
        "wikidataId": match.group(1),
        "name": name,
        "iataCodes": iata,
        "icaoCodes": icao,
        "callsigns": callsigns,
        "countries": countries,
        "inception": inception or None,
        "dissolution": dissolved or None,
        "operatingStatus": "dissolved" if dissolved else "not_verified",
        "wikidataUrl": item_url,
    }


def fetch_bindings(retries: int = 4) -> list[dict[str, Any]]:
    body = urllib.parse.urlencode({"query": QUERY, "format": "json"}).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=55) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload["results"]["bindings"]
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            code = getattr(exc, "code", None)
            if code == 429 or (code and code >= 500) or isinstance(exc, (urllib.error.URLError, TimeoutError)):
                if attempt + 1 < retries:
                    time.sleep(min(60, 5 * (2 ** attempt)))
                    continue
            raise RuntimeError(f"Wikidata Query Service request failed: {exc}") from exc
    raise RuntimeError("Wikidata Query Service request exhausted retries")


def build_records(bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        record = normalize_binding(binding)
        if not record:
            continue
        existing = by_id.get(record["wikidataId"])
        if existing is None:
            by_id[record["wikidataId"]] = record
        else:
            for field in ("iataCodes", "icaoCodes", "callsigns", "countries"):
                existing[field] = sorted(set(existing[field]) | set(record[field]))
            if not existing["inception"]:
                existing["inception"] = record["inception"]
            if not existing["dissolution"]:
                existing["dissolution"] = record["dissolution"]
                existing["operatingStatus"] = record["operatingStatus"]
    return sorted(by_id.values(), key=lambda row: (row["name"].casefold(), row["wikidataId"]))


def canonical_bytes(records: list[dict[str, Any]]) -> bytes:
    return (json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def update_manifest(dataset_path: str, records: list[dict[str, Any]], digest: str, size: int) -> None:
    manifest_path = ROOT / "navigation_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    datasets = [d for d in manifest.get("datasets", []) if d.get("id") != "global_airline_directory"]
    datasets.append({
        "id": "global_airline_directory",
        "path": dataset_path,
        "downloadUrl": "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/" + dataset_path,
        "available": True,
        "recordCount": len(records),
        "sizeBytes": size,
        "sha256": digest,
        "sourceProvider": "Wikidata structured data",
        "sourceUrl": SOURCE_URL,
        "coverage": "Worldwide airline entities with at least one IATA, ICAO or callsign identifier recorded in Wikidata",
        "license": LICENSE,
        "licenseStatus": "CC0_structured_data",
        "dataCycle": "weekly_snapshot",
        "effectiveDate": "",
        "expiryDate": "",
        "provenanceVerification": "provider_CC0_policy",
        "operationallyAvailable": False,
    })
    manifest["datasets"] = sorted(datasets, key=lambda item: item.get("id", ""))
    manifest.setdefault("capabilities", {})["globalAirlineDirectory"] = True
    manifest.setdefault("statistics", {})["globalAirlineDirectory"] = len(records)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="airlines/global_airlines.json")
    parser.add_argument("--manifest-only", action="store_true")
    args = parser.parse_args()
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    bindings = fetch_bindings()
    records = build_records(bindings)
    if len(records) < 100:
        raise RuntimeError(f"Refusing to publish suspiciously small airline result: {len(records)} records")
    if len({row["wikidataId"] for row in records}) != len(records):
        raise RuntimeError("Duplicate Wikidata entity identifiers found")

    payload = {
        "schemaVersion": 1,
        "dataset": "flighttempo-global-airline-directory",
        "source": {"name": "Wikidata structured data", "url": SOURCE_URL, "license": LICENSE},
        "description": "Worldwide airline reference directory; not a timetable or proof of current operations.",
        "recordCount": len(records),
        "records": records,
    }
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    output.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    update_manifest(args.output, records, digest, len(encoded))

    meta = {
        "source": "Wikidata structured data",
        "sourceUrl": SOURCE_URL,
        "license": LICENSE,
        "licenceStatus": "CC0_structured_data",
        "recordCount": len(records),
        "sizeBytes": len(encoded),
        "sha256": digest,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "notes": "Operating status is marked not_verified unless a dissolution date is explicitly present. No schedules or route frequencies are inferred.",
    }
    (output.parent / "global_airlines_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Built {len(records)} airline records; {len(encoded)} bytes; sha256={digest}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
