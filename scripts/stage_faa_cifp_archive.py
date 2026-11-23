#!/usr/bin/env python3
"""Stage newly published FAA CIFP archives without importing or replacing datasets."""
from __future__ import annotations
import hashlib, json, os, urllib.request, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "procedures/faa-cifp-currentness.json"
OUT = Path(os.environ.get("FAA_CIFP_OUT", "/tmp/faa-cifp-update"))
USER_AGENT = "FlightTempo-Data-Maintenance/1.0"

def download_candidate(status: dict, out_dir: Path = OUT) -> dict | None:
    latest = status.get("latestPublishedCycle")
    packaged = status.get("packagedCycle", {})
    if not latest or not latest.get("downloadUrl"):
        raise ValueError("Currentness status has no latest published CIFP download URL")
    token = str(latest.get("cycleToken", ""))
    if not token or token == str(packaged.get("cycleToken", "")):
        print("No new published FAA CIFP cycle; nothing to stage.")
        return None
    url = latest["downloadUrl"]
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"CIFP_{token}.zip"
    with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as dest:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk: break
            dest.write(chunk)
    if not zipfile.is_zipfile(archive):
        archive.unlink(missing_ok=True)
        raise ValueError("FAA download is not a valid ZIP archive")
    with zipfile.ZipFile(archive) as zf:
        bad = zf.testzip()
        if bad:
            archive.unlink(missing_ok=True)
            raise ValueError(f"ZIP integrity failed at member: {bad}")
    metadata = {
        "source": "FAA AeroNav CIFP", "sourceUrl": url, "cycleToken": token,
        "effectiveDate": latest.get("effectiveDate"), "expiryDate": latest.get("expiryDate"),
        "downloadedArchive": archive.name, "sizeBytes": archive.stat().st_size,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "zipIntegrity": "passed", "automaticImport": False,
        "replacementOfCurrentDataset": False, "purpose": "staging-only; manual parser validation required"
    }
    (out_dir / "download-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    return metadata

def main():
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    download_candidate(status)

if __name__ == "__main__": main()
