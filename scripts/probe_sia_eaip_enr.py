#!/usr/bin/env python3
"""Developer probe: print the real structure of the current SIA eAIP pages (used to write the parsers)."""
from __future__ import annotations

import os
import re
import sys
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_sia_eaip_procedure_data as f  # noqa: E402


def get(url: str, limit: int = 30_000_000) -> str | None:
    try:
        req = Request(url, headers={"User-Agent": f.USER_AGENT})
        with urlopen(req, timeout=60) as r:
            return r.read(limit).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        print(f"  GET failed {url}: {exc}")
        return None


def squash(t: str, n: int) -> str:
    return re.sub(r"\s+", " ", t[:n])


def main() -> int:
    cat = get(f.CATALOG_URL) or ""
    ex = f.TextExtractor()
    ex.feed(cat)
    issue = f.select_current_issue(f.parse_catalog_issues(ex.text), date.today())
    print("issue", issue)
    base = f.issue_base_url(issue)
    print("base", base)
    for rel in ("html/index-fr-FR.html", "html/index-en-GB.html", "html/eAIP/FR-menu-fr-FR.html", "html/eAIP/FR-menu-en-GB.html"):
        t = get(f"{base}/{rel}")
        if t is None:
            continue
        print(f"== {rel} {len(t)} bytes")
        print(squash(t, 1200))
        links = sorted(set(re.findall(r'href="([^"#]*(?:ENR|GEN)[^"#]*)"', t)))
        print("ENR/GEN links:", len(links), links[:80])
    extra = os.environ.get("EXTRA_PAGES", "").split()
    for page in extra:
        t = get(f"{base}/html/eAIP/{page}")
        if t is None:
            continue
        print(f"== PAGE {page} {len(t)} bytes; tables={t.count('<table')}; rows={t.count('<tr')}")
        start = t.find("<table")
        print(squash(t[start:start + 6000] if start >= 0 else t, 6000))
    return 0


if __name__ == "__main__":
    sys.exit(main())
