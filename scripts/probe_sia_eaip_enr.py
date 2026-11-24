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
        links = sorted(set(m.split("#")[0] for m in re.findall(r"""href=["']([^"']*(?:ENR|GEN)[^"']*)["']""", t)))
        print("ENR/GEN files:", len(links), links[:120])
        i = t.find("ENR")
        print("first ENR context:", squash(t[max(0, i - 400):i + 600], 1000))
    extra = os.environ.get("EXTRA_PAGES", "").split()
    for page in extra:
        t = get(f"{base}/html/eAIP/{page}")
        if t is None:
            continue
        print(f"== PAGE {page} {len(t)} bytes; tables={t.count('<table')}; rows={t.count('<tr')}")
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", t, flags=re.S)
        texts = []
        for r in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S)
            cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in cells]
            texts.append(" | ".join(c for c in cells if c))
        coord = [x for x in texts if re.search(r"\d{2,3}[°\s]?\d{2}['\s]?\d{0,2}[.,]?\d*\"?\s?[NSEW]\b", x)]
        print(f"  text rows {len(texts)}, rows with coordinates {len(coord)}")
        if len(t) < 40000:
            print("  FULLRAW:", squash(re.sub(r"<[^>]+>", " ", t), 3000))
        if os.environ.get("ROWS_FROM"):
            a = int(os.environ["ROWS_FROM"])
            for k, x in enumerate(texts[a:a + 45]):
                print(f"  R{a + k}:", x[:260])
        for x in texts[3:9]:
            print("  ROW:", x[:300])
        for x in coord[:10]:
            print("  COORD ROW:", x[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())
