#!/usr/bin/env python3
"""Fetch and build the current French SIA SID/STAR reference dataset.

The source is the official eAIP package listed in the SIA free-disposition
catalogue. Only DATA SID and DATA STAR sheets listed by the current GEN 0.4
index are fetched. Existing FAA and legacy procedure files are never replaced.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CATALOG_URL = "https://www.sia.aviation-civile.gouv.fr/produits-numeriques-en-libre-disposition/eaip.html"
PROCEDURE_CSV = ROOT / "procedures/europe/france/sid_star_legs.csv"
PROCEDURE_META = ROOT / "procedures/europe/france/meta.json"
NAV_MANIFEST = ROOT / "navigation_manifest.json"
DATASET_ID = "france_sia_sid_star_legs"
DOWNLOAD_URL = "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/procedures/europe/france/sid_star_legs.csv"
LICENSE_URL = "https://www.sia.aviation-civile.gouv.fr/produits-numeriques-en-libre-disposition/eaip/zip-eaip-complet-airac-11-26.html"
OPEN_LICENSE_URL = "https://www.sia.aviation-civile.gouv.fr/produits-numeriques-en-libre-disposition.html"
MAX_INDEX_BYTES = 20 * 1024 * 1024
MAX_PDF_BYTES = 20 * 1024 * 1024
USER_AGENT = "FlightTempo-Commercial-Navdata/1.0 (+https://github.com/julienvergouts-code/flighttempo-data)"


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.parts)).strip()


def parse_catalog_issues(catalog_text: str) -> list[dict]:
    text = re.sub(r"\s+", " ", catalog_text)
    pattern = re.compile(
        r"ZIP\s+eAIP\s+complet\s+AIRAC\s+(\d{1,2}/\d{2}).{0,250}?"
        r"en\s+vigueur\s+du\s+(\d{2}/\d{2}/\d{4})\s+au\s+(\d{2}/\d{2}/\d{4})",
        re.IGNORECASE,
    )
    issues = []
    for cycle, effective_raw, expiry_raw in pattern.findall(text):
        effective = datetime.strptime(effective_raw, "%d/%m/%Y").date()
        expiry = datetime.strptime(expiry_raw, "%d/%m/%Y").date()
        issues.append({
            "cycle": cycle,
            "effectiveDate": effective.isoformat(),
            "expiryDate": expiry.isoformat(),
        })
    return issues


def select_current_issue(issues: list[dict], today: date | None = None) -> dict:
    today = today or date.today()
    current = [
        issue for issue in issues
        if date.fromisoformat(issue["effectiveDate"]) <= today <= date.fromisoformat(issue["expiryDate"])
    ]
    if not current:
        raise ValueError("SIA catalogue has no eAIP package effective today")
    return max(current, key=lambda issue: issue["effectiveDate"])


def issue_base_url(issue: dict) -> str:
    effective = date.fromisoformat(issue["effectiveDate"])
    month = effective.strftime("%b").upper()
    folder = f"eAIP_{effective.day:02d}_{month}_{effective.year}"
    return (
        "https://www.sia.aviation-civile.gouv.fr/media/dvd/"
        f"{folder}/FRANCE/AIRAC-{effective.isoformat()}"
    )


def discover_documents(index_text: str) -> list[dict]:
    """Read SID/STAR PDF names from the current official GEN 0.4 index."""
    normalized = re.sub(r"\s+", " ", index_text.upper())
    pattern = re.compile(
        r"\bAD\s+2\s+([A-Z0-9]{4})\s+DATA\s+(SID|STAR)\s+(.+?)"
        r"\s+\d{1,2}\s+[A-Z]{3}\s+20\d{2}\b"
    )
    found = {}
    for match in pattern.finditer(normalized):
        airport, kind, description = match.groups()
        description = re.sub(r"\s+", " ", description).strip(" -")
        if not description or len(description) > 100:
            continue
        suffix = re.sub(r"[^A-Z0-9-]+", "_", description).strip("_")
        filename = f"AD_2_{airport}_DATA_{kind}_{suffix}.pdf"
        found[(airport, filename)] = {
            "airport": airport,
            "kind": kind,
            "filename": filename,
        }
    return sorted(found.values(), key=lambda item: (item["airport"], item["kind"], item["filename"]))


def fetch(url: str, limit: int) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"download exceeds {limit} byte safety limit: {url}")
    return raw


def extract_index_text(raw_pdf: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Install pypdf>=5,<7 to read the SIA index PDF") from exc
    reader = PdfReader(io.BytesIO(raw_pdf), strict=True)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def download_documents(documents: list[dict], charts_base_url: str, directory: Path) -> list[dict]:
    def one(document: dict) -> dict:
        url = f"{charts_base_url}/{document['airport']}/{document['filename']}"
        raw = fetch(url, MAX_PDF_BYTES)
        if not raw.startswith(b"%PDF-"):
            raise ValueError(f"official SIA link did not return a PDF: {url}")
        path = directory / document["filename"]
        path.write_bytes(raw)
        return {**document, "url": url, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

    downloaded = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(one, document) for document in documents]
        for future in concurrent.futures.as_completed(futures):
            downloaded.append(future.result())
    return sorted(downloaded, key=lambda item: (item["airport"], item["kind"], item["filename"]))


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_bytes(data)
    temp_path.replace(path)


def register_manifest(csv_path: Path, meta: dict) -> dict:
    raw = csv_path.read_bytes()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        import csv
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("SIA output CSV is empty")
    if len(rows) != meta.get("recordCount"):
        raise ValueError("SIA output record count does not match parser report")
    counts = {
        kind: sum(row["procedure_type"] == kind for row in rows)
        for kind in ("SID", "STAR")
    }
    if not all(counts.values()):
        raise ValueError(f"SIA import must contain both SIDs and STARs: {counts}")

    dataset = {
        "id": DATASET_ID,
        "path": "procedures/europe/france/sid_star_legs.csv",
        "downloadUrl": DOWNLOAD_URL,
        "available": True,
        "recordCount": len(rows),
        "sizeBytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sourceProvider": "Service de l'Information Aeronautique (SIA France)",
        "sourceUrl": meta["indexUrl"],
        "coverage": "France AIP aerodromes represented by current GEN 0.4 DATA SID/STAR index",
        "license": "SIA Licence Ouverte / Open Licence",
        "licenseUrl": OPEN_LICENSE_URL,
        "licenseStatus": "verified_exact_eAIP_product_linked_to_open_license",
        "commercialUseAllowed": True,
        "attribution": meta["attribution"],
        "dataCycle": meta["airacEffectiveDate"],
        "effectiveDate": meta["airacEffectiveDate"],
        "expiryDate": meta["expiryDate"],
        "provenanceVerification": "official_SIA_eAIP_GEN_0_4_index",
        "downloadPurpose": "regional_reference_only",
        "operationallyAvailable": False,
        "status": "current_cycle_regional_reference_dataset",
    }
    manifest = json.loads(NAV_MANIFEST.read_text(encoding="utf-8"))
    datasets = [item for item in manifest.get("datasets", []) if item.get("id") != DATASET_ID]
    datasets.append(dataset)
    manifest["datasets"] = datasets
    manifest.setdefault("statistics", {})["franceSiaSidStarLegs"] = len(rows)
    manifest.setdefault("capabilities", {})["franceSids"] = counts["SID"] > 0
    manifest["capabilities"]["franceStars"] = counts["STAR"] > 0
    coverage = manifest.setdefault("regionalProcedureCoverage", {}).setdefault("europe", {})
    coverage["status"] = "partial_current_france_sia_ingested"
    coverage["operationallyAvailable"] = False
    coverage["confirmedProcedureCountries"] = ["FR"]
    coverage["candidateProcedureCountries"] = []
    coverage["summary"] = (
        "France SID/STAR reference legs are imported from the current SIA eAIP "
        "under its commercial-use Open Licence. This is partial national coverage; "
        "no complete Europe-wide IFR database is available."
    )
    coverage["vfrOnlyProviders"] = ["OpenFlightMaps"]
    coverage["sources"] = [
        item for item in coverage.get("sources", [])
        if item.get("id") != "FR_SIA_EAIP_DATA_PDFS"
    ]
    coverage["sources"].append({
        "id": "FR_SIA_EAIP_DATA_PDFS",
        "jurisdiction": "FR",
        "provider": "Service de l'Information Aeronautique (SIA France)",
        "sourceUrl": meta["indexUrl"],
        "format": ["official eAIP GEN 0.4 index", "PDF DATA SID/STAR tables"],
        "procedureScope": ["SIDs", "STARs"],
        "license": "SIA Licence Ouverte / Open Licence",
        "licenseUrl": OPEN_LICENSE_URL,
        "redistribution": "commercial_public_redistribution",
        "licenseStatus": "verified_exact_eAIP_product_linked_to_open_license",
        "attribution": meta["attribution"],
        "cycle": meta["airacEffectiveDate"],
        "effectiveDate": meta["airacEffectiveDate"],
        "expiryDate": meta["expiryDate"],
        "sourceStatus": "official_eAIP_DATA_procedure_source_commercial_reuse_confirmed",
        "dataStatus": "current_cycle_imported",
        "recordCount": len(rows),
        "procedureTypeCounts": counts,
        "sourceDocumentCount": len(meta["sourceDocuments"]),
        "operationallyAvailable": False,
        "notes": "Do not treat regional reference procedure legs as an approved operational navigation database."
    })
    manifest["procedureCoverageStatus"] = (
        "FAA_US_NAS_CYCLE_PINNED; FRANCE_SIA_CURRENT_SIDS_STARS; "
        "NO_COMPLETE_WORLDWIDE_IFR_PROCEDURES"
    )
    manifest["generatedAtUtc"] = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    NAV_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dataset


def run(dry_run: bool = False) -> dict:
    catalog = fetch(CATALOG_URL, MAX_INDEX_BYTES).decode("utf-8", errors="replace")
    parser = TextExtractor()
    parser.feed(catalog)
    issue = select_current_issue(parse_catalog_issues(parser.text))
    base = issue_base_url(issue)
    index_url = f"{base}/pdf/FR-GEN-0.4-fr-FR.pdf"
    charts_base_url = f"{base}/html/eAIP/Cartes"
    index_text = extract_index_text(fetch(index_url, MAX_INDEX_BYTES))
    documents = discover_documents(index_text)
    if not documents:
        raise ValueError("Current SIA GEN 0.4 index contained no DATA SID/STAR PDFs; refusing empty replacement")
    counts_by_kind = {kind: sum(doc["kind"] == kind for doc in documents) for kind in ("SID", "STAR")}
    if not all(counts_by_kind.values()):
        raise ValueError(f"Current SIA index must contain both SIDs and STARs: {counts_by_kind}")

    with tempfile.TemporaryDirectory(prefix="flighttempo-sia-") as temp:
        temp_dir = Path(temp)
        sources = download_documents(documents, charts_base_url, temp_dir)
        output_csv = temp_dir / "sid_star_legs.csv"
        output_meta = temp_dir / "meta.json"
        command = [
            sys.executable, str(ROOT / "scripts/import_sia_eaip_procedures.py"),
            "--pdf-dir", str(temp_dir),
            "--airac-effective-date", issue["effectiveDate"],
            "--source-base-url", charts_base_url,
            "--output", str(output_csv),
            "--manifest", str(output_meta),
        ]
        subprocess.run(command, check=True, cwd=ROOT, capture_output=not dry_run, text=True)
        meta = json.loads(output_meta.read_text(encoding="utf-8"))
        parser_sources = meta.get("sourceDocuments", [])
        if len(parser_sources) != len(documents):
            raise ValueError(
                f"parser saw {len(parser_sources)} of {len(documents)} indexed SID/STAR PDFs"
            )
        unparsed = [item for item in parser_sources if item.get("record_count", 0) <= 0]
        if unparsed:
            raise ValueError(
                "SIA format/layout changed or parser missed indexed PDFs; refusing partial publish: "
                + ", ".join(item["source_file"] for item in unparsed[:10])
            )
        meta.update({
            "license": "SIA Licence Ouverte / Open Licence",
            "licenseUrl": OPEN_LICENSE_URL,
            "licenseStatus": "verified_exact_eAIP_product_linked_to_open_license",
            "commercialUseAllowed": True,
            "attribution": "Service de l'Information Aeronautique (SIA France); include source and last update date; do not imply SIA endorsement.",
            "catalogUrl": CATALOG_URL,
            "indexUrl": index_url,
            "airacCycle": issue["cycle"],
            "airacEffectiveDate": issue["effectiveDate"],
            "expiryDate": issue["expiryDate"],
            "sourceDocumentCount": len(sources),
            "indexedDocumentCount": len(documents),
            "procedureTypeDocumentCounts": counts_by_kind,
            "operationallyAvailable": False,
        })
        if dry_run:
            raw = output_csv.read_bytes()
            with output_csv.open("r", encoding="utf-8-sig", newline="") as handle:
                import csv
                rows = list(csv.DictReader(handle))
            counts = {kind: sum(row["procedure_type"] == kind for row in rows) for kind in ("SID", "STAR")}
            return {
                "airacCycle": issue["cycle"],
                "effectiveDate": issue["effectiveDate"],
                "expiryDate": issue["expiryDate"],
                "sourceDocumentCount": len(sources),
                "recordCount": len(rows),
                "procedureTypeCounts": counts,
                "sizeBytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }

        meta["recordCount"] = meta.get("recordCount", 0)
        atomic_write(PROCEDURE_CSV, output_csv.read_bytes())
        atomic_write(PROCEDURE_META, (json.dumps(meta, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        dataset = register_manifest(PROCEDURE_CSV, meta)
        return {
            "airacCycle": issue["cycle"],
            "effectiveDate": issue["effectiveDate"],
            "sourceDocumentCount": len(sources),
            "recordCount": dataset["recordCount"],
            "procedureTypeCounts": meta.get("procedureTypeCounts", {}),
            "sha256": dataset["sha256"],
            "path": dataset["path"],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and validate without changing repository files")
    args = parser.parse_args()
    try:
        result = run(args.dry_run)
    except (OSError, ValueError, URLError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"SIA import failed closed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
