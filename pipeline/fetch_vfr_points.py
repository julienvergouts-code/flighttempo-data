#!/usr/bin/env python3
"""FlightTempo VFR waypoint reference pipeline (FAA NASR FIX).

FAA records are public-domain US government data. OFMA is intentionally not
enabled: a feed URL, schema and redistribution terms must be verified first.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

try:
    import requests
except ImportError:  # Keep unittest discovery usable in the repo's minimal CI.
    requests = None
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CSV_PATH = DATA_DIR / "vfr_points.csv"
META_PATH = DATA_DIR / "vfr_points_meta.json"
CSV_COLUMNS = ["icao", "code", "name", "lat", "lon", "role", "source", "updated_date"]
VALID_SOURCES = {"FAA", "OFMA"}
SOURCE_PRIORITY = {"FAA": 30, "OFMA": 20}
MAX_REJECTION_RATE = float(os.getenv("MAX_REJECTION_RATE", "0.25"))
REQUEST_TIMEOUT = (15, 120)
USER_AGENT = "FlightTempo-DataPipeline/2.2 (+https://github.com/julienvergouts-code/flighttempo-data)"
INDEX_URL = "https://www.faa.gov/air_traffic/flight_info/aeronav/Aero_Data/NASR_Subscription/"
FAA_FIX_URL = os.getenv("FAA_FIX_URL", "").strip()
FAA_FIX_DATE = os.getenv("FAA_FIX_DATE", "").strip()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("vfr-points")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_cycle_date(token: str) -> str | None:
    token = token.strip()
    for fmt in ("%d_%b_%Y", "%Y-%m-%d", "%Y%m%d", "%y%m%d"):
        try:
            return datetime.strptime(token, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def cycle_date_from_url(url: str) -> str | None:
    match = re.search(r"(\d{2}_[A-Za-z]{3}_\d{4}|\d{4}-\d{2}-\d{2}|\d{8}|\d{6})", url)
    return parse_cycle_date(match.group(1)) if match else None


def extract_fix_links(html: str, page_url: str) -> list[tuple[str, str | None]]:
    links = re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I)
    found: dict[str, str | None] = {}
    for href in links:
        url = urljoin(page_url, href)
        if "FIX_CSV.ZIP" in url.upper():
            found[url] = cycle_date_from_url(url)
    return list(found.items())


def extract_cycle_pages(html: str, page_url: str) -> list[tuple[str, str | None]]:
    links = re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I)
    found: dict[str, str | None] = {}
    for href in links:
        url = urljoin(page_url, href)
        date = cycle_date_from_url(url)
        if url != page_url and date and not url.lower().endswith((".zip", ".pdf")):
            found[url] = date
    return list(found.items())


class UrllibResponse:
    def __init__(self, response):
        self.response = response
        self.status_code = getattr(response, "status", 200)
        self._body: bytes | None = None
    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
    @property
    def text(self) -> str:
        if self._body is None:
            self._body = self.response.read()
        return self._body.decode("utf-8", errors="replace")
    def iter_content(self, chunk_size: int = 65536):
        while chunk := self.response.read(chunk_size):
            yield chunk
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.response.close()
        return False


def get(url: str, *, stream: bool = False):
    headers = {"User-Agent": USER_AGENT}
    if requests is not None:
        return requests.get(url, stream=stream, timeout=REQUEST_TIMEOUT, headers=headers)
    request = Request(url, headers=headers)
    return UrllibResponse(urlopen(request, timeout=REQUEST_TIMEOUT[1]))


def discover_faa_archives() -> list[tuple[str, str]]:
    if FAA_FIX_URL:
        date = parse_cycle_date(FAA_FIX_DATE) if FAA_FIX_DATE else cycle_date_from_url(FAA_FIX_URL)
        if not date:
            raise RuntimeError("FAA_FIX_URL requires a recognizable cycle date or FAA_FIX_DATE=YYYY-MM-DD")
        return [(FAA_FIX_URL, date)]

    response = get(INDEX_URL)
    response.raise_for_status()
    candidates = {url: date for url, date in extract_fix_links(response.text, INDEX_URL) if date}
    pages = sorted(extract_cycle_pages(response.text, INDEX_URL), key=lambda item: item[1] or "", reverse=True)
    for page_url, page_date in pages[:8]:
        try:
            page = get(page_url)
            page.raise_for_status()
            for url, date in extract_fix_links(page.text, page_url):
                resolved = date or page_date
                if resolved:
                    candidates[url] = resolved
        except Exception as exc:
            log.warning("Cycle subpage unavailable %s: %s", page_url, exc)
    if not candidates:
        raise RuntimeError("FAA NASR page contained no dated FIX_CSV.ZIP links")
    return sorted(candidates.items(), key=lambda pair: pair[1], reverse=True)


def download_to(url: str, path: Path) -> None:
    with get(url, stream=True) as response:
        response.raise_for_status()
        with path.open("wb") as out:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    out.write(chunk)


def iter_fix_base_lines(zip_path: Path) -> Iterable[str]:
    """Stream FIX_BASE.csv; nested archives are spooled to disk, not RAM."""
    with zipfile.ZipFile(zip_path) as outer:
        csv_members = [n for n in outer.namelist() if n.lower().endswith(".csv") and "fix_base" in n.lower()]
        for name in csv_members:
            with outer.open(name) as member:
                yield from io.TextIOWrapper(member, encoding="utf-8-sig", errors="replace")
            return
        nested = [n for n in outer.namelist() if n.lower().endswith(".zip")]
        if nested:
            with tempfile.TemporaryDirectory(prefix="faa-nested-") as td:
                nested_path = Path(td) / "inner.zip"
                with outer.open(nested[0]) as member, nested_path.open("wb") as out:
                    shutil.copyfileobj(member, out, length=1024 * 1024)
                with zipfile.ZipFile(nested_path) as inner:
                    for name in inner.namelist():
                        if name.lower().endswith(".csv") and "fix_base" in name.lower():
                            with inner.open(name) as member:
                                yield from io.TextIOWrapper(member, encoding="utf-8-sig", errors="replace")
                            return
    raise RuntimeError("FIX_BASE.csv not found in FAA archive")


def parse_faa_records(lines: Iterable[str], effective_date: str) -> list[dict[str, Any]]:
    records = []
    for row in csv.DictReader(lines):
        ident = clean(row.get("FIX_ID")).upper()
        if re.fullmatch(r"VP[A-Z0-9]{3}", ident):
            records.append({
                "icao": "", "code": ident, "name": ident,
                "lat": row.get("LAT_DECIMAL"), "lon": row.get("LONG_DECIMAL"),
                "role": "VFR_WAYPOINT", "source": "FAA", "updated_date": effective_date,
            })
    return records


def fetch_faa() -> list[dict[str, Any]]:
    candidates = discover_faa_archives()
    last_error: Exception | None = None
    with tempfile.TemporaryDirectory(prefix="flighttempo-faa-") as td:
        archive = Path(td) / "fix.zip"
        for url, date in candidates:
            try:
                log.info("Downloading FAA archive %s (effective %s)", url, date)
                download_to(url, archive)
                records = parse_faa_records(iter_fix_base_lines(archive), date)
                if not records:
                    raise RuntimeError("Archive parsed successfully but contained zero VP fixes")
                return records
            except Exception as exc:
                last_error = exc
                log.warning("FAA archive failed %s: %s", url, exc)
                archive.unlink(missing_ok=True)
    raise RuntimeError(f"All FAA archive candidates failed: {last_error}")


def validate_record(record: dict[str, Any]) -> dict[str, Any]:
    icao = clean(record.get("icao")).upper()
    if icao and not re.fullmatch(r"[A-Z]{4}", icao):
        raise ValueError("Invalid ICAO identifier")
    code = clean(record.get("code")).upper()
    if not code:
        raise ValueError("Missing point identifier")
    lat, lon = float(record["lat"]), float(record["lon"])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Coordinates out of range")
    if lat == 0 and lon == 0:
        raise ValueError("Null Island coordinate")
    date = clean(record.get("updated_date"))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("Date must be ISO YYYY-MM-DD")
    datetime.strptime(date, "%Y-%m-%d")
    source = clean(record.get("source")).upper()
    if source not in VALID_SOURCES:
        raise ValueError(f"Unsupported source {source}")
    role = clean(record.get("role")).upper()
    if source == "FAA" and not re.fullmatch(r"VP[A-Z0-9]{3}", code):
        raise ValueError("Invalid FAA VFR waypoint identifier")
    if source == "FAA" and role != "VFR_WAYPOINT":
        raise ValueError("FAA VFR records must use the VFR_WAYPOINT role")
    if role not in {"ENTRY", "EXIT", "BOTH", "VRP", "VFR_WAYPOINT"}:
        role = "VRP"
    return {"icao": icao, "code": code, "name": clean(record.get("name")) or code,
            "lat": round(lat, 5), "lon": round(lon, 5), "role": role,
            "source": source, "updated_date": date}


def validate_records(records: Iterable[dict[str, Any]], *, guard: bool = False) -> tuple[list[dict[str, Any]], int]:
    good, rejected = [], 0
    for item in records:
        try:
            good.append(validate_record(item))
        except (ValueError, TypeError, KeyError) as exc:
            rejected += 1
            log.warning("Rejecting row: %s", exc)
    total = len(good) + rejected
    if guard and total and rejected / total > MAX_REJECTION_RATE:
        raise RuntimeError(f"Rejection rate {rejected / total:.1%} exceeds {MAX_REJECTION_RATE:.1%}")
    return good, rejected


def read_existing(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or CSV_PATH
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        first = f.readline()
        if first and not first.startswith("#version="):
            f.seek(0)
        rows = list(csv.DictReader(f))
    valid, rejected = validate_records(rows)
    if rejected:
        log.warning("Existing CSV had %d invalid row(s)", rejected)
    return valid


def dedupe_sort(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in records:
        key = (row["icao"], row["code"])
        current = by_key.get(key)
        if current is None or SOURCE_PRIORITY[row["source"]] > SOURCE_PRIORITY[current["source"]]:
            by_key[key] = row
        elif SOURCE_PRIORITY[row["source"]] == SOURCE_PRIORITY[current["source"]]:
            if tuple(row[k] for k in CSV_COLUMNS) < tuple(current[k] for k in CSV_COLUMNS):
                by_key[key] = row
    return sorted(by_key.values(), key=lambda r: (r["icao"], r["code"], r["name"], r["source"]))


def source_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if r["source"] == "FAA"]


def write_csv(path: Path, records: list[dict[str, Any]], generated: str) -> None:
    buf = io.StringIO(newline="")
    buf.write(f"#version=1,generated_utc={generated}\n")
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    writer.writerows(records)
    atomic_text(path, buf.getvalue())


def write_meta(path: Path, records: list[dict[str, Any]], generated: str, status: str) -> None:
    meta = {
        "version": 1, "generated_utc": generated, "total_rows": len(records),
        "rows_by_source": {src: sum(r["source"] == src for r in records) for src in sorted(VALID_SOURCES)},
        "source_status": {"FAA": status, "OFMA": "disabled"},
        "sources": {"FAA": {"license": "US Government public-domain data",
          "attribution": "Federal Aviation Administration, Aeronautical Information Services, NASR FIX data."},
          "OFMA": {"status": "disabled", "reason": "Source/schema/redistribution terms not verified"}},
    }
    atomic_text(path, json.dumps(meta, indent=2) + "\n")


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_meta_status(path: Path | None = None) -> str | None:
    path = path or META_PATH
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("source_status", {}).get("FAA")
    except (OSError, ValueError, AttributeError):
        return None


def publish_pair(csv_path: Path, meta_path: Path, records: list[dict[str, Any]], generated: str, status: str) -> None:
    """Stage both outputs; restore originals if either replacement fails."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vfr-stage-", dir=csv_path.parent) as td:
        staged_csv, staged_meta = Path(td) / "data.csv", Path(td) / "meta.json"
        write_csv(staged_csv, records, generated)
        write_meta(staged_meta, records, generated, status)
        backups: dict[Path, Path | None] = {}
        for target in (csv_path, meta_path):
            backup = Path(td) / (target.name + ".bak")
            if target.exists():
                shutil.copy2(target, backup)
                backups[target] = backup
            else:
                backups[target] = None
        try:
            os.replace(staged_csv, csv_path)
            os.replace(staged_meta, meta_path)
        except Exception:
            for target, backup in backups.items():
                if backup is None:
                    target.unlink(missing_ok=True)
                elif backup.exists():
                    os.replace(backup, target)
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-drop", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args(argv)
    previous = read_existing()
    try:
        fetched, status = fetch_faa(), "ok"
        validated, rejected = validate_records(fetched, guard=True)
        if not validated:
            raise RuntimeError("FAA produced zero valid VFR waypoints")
        retained_disabled = [row for row in previous if row["source"] == "OFMA"]
        new_rows = dedupe_sort(validated + retained_disabled)
    except Exception as exc:
        log.error("FAA source failed; retaining previous FAA rows: %s", exc)
        new_rows, status = previous, "failed"
        if not args.allow_partial:
            log.error("Use --allow-partial to publish retained data with failure metadata")
            return 1
    if not new_rows:
        log.error("Refusing to publish an empty VFR waypoint dataset")
        return 1
    if previous:
        drop = (len(previous) - len(new_rows)) / len(previous)
        if drop > 0.30 and not args.allow_drop:
            log.error("Dataset drop %.1f%% (%d -> %d); refusing. Use --allow-drop.", drop * 100, len(previous), len(new_rows))
            return 1
    if not args.dry_run and dedupe_sort(previous) == new_rows and read_meta_status() == status:
        log.info("Dataset unchanged; leaving committed files untouched.")
        return 0
    generated = timestamp()
    if args.dry_run:
        out = io.StringIO(newline="")
        out.write(f"#version=1,generated_utc={generated}\n")
        writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(new_rows[:12])
        print(out.getvalue())
        print(json.dumps({"total_rows": len(new_rows), "source_status": status, "rejected": rejected if status == "ok" else None}, indent=2))
        return 0
    publish_pair(CSV_PATH, META_PATH, new_rows, generated, status)
    log.info("Published %d FAA VFR waypoints (%s)", len(new_rows), status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
