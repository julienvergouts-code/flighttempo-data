#!/usr/bin/env python3
"""Inspect OFMA regional publication metadata without importing aeronautical data."""
from __future__ import annotations
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ofma_download_discovery_report.json"
UA = "FlightTempo-OFMA-DownloadDiscovery/2.0 (+https://github.com/julienvergouts-code/flighttempo-data)"
REGIONS = {
    "EB": "Belgium", "ED": "Germany", "EF": "Finland", "EH": "Netherlands",
    "EK": "Denmark", "EP": "Poland", "ES": "Sweden", "FA": "South Africa",
    "FY": "Namibia", "LD": "Croatia", "LF": "France", "LG": "Greece",
    "LH": "Hungary", "LI": "Italy", "LJ": "Slovenia", "LK": "Czechia",
    "LM": "Malta", "LO": "Austria", "LR": "Romania", "LS": "Switzerland",
    "LZ": "Slovakia",
}
FORMATS = (".cup", ".openair", ".ofmx", ".xml", ".zip", ".csv", ".aixm", ".arinc")
MAX_BYTES = 3 * 1024 * 1024
AIRAC_ANCHOR = date(2026, 1, 22)

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs, self.srcs, self.data_attrs = [], [], []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("href"): self.hrefs.append(attrs["href"])
        if attrs.get("src"): self.srcs.append(attrs["src"])
        for key, value in attrs.items():
            if key.startswith("data-") and value and any(t in key.lower() for t in ("url", "download", "region", "file", "api")):
                self.data_attrs.append({"attribute": key, "value": value})

def current_airac(today=None):
    today = today or datetime.now(timezone.utc).date()
    n = (today - AIRAC_ANCHOR).days // 28
    if n < 0: raise ValueError("date predates AIRAC anchor")
    return f"{(2026 + n // 13) % 100:02d}{n % 13 + 1:02d}"

def fetch(url):
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=45) as response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES: raise RuntimeError("response exceeded safety limit")
        return response.status, response.url, raw

def scan_script_text(source):
    patterns = re.findall(r"""["']([^"'\s<>]{3,})["']""", source)
    candidates = sorted(set(x for x in patterns if any(t in x.lower() for t in ("download", "api", "snapshot", "ofmx", "cup", "openair", "region", "data", "zip"))))
    snippets = []
    for keyword in ("download", "ajax", "snapshot", "airac", "api", "region", "file", "ofmx", "zip", "cup", "openair"):
        for match in re.finditer(keyword, source, re.IGNORECASE):
            snippets.append(source[max(0, match.start()-90):min(len(source), match.end()+140)].replace("\n", " "))
            if len(snippets) >= 100: break
        if len(snippets) >= 100: break
    return candidates, list(dict.fromkeys(snippets))[:100]

def local_name(node):
    return node.tag.split("}")[-1].lower()

def xml_download_metadata(raw):
    root = ET.fromstring(raw)
    records = []
    def walk(node, path, budget):
        if budget[0] <= 0: return
        budget[0] -= 1
        tag = local_name(node)
        attrs = {str(k): str(v)[:500] for k, v in node.attrib.items()}
        current = path + [{"tag": tag, "attributes": attrs}]
        if tag in {"download", "variant", "product", "file"}:
            records.append({"path": current[-5:], "text": (node.text or "").strip()[:300]})
        for child in list(node): walk(child, current, budget)
    walk(root, [], [1000])
    return {
        "root": local_name(root),
        "rootAttributes": dict(root.attrib),
        "childTags": [local_name(child) for child in list(root)[:100]],
        "downloadRecords": records[:250],
        "xmlBytes": len(raw),
        "xmlSha256": hashlib.sha256(raw).hexdigest(),
    }

def discover_region(code):
    slug = {"LD": "lb"}.get(code, code.lower())
    page_url = f"https://openflightmaps.org/downloads/{slug}/"
    result = {"region": code, "regionName": REGIONS[code], "pageUrl": page_url}
    try:
        status, final_url, raw = fetch(page_url)
        html = raw.decode("utf-8", "replace")
        parser = Links()
        parser.feed(html)
        codes = sorted(set(re.findall(r"""\bregionCode\s*=\s*['"]([^'"]+)['"]""", html, re.IGNORECASE)))
        result.update({
            "pageStatus": status, "pageFinalUrl": final_url, "pageBytes": len(raw),
            "pageSha256": hashlib.sha256(raw).hexdigest(), "regionCodeCandidates": codes,
            "directDownloadLinks": sorted(set(urljoin(final_url, href) for href in parser.hrefs
                if any(ext in urljoin(final_url, href).lower().split("?")[0] for ext in FORMATS))),
        })
        if len(codes) != 1:
            result["publicationError"] = f"expected one regionCode in page, found {len(codes)}"
            return result
        cycle = current_airac()
        xml_url = f"https://snapshots.openflightmaps.org/publicationServices/{codes[0]}_{cycle}.xml"
        try:
            xml_status, xml_final, xml_raw = fetch(xml_url)
            result["publication"] = {
                "status": xml_status, "finalUrl": xml_final, "url": xml_url, "cycle": cycle,
                **xml_download_metadata(xml_raw),
            }
        except Exception as exc:
            result["publication"] = {"url": xml_url, "cycle": cycle, "error": str(exc)}
    except Exception as exc:
        result["error"] = str(exc)
    return result

def main():
    report = {
        "generatedUtc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Inspect OFMA publication metadata only; do not download, parse, or publish aeronautical data.",
        "license": "OFMA GUL permits commercial use subject to its conditions; attribution, alteration reporting and user-reporting obligations apply.",
        "regions": {code: discover_region(code) for code in REGIONS},
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    page_ok = sum(r.get("pageStatus") == 200 for r in report["regions"].values())
    pub_ok = sum(r.get("publication", {}).get("status") == 200 for r in report["regions"].values())
    print(f"OFMA catalogue regions: {len(REGIONS)}; pages HTTP 200: {page_ok}; current-cycle publication XML HTTP 200: {pub_ok}")
    for code, region in report["regions"].items():
        pub = region.get("publication", {})
        summary = {
            "region": code, "regionCode": (region.get("regionCodeCandidates") or [None])[0],
            "cycle": pub.get("cycle"), "pageStatus": region.get("pageStatus"),
            "publicationStatus": pub.get("status"),
            "publicationError": pub.get("error") or region.get("publicationError"),
            "xmlRoot": pub.get("root"), "childTags": pub.get("childTags", []),
            "downloadRecords": pub.get("downloadRecords", []),
        }
        print("OFMA_PUBLICATION " + json.dumps(summary, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()
