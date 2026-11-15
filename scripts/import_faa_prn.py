#!/usr/bin/env python3
"""Import FAA Prohibitions, Restrictions and Notices (PRN) KICZ references.

This is a structured index of FAA-published KICZ NOTAM PDFs, not a live
NOTAM-status service. A notice listed on the PRN page may have been amended
or cancelled elsewhere; preserve that uncertainty in every output record.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PAGE = "https://www.faa.gov/air_traffic/publications/us_restrictions/index.cfm"
OUTPUT = ROOT / "airspace" / "faa_prn_notams.json"
FILTER = ROOT / "airspace" / "airspace_filter.json"
POLICY = ROOT / "airspace" / "route_policy.json"
APP_MANIFEST = ROOT / "navigation_manifest.json"
ROOT_MANIFEST = ROOT / "manifest.json"
AIRSPACE_META = ROOT / "airspace" / "meta.json"
USER_AGENT = "FlightTempoDataImporter/1.0 (+https://github.com/julienvergouts-code/flighttempo-data)"


class AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self.current = {"href": dict(attrs).get("href"), "text": []}

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current is not None:
            self.links.append({
                "href": self.current.get("href"),
                "text": " ".join(" ".join(self.current["text"]).split())
            })
            self.current = None


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def section(text: str, start_marker: str, stop_markers: tuple[str, ...]) -> str:
    upper = text.upper()
    start = upper.find(start_marker.upper())
    if start < 0:
        return ""
    start += len(start_marker)
    ends = [upper.find(marker.upper(), start) for marker in stop_markers]
    ends = [position for position in ends if position >= 0]
    end = min(ends) if ends else len(text)
    return text[start:end].strip()


def extract_pdf_text(payload: bytes) -> str:
    reader = PdfReader(BytesIO(payload))
    return "\n".join((page.extract_text() or "") for page in reader.pages).strip()


def parse_notice(link: dict, base_url: str, geometry_by_code: dict) -> dict:
    href = link.get("href") or ""
    pdf_url = urllib.parse.urljoin(base_url, href)
    title = link.get("text") or pdf_url
    download_status = "downloaded"
    pdf_sha256 = None
    pdf_size = 0
    text = ""
    try:
        payload = fetch_bytes(pdf_url)
        pdf_sha256 = hashlib.sha256(payload).hexdigest()
        pdf_size = len(payload)
        text = extract_pdf_text(payload)
    except Exception as exc:  # keep the index record even if one PDF is unavailable
        download_status = f"download_failed: {type(exc).__name__}: {exc}"

    combined = (title + "\n" + text).upper()
    match = re.search(r"KICZ\s+(?:NOTAM\s+)?(A\d{4}/\d{2})", combined)
    if not match:
        match = re.search(r"\b(A\d{4}/\d{2})\b", combined)
    notam_id = match.group(1) if match else None

    # FIR/UIR identifiers in FAA KICZ notices are explicitly parenthesized.
    # Do not harvest arbitrary four-letter words from prose lines mentioning FIR.
    fir_codes = set(re.findall(r"\(\s*([A-Z]{4})\s*\)", combined))
    fir_codes = sorted(fir_codes)

    applicability = section(
        text, "A. APPLICABILITY",
        ("B. PERMITTED OPERATIONS", "B. EXCEPTIONS", "B. PROHIBITED OPERATIONS", "B. GENERAL")
    )
    permitted = section(
        text, "B. PERMITTED OPERATIONS",
        ("C. EXCEPTIONS", "C. SPECIAL PROVISIONS", "C. GENERAL", "D. ")
    )
    exceptions = section(
        text, "C. EXCEPTIONS",
        ("D. ", "E. ", "END OF NOTAM")
    )

    scope = applicability.upper()
    scope_tags = []
    if "U.S. AIR CARRIERS" in scope or "UNITED STATES AIR CARRIERS" in scope:
        scope_tags.append("US_AIR_CARRIERS")
    if "AIRMAN CERTIFICATE" in scope and "FAA" in scope:
        scope_tags.append("FAA_AIRMAN_CERTIFICATE_HOLDERS")
    if "AIRCRAFT REGISTERED IN THE UNITED STATES" in scope or "U.S.-REGISTERED AIRCRAFT" in scope:
        scope_tags.append("US_REGISTERED_AIRCRAFT")
    if "U.S. PERSONS" in scope or "UNITED STATES PERSONS" in scope:
        scope_tags.append("US_PERSONS")

    pointer_only = "POINTER NOTAM" in combined
    if pointer_only:
        restriction_type = "pointer_only"
    elif "PROHIBITION" in combined or "PROHIBITED FROM OPERATING" in combined:
        restriction_type = "prohibition"
    elif "ADVISORY" in combined:
        restriction_type = "advisory"
    else:
        restriction_type = "reference"

    affected_firs = []
    for code in fir_codes:
        feature_ids = geometry_by_code.get(code, [])
        affected_firs.append({
            "firCode": code,
            "geometryFeatureIds": feature_ids,
            "geometryAvailable": bool(feature_ids)
        })

    validity_lines = [
        line.strip() for line in text.splitlines()
        if "UNTIL" in line.upper() or "PERM" in line.upper()
    ]
    return {
        "notamId": notam_id,
        "title": title,
        "pdfUrl": pdf_url,
        "pdfSha256": pdf_sha256,
        "pdfSizeBytes": pdf_size,
        "downloadStatus": download_status,
        "restrictionType": restriction_type,
        "pointerOnly": pointer_only,
        "affectedFirs": affected_firs,
        "appliesTo": scope_tags,
        "applicabilityText": applicability,
        "permittedOperationsText": permitted,
        "exceptionsText": exceptions,
        "validityText": validity_lines,
        "permanentUntilCancelledText": any("UNTIL PERM" in line.upper() for line in validity_lines),
        "currentnessVerified": False,
        "currentnessStatus": "listed_on_FAA_PRN_page; live NOTAM amendments/cancellations not independently checked",
        "rawPdfText": text[:30000]
    }


def main() -> None:
    html = fetch_bytes(SOURCE_PAGE).decode("utf-8", errors="replace")
    parser = AnchorParser()
    parser.feed(html)
    base_url = SOURCE_PAGE

    kicz_links = []
    sfar_links = []
    for link in parser.links:
        text = link["text"].upper()
        href = link.get("href") or ""
        if "KICZ" in text and "NOTAM" in text:
            kicz_links.append(link)
        elif "SFAR" in text or "SPECIAL FEDERAL AVIATION REGULATION" in text:
            sfar_links.append(link)

    if not kicz_links:
        raise RuntimeError("No KICZ NOTAM links found on the official FAA PRN page; page structure may have changed.")

    geometry_by_code = {}
    geo_path = ROOT / "navigation" / "airspace" / "openaip_fir_boundaries.geojson"
    if geo_path.is_file():
        geo = json.loads(geo_path.read_text(encoding="utf-8"))
        for index, feature in enumerate(geo.get("features", [])):
            props = feature.get("properties") or {}
            code = str(props.get("flightTempoFirCode") or props.get("designator") or props.get("icaoCode") or "").upper()
            if code:
                geometry_by_code.setdefault(code, []).append(feature.get("id", index))

    records = [parse_notice(link, base_url, geometry_by_code) for link in kicz_links]
    sfar_refs = [
        {"title": link["text"], "url": urllib.parse.urljoin(base_url, link.get("href") or "")}
        for link in sfar_links
    ]

    payload = {
        "schemaVersion": 1,
        "provider": "FAA",
        "dataset": "Prohibitions, Restrictions and Notices (PRN) — KICZ NOTAM references",
        "sourcePage": SOURCE_PAGE,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "currentnessWarning": "The FAA PRN page is an official index, not a live NOTAM cancellation/status API. Do not hard-block a route solely from this file without checking the current NOTAM and applicability.",
        "records": records,
        "sfarReferences": sfar_refs
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    filter_data = json.loads(FILTER.read_text(encoding="utf-8")) if FILTER.is_file() else {}
    filter_data["faaRestrictions"] = [
        {
            "notamId": record["notamId"],
            "title": record["title"],
            "restrictionType": record["restrictionType"],
            "pointerOnly": record["pointerOnly"],
            "affectedFirs": record["affectedFirs"],
            "appliesTo": record["appliesTo"],
            "currentnessVerified": False,
            "currentnessStatus": record["currentnessStatus"],
            "sourceUrl": record["pdfUrl"]
        }
        for record in records
    ]
    filter_data["conditionalRestrictions"] = [
        {
            "notamId": record["notamId"],
            "affectedFirs": record["affectedFirs"],
            "appliesTo": record["appliesTo"],
            "restrictionType": record["restrictionType"],
            "pointerOnly": record["pointerOnly"],
            "currentnessVerified": False,
            "action": "warn_and_suggest_avoid_pending_live_NOTAM_check",
            "userOverrideAllowed": False
        }
        for record in records
        if record["restrictionType"] == "prohibition" and not record["pointerOnly"] and record["appliesTo"]
    ]
    filter_data["faaRestrictionSource"] = {
        "provider": "FAA",
        "sourcePage": SOURCE_PAGE,
        "status": "official_PRN_index_scraped; live_NOTAM_currentness_not_verified",
        "recordCount": len(records),
        "sfarReferenceCount": len(sfar_refs)
    }
    filter_data.setdefault("hardNoFlyFirs", [])
    FILTER.write_text(json.dumps(filter_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    policy = json.loads(POLICY.read_text(encoding="utf-8")) if POLICY.is_file() else {}
    policy.setdefault("officialRestrictions", {})
    policy["officialRestrictions"].update({
        "faaSource": "FAA PRN KICZ NOTAM index",
        "matchApplicabilityScopeBeforeApplying": True,
        "requireLiveNotamVerificationBeforeHardBlock": True,
        "listedRestrictionAction": "warn_and_suggest_avoid",
        "userOverrideAllowedForVerifiedLegalRestrictions": False,
        "neverInferRestrictionsFromAirlineNationality": True
    })
    POLICY.write_text(json.dumps(policy, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    app = json.loads(APP_MANIFEST.read_text(encoding="utf-8"))
    datasets = [d for d in app.get("datasets", []) if d.get("id") not in {"faa_prn_notams", "airspace_filter", "route_policy"}]
    for dataset_id, path, count, license_name, status in (
        ("faa_prn_notams", "airspace/faa_prn_notams.json", len(records), "FAA government source; public information", "reference_only_currentness_unverified"),
        ("airspace_filter", "airspace/airspace_filter.json", len(filter_data.get("activeAdvisories", [])), "EASA acknowledgement + OpenAIP CC BY-NC 4.0 + FAA reference", "advisory_and_conditional_reference_only"),
        ("route_policy", "airspace/route_policy.json", 1, "FlightTempo original configuration", "route_preview_policy")
    ):
        raw = (ROOT / path).read_bytes()
        datasets.append({
            "id": dataset_id, "path": path,
            "downloadUrl": "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/" + path,
            "available": True, "recordCount": count, "sizeBytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "license": license_name, "status": status, "operationallyAvailable": False
        })
    app["datasets"] = datasets
    app.setdefault("capabilities", {})["faaPrnReferences"] = True
    app["capabilities"]["faaLiveNotamCurrentnessVerified"] = False
    APP_MANIFEST.write_text(json.dumps(app, indent=2) + "\n", encoding="utf-8")

    root_manifest = json.loads(ROOT_MANIFEST.read_text(encoding="utf-8"))
    root_datasets = [d for d in root_manifest.get("datasets", []) if d.get("id") != "faa-prn-notams"]
    raw = OUTPUT.read_bytes()
    root_datasets.append({
        "id": "faa-prn-notams", "path": "airspace/faa_prn_notams.json",
        "source": "FAA PRN KICZ NOTAM index", "airacCycle": None,
        "effectiveDate": None, "expiryDate": None,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "licenceStatus": "FAA_public_information_reference_currentness_unverified",
        "coverage": "FAA-published international prohibition/restriction notice references",
        "recordCount": len(records)
    })
    root_manifest["datasets"] = root_datasets
    root_manifest["generatedAtUtc"] = datetime.now(timezone.utc).isoformat()
    ROOT_MANIFEST.write_text(json.dumps(root_manifest, indent=2) + "\n", encoding="utf-8")

    meta = json.loads(AIRSPACE_META.read_text(encoding="utf-8")) if AIRSPACE_META.is_file() else {
        "source": "FlightTempo route policy and machine-readable conflict-zone advisory datasets",
        "airacCycle": None, "effectiveDate": None, "expiryDate": None, "sha256": None,
        "licenceStatus": "mixed_source_rights_per_file_metadata_applies", "files": []
    }
    file_paths = ["airspace_filter.json", "route_policy.json", "faa_prn_notams.json"]
    files = []
    for name in file_paths:
        path = ROOT / "airspace" / name
        raw = path.read_bytes()
        files.append({
            "path": name, "sha256": hashlib.sha256(raw).hexdigest(),
            "sizeBytes": len(raw),
            "recordCount": len(records) if name == "faa_prn_notams.json" else (1 if name == "route_policy.json" else len(filter_data.get("activeAdvisories", [])))
        })
    meta["files"] = files
    AIRSPACE_META.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "kiczLinks": len(kicz_links),
        "downloadedPdfs": sum(1 for x in records if x["downloadStatus"] == "downloaded"),
        "sfarReferences": len(sfar_refs),
        "recordsWithFirCodes": sum(1 for x in records if x["affectedFirs"]),
        "recordsWithApplicabilityScope": sum(1 for x in records if x["appliesTo"])
    }, indent=2))


if __name__ == "__main__":
    main()
