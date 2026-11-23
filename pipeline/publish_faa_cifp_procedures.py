#!/usr/bin/env python3
"""Publish FAA CIFP SID and STAR legs for the cycle in effect, unattended.

Source: FAA AeroNav CIFP (ARINC 424-18, FAACIFP18), US government public-domain
data. The importer downloads the cycle whose effective date has passed, decodes
the primary SID (section P, subsection D) and STAR (subsection E) leg records
into the CSV layout the app already reads, and publishes them only if every
check passes. Nothing is written on failure.

Why it can run unattended: the previous cycle's published CSV is the ground
truth for column meaning. A new cycle changes only a minority of procedures, so
most unchanged legs must decode to exactly the same row. If the decoder
misreads a column, that overlap collapses and publication stops with a
per-column report instead of shipping wrong altitudes or fixes.

Approaches are intentionally not published here: their record count differs from
the packaged file by an unexplained 6,509 and that dataset stays blocked.
This is reference data, not an approved operational navigation database.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

CYCLE_ANCHOR = date(2026, 11, 26)  # known FAA/AIRAC effective date; cycles repeat every 28 days
CYCLE_DAYS = 28
ARCHIVE_URL = "https://aeronav.faa.gov/Upload_313-d/cifp/CIFP_{token}.zip"
USER_AGENT = "FlightTempo-Data-Maintenance/1.0 (+https://github.com/julienvergouts-code/flighttempo-data)"
DOWNLOAD_BASE = "https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/"

RECORD_WIDTH = 132
MEMBER = "FAACIFP18"
MAX_ARCHIVE_BYTES = 150_000_000
MAX_MEMBER_BYTES = 300_000_000

COLUMNS = ["airport_icao", "procedure_id", "route_type", "transition_id", "seq", "fix_id",
           "path_terminator", "alt_desc", "alt1", "speed_limit_kt", "source"]
STRUCTURE_KEY = ("airport_icao", "procedure_id", "route_type", "transition_id", "seq")
# ARINC 424 section P, subsection D = SID, E = STAR (F = approach, not published here).
DATASETS = {
    "D": {"id": "sids", "rel": "procedures/sids/sids.csv", "meta": "procedures/sids/meta.json",
          "coverage": "United States / FAA National Airspace System — departure procedures"},
    "E": {"id": "stars", "rel": "procedures/stars/stars.csv", "meta": "procedures/stars/meta.json",
          "coverage": "United States / FAA National Airspace System — arrival procedures"},
}
PATH_TERMINATORS = set(
    "AF CA CD CF CI CR DF FA FC FD FM HA HF HM IF PI RF TF VA VD VI VM VR".split())

MIN_ROW_RATIO = float(os.getenv("CIFP_MIN_ROW_RATIO", "0.85"))
MAX_ROW_RATIO = float(os.getenv("CIFP_MAX_ROW_RATIO", "1.15"))
MIN_EQUIVALENCE = float(os.getenv("CIFP_MIN_EQUIVALENCE", "0.80"))
MIN_VALID_PATH_TERMINATOR = float(os.getenv("CIFP_MIN_VALID_PATH_TERMINATOR", "0.999"))
MIN_FIX_WITNESS = float(os.getenv("CIFP_MIN_FIX_WITNESS", "0.70"))
MIN_ROWS = int(os.getenv("CIFP_MIN_ROWS", "5000"))

log = logging.getLogger("faa-cifp-procedures")


class CifpError(RuntimeError):
    """Raised for any condition that must stop publication."""


# --------------------------------------------------------------------------- cycles

def cycle_effective_on_or_before(today: date) -> date:
    return CYCLE_ANCHOR + timedelta(days=CYCLE_DAYS * ((today - CYCLE_ANCHOR).days // CYCLE_DAYS))


def cycle_expiry(effective: date) -> date:
    return effective + timedelta(days=CYCLE_DAYS - 1)


def airac_label(effective: date) -> str:
    """AIRAC identifier such as 2611 (29 Oct 2026) or 2612 (26 Nov 2026)."""
    first = effective
    while (first - timedelta(days=CYCLE_DAYS)).year == effective.year:
        first -= timedelta(days=CYCLE_DAYS)
    return f"{effective.year % 100:02d}{(effective - first).days // CYCLE_DAYS + 1:02d}"


def archive_url(effective: date) -> str:
    return ARCHIVE_URL.format(token=effective.strftime("%y%m%d"))


# --------------------------------------------------------------------------- decoding

def decode_line(line: str, number: int, source_tag: str) -> tuple[str, dict[str, str]] | str | None:
    """Return (subsection, row), 'continuation' for non-primary records, or None.

    Fixed ARINC 424-18 positions (0-based): airport 6:10, subsection 12,
    procedure 13:19, route type 19, transition 20:25, sequence 26:29, fix 29:34,
    continuation 38, path terminator 47:49, altitude description 82,
    altitude 1 83:88, speed limit 99:102.
    """
    if len(line) != RECORD_WIDTH:
        raise CifpError(f"Line {number}: expected {RECORD_WIDTH} columns, got {len(line)}")
    if line[0] != "S" or line[1:4] != "USA" or line[4] != "P":
        return None
    subsection = line[12]
    if subsection not in DATASETS:
        return None
    if line[38] not in ("0", "1"):
        return "continuation"
    airport, procedure = line[6:10].strip(), line[13:19].strip()
    if not airport or not procedure:
        raise CifpError(f"Line {number}: procedure record without airport or procedure identifier")
    seq_raw = line[26:29].strip()
    return subsection, {
        "airport_icao": airport,
        "procedure_id": procedure,
        "route_type": line[19].strip(),
        "transition_id": line[20:25].strip(),
        "seq": str(int(seq_raw)) if seq_raw.isdigit() else "",
        "fix_id": line[29:34].strip(),
        "path_terminator": line[47:49].strip(),
        "alt_desc": line[82].strip(),
        "alt1": line[83:88].strip(),
        "speed_limit_kt": line[99:102].strip(),
        "source": source_tag,
    }


def read_cifp_text(zip_path: Path) -> Iterable[tuple[int, str]]:
    if not zip_path.is_file() or zip_path.stat().st_size == 0:
        raise CifpError("CIFP archive is missing or empty")
    if zip_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise CifpError("CIFP archive exceeds the size limit")
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad:
            raise CifpError(f"ZIP integrity failed at member {bad}")
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or any(part in {"..", ""} for part in name.split("/")[:-1]):
                raise CifpError(f"Unsafe archive path: {info.filename}")
        try:
            info = zf.getinfo(MEMBER)
        except KeyError:
            raise CifpError(f"Archive lacks {MEMBER}") from None
        if info.file_size > MAX_MEMBER_BYTES:
            raise CifpError(f"{MEMBER} exceeds the size limit")
        with zf.open(info) as member:
            for number, raw in enumerate(io.TextIOWrapper(member, encoding="ascii", newline=""), 1):
                line = raw.rstrip("\r\n")
                if line:
                    yield number, line


def decode_archive(zip_path: Path, source_tag: str) -> tuple[dict[str, list[dict[str, str]]], dict[str, int]]:
    rows: dict[str, list[dict[str, str]]] = {meta["id"]: [] for meta in DATASETS.values()}
    stats = {"recordsScanned": 0, "continuationRecordsSkipped": 0}
    for number, line in read_cifp_text(zip_path):
        stats["recordsScanned"] += 1
        decoded = decode_line(line, number, source_tag)
        if decoded is None:
            continue
        if decoded == "continuation":
            stats["continuationRecordsSkipped"] += 1
            continue
        subsection, row = decoded
        rows[DATASETS[subsection]["id"]].append(row)
    for dataset_rows in rows.values():
        dataset_rows.sort(key=lambda r: (r["airport_icao"], r["procedure_id"], r["route_type"],
                                         r["transition_id"], int(r["seq"] or 0)))
    return rows, stats


# --------------------------------------------------------------------------- checks

def read_published(path: Path) -> tuple[str | None, list[dict[str, str]]]:
    if not path.is_file():
        return None, []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        directive = next(reader, None)
        header = next(reader, None)
        if not directive or directive[0] != "#version" or header != COLUMNS:
            return None, []
        return (directive[1] if len(directive) > 1 else None), [dict(zip(COLUMNS, row)) for row in reader if row]


def compare_with_previous(previous: list[dict[str, str]], new: list[dict[str, str]]) -> dict[str, Any]:
    """Share of previous legs that decode identically, plus per-column disagreement."""
    value = lambda r: tuple(r[c] for c in COLUMNS[:-1])  # noqa: E731  (source tag differs by cycle)
    kept = sum((Counter(map(value, previous)) & Counter(map(value, new))).values())
    by_structure: dict[tuple, list[dict[str, str]]] = defaultdict(list)
    for row in new:
        by_structure[tuple(row[c] for c in STRUCTURE_KEY)].append(row)
    column_mismatch: Counter = Counter()
    examples: list[str] = []
    structure_matched = 0
    for row in previous:
        candidates = by_structure.get(tuple(row[c] for c in STRUCTURE_KEY))
        if not candidates:
            continue
        structure_matched += 1
        if any(value(row) == value(c) for c in candidates):
            continue
        other = candidates[0]
        for column in COLUMNS[5:-1]:
            if row[column] != other[column]:
                column_mismatch[column] += 1
                if len(examples) < 10:
                    examples.append(f"{'/'.join(row[c] for c in STRUCTURE_KEY)} {column}: "
                                    f"{row[column]!r} (previous) vs {other[column]!r} (new)")
    return {"previousRows": len(previous), "identicalRows": kept,
            "identicalShare": round(kept / len(previous), 4) if previous else None,
            "structureMatched": structure_matched,
            "columnMismatch": dict(column_mismatch), "examples": examples}


def known_identifiers(root: Path) -> set[str] | None:
    """Fix and navaid identifiers from current NASR data; None if NASR data is not published yet."""
    nasr_fixes = root / "navigation/faa_nasr/fixes.csv"
    if not nasr_fixes.is_file():
        return None
    idents: set[str] = set()
    for rel in ("navigation/faa_nasr/fixes.csv", "navigation/faa_nasr/navaids.csv", "navigation/navaids/navaids.csv"):
        path = root / rel
        if path.is_file():
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                idents.update(r.get("ident", "").strip().upper() for r in csv.DictReader(handle))
    idents.discard("")
    return idents


def check_dataset(dataset_id: str, rows: list[dict[str, str]], previous: list[dict[str, str]],
                  previous_cycle: str | None, new_cycle: str, idents: set[str] | None) -> dict[str, Any]:
    report: dict[str, Any] = {"rows": len(rows), "airports": len({r["airport_icao"] for r in rows})}
    if len(rows) < MIN_ROWS:
        raise CifpError(f"{dataset_id}: only {len(rows)} rows (floor {MIN_ROWS}); refusing a truncated import")
    valid = sum(r["path_terminator"] in PATH_TERMINATORS for r in rows) / len(rows)
    report["validPathTerminatorShare"] = round(valid, 5)
    if valid < MIN_VALID_PATH_TERMINATOR:
        bad = Counter(r["path_terminator"] for r in rows if r["path_terminator"] not in PATH_TERMINATORS)
        raise CifpError(f"{dataset_id}: only {valid:.2%} of path terminators are valid ARINC 424 codes; "
                        f"the record layout probably changed. Top invalid values: {bad.most_common(5)}")
    if any(r["seq"] == "" for r in rows):
        raise CifpError(f"{dataset_id}: records with a non-numeric sequence number")
    witness = [r["fix_id"].upper() for r in rows if r["fix_id"] and not r["fix_id"].upper().startswith("RW")]
    if idents is not None and witness:
        share = sum(f in idents for f in witness) / len(witness)
        report["fixesFoundInNasrOrNavaidData"] = round(share, 4)
        if share < MIN_FIX_WITNESS:
            raise CifpError(f"{dataset_id}: only {share:.1%} of fix identifiers exist in NASR fixes or navaids "
                            f"(floor {MIN_FIX_WITNESS:.0%}); the fix column is probably misaligned")
    else:
        report["fixesFoundInNasrOrNavaidData"] = None
    if previous and previous_cycle != new_cycle:
        ratio = len(rows) / len(previous)
        report["rowRatioToPrevious"] = round(ratio, 4)
        if not MIN_ROW_RATIO <= ratio <= MAX_ROW_RATIO:
            raise CifpError(f"{dataset_id}: row count changed by {ratio - 1:+.1%} versus cycle {previous_cycle} "
                            f"({len(previous)} -> {len(rows)}); allowed {MIN_ROW_RATIO - 1:+.0%}..{MAX_ROW_RATIO - 1:+.0%}")
        comparison = compare_with_previous(previous, rows)
        report["equivalence"] = comparison
        if comparison["identicalShare"] < MIN_EQUIVALENCE:
            raise CifpError(
                f"{dataset_id}: only {comparison['identicalShare']:.1%} of cycle {previous_cycle} legs decode "
                f"identically in cycle {new_cycle} (floor {MIN_EQUIVALENCE:.0%}). Column disagreements: "
                f"{comparison['columnMismatch']}. Examples: {comparison['examples'][:5]}")
    else:
        report["equivalence"] = None
    return report


# --------------------------------------------------------------------------- output

def csv_bytes(cycle: str, rows: list[dict[str, str]]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)  # default CRLF terminator, as in the published files
    writer.writerow(["#version", cycle])
    writer.writerow(COLUMNS)
    writer.writerows([[r[c] for c in COLUMNS] for r in rows])
    return buf.getvalue().encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def build_artifacts(root: Path, effective: date, rows_by_dataset: dict[str, list[dict[str, str]]],
                    archive_sha: str, url: str, downloaded_at: str) -> dict[str, dict[str, Any]]:
    cycle = airac_label(effective)
    expiry = cycle_expiry(effective)
    artifacts: dict[str, dict[str, Any]] = {}
    for meta in DATASETS.values():
        rows = rows_by_dataset[meta["id"]]
        raw = csv_bytes(cycle, rows)
        digest = hashlib.sha256(raw).hexdigest()
        source = {
            "sourceTag": f"FAA_CIFP_{cycle}", "provider": "FAA AeroNav", "sourceUrl": url,
            "license": "US Government Public Domain (FAA AeroNav)", "licenseStatus": "public_domain",
            "redistributable": True, "dataCycle": cycle,
            "effectiveDate": effective.isoformat(), "expiryDate": expiry.isoformat(),
            "downloadedAt": downloaded_at, "coverage": meta["coverage"],
            "recordCount": len(rows), "airportCount": len({r["airport_icao"] for r in rows}),
            "sizeBytes": len(raw), "sha256": digest,
        }
        file_meta = {
            "source": "FAA AeroNav CIFP", "airacCycle": cycle,
            "effectiveDate": effective.isoformat(), "expiryDate": expiry.isoformat(),
            "sha256": digest,
            "licenceStatus": "US_government_public_domain_review_FAA_terms_and_error_notification",
            "sourceUrl": url, "licenseName": "US Government work / public domain",
            "coverage": "United States NAS only; no European coverage",
            "recordCount": len(rows), "sourceArchiveSha256": archive_sha,
            "files": [{"path": Path(meta["rel"]).name, "sha256": digest, "sizeBytes": len(raw)}],
            "notes": f"FAA CIFP cycle {cycle}, decoded unattended from ARINC 424 (primary leg records). "
                     "Not a worldwide procedure database; reference data only.",
        }
        artifacts[meta["id"]] = {"rel": meta["rel"], "meta_rel": meta["meta"], "raw": raw,
                                 "source": source, "file_meta": file_meta}
    return artifacts


def verify_staged(artifacts: dict[str, dict[str, Any]]) -> None:
    """Prove the exact artifact identity contract the daily manifest build relies on."""
    from import_xplane_navdata import load_procedure_metadata  # noqa: WPS433 (shared contract)
    with tempfile.TemporaryDirectory(prefix="cifp-verify-") as td:
        stage = Path(td)
        (stage / "procedures").mkdir()
        (stage / "procedures/source-manifest.json").write_text(
            json.dumps({"datasets": {k: v["source"] for k, v in artifacts.items()}}), encoding="utf-8")
        for dataset_id, art in artifacts.items():
            atomic_write(stage / art["rel"], art["raw"])
            result = load_procedure_metadata(stage, dataset_id, art["rel"])
            if result.get("provenanceVerification") != "matched_repository_artifact":
                raise CifpError(f"{dataset_id}: staged file does not satisfy the pinned-provenance contract")


def update_manifests(root: Path, artifacts: dict[str, dict[str, Any]], today: date) -> None:
    source_path = root / "procedures/source-manifest.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    for dataset_id, art in artifacts.items():
        source.setdefault("datasets", {})[dataset_id] = art["source"]
    atomic_write(source_path, (json.dumps(source, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))

    manifest_path = root / "navigation_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for dataset_id, art in artifacts.items():
        src = art["source"]
        entries = [d for d in manifest.get("datasets", []) if d.get("id") == dataset_id]
        if len(entries) != 1:
            raise CifpError(f"Manifest must contain exactly one '{dataset_id}' dataset, found {len(entries)}")
        entry = entries[0]
        in_cycle = date.fromisoformat(src["effectiveDate"]) <= today <= date.fromisoformat(src["expiryDate"])
        entry.update({
            "path": art["rel"], "recordCount": src["recordCount"], "sizeBytes": src["sizeBytes"],
            "sha256": src["sha256"], "sourceProvider": src["provider"], "sourceUrl": src["sourceUrl"],
            "coverage": src["coverage"], "sourceTag": src["sourceTag"], "license": src["license"],
            "licenseStatus": src["licenseStatus"], "dataCycle": src["dataCycle"],
            "effectiveDate": src["effectiveDate"], "expiryDate": src["expiryDate"],
            "provenanceVerification": "matched_repository_artifact",
            "testDownloadAvailable": True, "downloadPurpose": "development_test_only",
            "operationallyAvailable": False, "available": in_cycle,
            "status": "present_unverified_test_only" if in_cycle else "not_published_source_cycle_expired",
        })
        if in_cycle:
            entry["downloadUrl"] = DOWNLOAD_BASE + art["rel"]
        else:
            entry.pop("downloadUrl", None)
    manifest["generatedAtUtc"] = datetime.now(timezone.utc).isoformat()
    atomic_write(manifest_path, (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def publish(root: Path, effective: date, zip_path: Path, url: str, today: date) -> bool:
    cycle = airac_label(effective)
    tag = f"FAA_CIFP_{cycle}"
    rows_by_dataset, scan = decode_archive(zip_path, tag)
    idents = known_identifiers(root)
    report: dict[str, Any] = {"cycle": cycle, "effectiveDate": effective.isoformat(), "scan": scan, "datasets": {}}
    for meta in DATASETS.values():
        previous_cycle, previous = read_published(root / meta["rel"])
        report["datasets"][meta["id"]] = check_dataset(
            meta["id"], rows_by_dataset[meta["id"]], previous, previous_cycle, cycle, idents)
    write_summary(report)

    archive_sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    artifacts = build_artifacts(root, effective, rows_by_dataset, archive_sha, url,
                                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    verify_staged(artifacts)

    unchanged = all(
        (root / a["rel"]).is_file() and hashlib.sha256((root / a["rel"]).read_bytes()).hexdigest() == a["source"]["sha256"]
        for a in artifacts.values())
    if unchanged:
        log.info("Cycle %s is already published; nothing to do.", cycle)
        return False
    for art in artifacts.values():
        atomic_write(root / art["rel"], art["raw"])
        atomic_write(root / art["meta_rel"], (json.dumps(art["file_meta"], indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    update_manifests(root, artifacts, today)
    log.info("Published FAA CIFP cycle %s: %s", cycle,
             ", ".join(f"{k} {v['source']['recordCount']} rows" for k, v in artifacts.items()))
    return True


def write_summary(report: dict[str, Any]) -> None:
    text = json.dumps(report, indent=2, ensure_ascii=False)
    log.info("Import report:\n%s", text)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"### FAA CIFP {report['cycle']} procedure import\n\n```json\n{text}\n```\n")


# --------------------------------------------------------------------------- orchestration

def download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response, target.open("wb") as handle:
        shutil.copyfileobj(response, handle, length=1024 * 1024)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today", help="Override today's date (YYYY-MM-DD).")
    parser.add_argument("--cycle", help="Force a cycle effective date (YYYY-MM-DD).")
    parser.add_argument("--zip", type=Path, help="Use a local CIFP zip instead of downloading (requires --cycle).")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()

    if args.zip:
        if not args.cycle:
            parser.error("--zip requires --cycle")
        effective = date.fromisoformat(args.cycle)
        print("Updated" if publish(args.root, effective, args.zip, archive_url(effective), today) else "No change")
        return 0

    first = date.fromisoformat(args.cycle) if args.cycle else cycle_effective_on_or_before(today)
    last_error: Exception | None = None
    for effective in (first, first - timedelta(days=CYCLE_DAYS)):
        try:
            with tempfile.TemporaryDirectory(prefix="flighttempo-cifp-") as td:
                archive = Path(td) / "CIFP.zip"
                url = archive_url(effective)
                log.info("Downloading %s", url)
                download(url, archive)
                changed = publish(args.root, effective, archive, url, today)
            print("Updated" if changed else "No change")
            return 0
        except Exception as exc:
            last_error = exc
            log.warning("FAA CIFP cycle %s failed: %s", effective, exc)
            if args.cycle:
                break
    raise CifpError(f"No usable CIFP cycle: {last_error}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CifpError as exc:
        log.error("%s", exc)
        sys.exit(1)
