#!/usr/bin/env python3
"""Discover OFMA regional download endpoints; do not publish aeronautical data."""
from __future__ import annotations
import hashlib, json, re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ofma_download_discovery_report.json"
UA = "FlightTempo-OFMA-DownloadDiscovery/1.0 (+https://github.com/julienvergouts-code/flighttempo-data)"
REGIONS = {
    "EB":"Belgium","ED":"Germany","EF":"Finland","EH":"Netherlands","EK":"Denmark",
    "EP":"Poland","ES":"Sweden","FA":"South Africa","FY":"Namibia","LD":"Croatia",
    "LF":"France","LG":"Greece","LH":"Hungary","LI":"Italy","LJ":"Slovenia",
    "LK":"Czechia","LM":"Malta","LO":"Austria","LR":"Romania","LS":"Switzerland",
    "LZ":"Slovakia",
}
FORMATS = (".cup", ".openair", ".ofmx", ".xml", ".zip", ".csv", ".aixm", ".arinc")
MAX_PAGE_BYTES = 3 * 1024 * 1024

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.hrefs=[]; self.srcs=[]; self.data_attrs=[]
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if d.get("href"): self.hrefs.append(d["href"])
        if d.get("src"): self.srcs.append(d["src"])
        for key,value in attrs:
            if key.startswith("data-") and value and any(term in key.lower() for term in ("url","download","region","file","api")):
                self.data_attrs.append({"attribute":key,"value":value})

def fetch(url):
    req=Request(url,headers={"User-Agent":UA})
    with urlopen(req,timeout=45) as r:
        body=r.read(MAX_PAGE_BYTES+1)
        if len(body)>MAX_PAGE_BYTES: raise RuntimeError("Page exceeded safety limit")
        return r.status,r.url,body


def scan_script_text(source):
    patterns=re.findall(r"""["']((?:https?://|/)[^"'\s<>]{3,})["']""",source)
    candidates=sorted(set(x for x in patterns if any(t in x.lower() for t in ("download","api","snapshot","ofmx","cup","openair","region","data","zip"))))
    keywords=("download","ajax","snapshot","airac","api","region","file","ofmx","zip","cup","openair")
    snippets=[]
    for keyword in keywords:
        for match in re.finditer(keyword,source,re.IGNORECASE):
            snippets.append(source[max(0,match.start()-90):min(len(source),match.end()+140)].replace("\n"," "))
            if len(snippets)>=100: break
        if len(snippets)>=100: break
    return candidates, list(dict.fromkeys(snippets))[:100]

def inspect_script(url):
    try:
        status,final,raw=fetch(url)
        source=raw.decode("utf-8","replace")
        candidates,snippets=scan_script_text(source)
        return {"url":url,"status":status,"finalUrl":final,"bytes":len(raw),
                "sha256":hashlib.sha256(raw).hexdigest(),"candidateStrings":candidates[:200],
                "keywordSnippets":snippets}
    except Exception as e:
        return {"url":url,"error":str(e)}

def discover_region(code):
    slug={"LD":"lb"}.get(code,code.lower())
    url=f"https://openflightmaps.org/downloads/{slug}/"
    try:
        status,final,raw=fetch(url)
        html=raw.decode("utf-8","replace")
        parser=Links(); parser.feed(html)
        links=[]
        for href in parser.hrefs:
            resolved=urljoin(final,href)
            if any(ext in resolved.lower().split("?")[0] for ext in FORMATS):
                links.append(resolved)
        # Capture format hints from the visible text/source without retaining page contents.
        format_hints=sorted(set(ext[1:] for ext in FORMATS if ext in html.lower()))
        absolute_urls=sorted(set(re.findall(r"https?://[^\s<>]+",html)))
        candidate_urls=[x for x in absolute_urls if any(term in x.lower() for term in ("openflightmaps","snapshot","download","api"))]
        return {"region":code,"regionName":REGIONS[code],"pageUrl":url,"status":status,
                "finalUrl":final,"pageBytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),
                "directDownloadLinks":sorted(set(links)),"formatHints":format_hints,
                "scriptSrcs":sorted(set(urljoin(final,x) for x in parser.srcs)),
                "scriptEndpointAnalysis":[inspect_script(urljoin(final,x)) for x in parser.srcs if "download.js" in x.lower() or "ofmTileMap.js" in x.lower()],
                "dataAttributes":parser.data_attrs[:100],"candidateEmbeddedUrls":candidate_urls[:100],
                "downloadLinksFound":len(set(links))}
    except Exception as e:
        return {"region":code,"regionName":REGIONS[code],"pageUrl":url,"error":str(e)}

def main():
    report={"generatedUtc":datetime.now(timezone.utc).isoformat(),
            "purpose":"Endpoint discovery only. No OFMA data is downloaded, parsed, stored or redistributed.",
            "license":"OFMA GUL permits commercial use subject to conditions; attribution, alteration reporting and error-reporting obligations must be implemented before app integration.",
            "regions":{code:discover_region(code) for code in REGIONS}}
    OUT.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    total=sum(x.get("downloadLinksFound",0) for x in report["regions"].values())
    ok=sum("status" in x and x["status"]==200 for x in report["regions"].values())
    print(f"OFMA regions checked: {len(REGIONS)}; HTTP 200: {ok}; direct data links discovered: {total}")
    for code,x in report["regions"].items():
        print(f"{code}: {x.get('status',x.get('error'))}; direct links={x.get('downloadLinksFound',0)}; hints={','.join(x.get('formatHints',[]))}")
if __name__=="__main__": main()
