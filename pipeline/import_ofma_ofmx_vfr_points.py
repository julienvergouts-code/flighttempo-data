#!/usr/bin/env python3
"""Import current OFMA OFMX VFR-designated points as reference data only."""
from __future__ import annotations
import argparse, csv, hashlib, io, json, os, re, tempfile, urllib.parse, urllib.request, zipfile
from datetime import date, datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/"data/ofma_ofmx_sources.json"
OUT=ROOT/"data/ofma_ofmx_vfr_points.csv"
META=ROOT/"data/ofma_ofmx_vfr_points_meta.json"
ARCHIVES=ROOT/"data/ofma_source_archives"
COLUMNS=["region","feature_region","point_id","code","name","lat","lon","kind","source_regions","source","license","cycle"]
VFR_TYPES={"VFR-RP","VFR-MRP","VFR-ENR","VFR-GLDR","VFR-HELI"}
AIRAC_ANCHOR=date(2026,1,22)
MAX_BYTES=80*1024*1024
MAX_PUBLICATION_BYTES=4*1024*1024
MAX_XML_BYTES=80*1024*1024
UA="FlightTempo-OFMA-OFMX-VFR-Importer/2.0 (+https://github.com/julienvergouts-code/flighttempo-data)"

def stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def current_airac(today=None):
    today=today or datetime.now(timezone.utc).date()
    n=(today-AIRAC_ANCHOR).days//28
    if n<0: raise ValueError("date predates AIRAC anchor")
    return f"{(2026+n//13)%100:02d}{n%13+1:02d}"

def clean(value):
    return re.sub(r"\s+"," ",str(value or "")).strip()

def local_name(node):
    return node.tag.split("}")[-1].lower()

def parse_coord(value):
    value=clean(value).upper()
    hemisphere=value[-1] if value and value[-1] in "NSEW" else ""
    if not hemisphere: raise ValueError(f"bad OFMX coordinate {value!r}")
    body=value[:-1]
    limit=90 if hemisphere in "NS" else 180
    if re.fullmatch(r"\d{1,3}\.\d+",body):
        number=float(body)
        if number>limit: raise ValueError(f"coordinate degrees out of range: {value}")
    else:
        degree_digits=2 if hemisphere in "NS" else 3
        match=re.fullmatch(r"(\d{"+str(degree_digits)+r"})(\d{2})(?:(\d{2}(?:\.\d+)?))?",body)
        if not match: raise ValueError(f"bad OFMX coordinate {value!r}")
        degrees=int(match.group(1));minutes=int(match.group(2));seconds=float(match.group(3) or 0)
        if minutes>=60 or seconds>=60: raise ValueError(f"coordinate minute/second out of range: {value}")
        if degrees>limit or (degrees==limit and (minutes or seconds)): raise ValueError(f"coordinate degrees out of range: {value}")
        number=degrees+minutes/60+seconds/3600
    return -number if hemisphere in "SW" else number

def text(node,name):
    for child in list(node):
        if local_name(child)==name.lower(): return clean(child.text)
    return ""

def publication_service_url(region_code,airac):
    if not re.fullmatch(r"[A-Z0-9]{2,4}",region_code): raise ValueError(f"invalid OFMA regionCode {region_code!r}")
    if not re.fullmatch(r"\d{4}",airac): raise ValueError(f"invalid AIRAC cycle {airac!r}")
    return f"https://snapshots.openflightmaps.org/publicationServices/{region_code}_{airac}.xml"

def select_ofmx_url(publication_xml,airac):
    root=ET.fromstring(publication_xml)
    urls=set()
    for product in root.iter():
        if local_name(product)!="product" or clean(product.attrib.get("type")).upper()!="OFMX":
            continue
        for node in product.iter():
            if local_name(node) not in {"download","variant"}: continue
            candidate=next((value for key,value in node.attrib.items() if key.lower()=="url"),"")
            if not candidate: continue
            parsed=urllib.parse.urlparse(candidate)
            filename=Path(parsed.path).name.lower()
            if (parsed.scheme=="https" and parsed.hostname=="snapshots.openflightmaps.org"
                and f"/live/{airac}/ofmx/" in parsed.path.lower()
                and filename.startswith("ofmx_") and filename.endswith(".zip")):
                urls.add(candidate)
    if len(urls)!=1:
        raise ValueError(f"expected one official OFMX ZIP for cycle {airac}; found {len(urls)}")
    return next(iter(urls))

def fetch(url,max_bytes=MAX_BYTES):
    request=urllib.request.Request(url,headers={"User-Agent":UA})
    with urllib.request.urlopen(request,timeout=60) as response:
        final_url=response.geturl()
        if response.status!=200: raise ValueError(f"HTTP {response.status}: {url}")
        raw=response.read(max_bytes+1)
    if len(raw)>max_bytes: raise ValueError(f"download exceeds {max_bytes} byte safety cap")
    if urllib.parse.urlparse(final_url).hostname!=urllib.parse.urlparse(url).hostname:
        raise ValueError(f"unexpected redirect host: {final_url}")
    return raw,final_url

def validate_source(source):
    for key in ("region","regionName","regionCode","regionKey","archiveKey","sourcePage","license"):
        if not clean(source.get(key)): raise ValueError(f"source missing {key}")
    if source["license"]!="OFMA_GUL": raise ValueError("OFMA GUL required")
    if not re.fullmatch(r"[A-Z]{2}",source["region"]): raise ValueError("region must be a two-letter OFMA catalogue code")
    if not source["sourcePage"].startswith("https://openflightmaps.org/downloads/"):
        raise ValueError("source page must be an official OpenFlightMaps regional download page")

def discover_page_region_code(source):
    raw,final_url=fetch(source["sourcePage"],MAX_PUBLICATION_BYTES)
    if urllib.parse.urlparse(final_url).hostname not in {"openflightmaps.org","www.openflightmaps.org"}:
        raise ValueError(f"unexpected regional-page host: {final_url}")
    html=raw.decode("utf-8","replace")
    candidates=sorted(set(re.findall(r"""\bregionCode\s*=\s*['"]([^'"]+)['"]""",html,re.IGNORECASE)))
    if candidates!=[source["regionCode"]]:
        raise ValueError(f"official page regionCode mismatch for {source['region']}: {candidates}")
    return hashlib.sha256(raw).hexdigest()

def resolve_ofmx_source(source,airac):
    page_sha=discover_page_region_code(source)
    service_url=publication_service_url(source["regionCode"],airac)
    publication,final_url=fetch(service_url,MAX_PUBLICATION_BYTES)
    package_url=select_ofmx_url(publication,airac)
    return package_url,service_url,hashlib.sha256(publication).hexdigest(),page_sha

def parse_xml(raw,source):
    if len(raw)>MAX_XML_BYTES: raise ValueError("OFMX XML exceeds size cap")
    root=ET.fromstring(raw)
    dpn_count=0
    records=[]
    for dpn in root.iter():
        if local_name(dpn)!="dpn": continue
        dpn_count+=1
        uid=next((node for node in list(dpn) if local_name(node)=="dpnuid"),None)
        if uid is None: continue
        kind=text(dpn,"codeType").upper()
        if kind not in VFR_TYPES: continue
        code=text(uid,"codeId")
        name=text(dpn,"txtName") or code
        lat_s=text(uid,"geoLat") or text(dpn,"geoLat")
        lon_s=text(uid,"geoLong") or text(dpn,"geoLon") or text(dpn,"geoLong")
        if not lat_s or not lon_s: raise ValueError(f"VFR Dpn has no coordinates: {code or name}")
        lat=parse_coord(lat_s);lon=parse_coord(lon_s)
        if not -90<=lat<=90 or not -180<=lon<=180 or (lat==0 and lon==0):
            raise ValueError(f"invalid point coordinates: {code or name}")
        if not code and not name: continue
        feature_region=clean(uid.attrib.get("region") or dpn.attrib.get("region")).upper()
        identity="|".join((feature_region or source["region"],code or name,kind,f"{lat:.8f}",f"{lon:.8f}"))
        point_id=hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        records.append({
            "region":source["region"],"feature_region":feature_region,"point_id":point_id,
            "code":code or name[:32],"name":name or code,"lat":round(lat,8),"lon":round(lon,8),
            "kind":kind,"source_regions":source["region"],"source":"OFMA","license":"OFMA_GUL",
            "cycle":source.get("cycle") or stamp()[:10],
        })
    if dpn_count==0: raise ValueError(f"no Dpn elements parsed for {source['region']}; schema/endpoint may have changed")
    return records

def xml_from_zip(raw,source):
    if len(raw)>MAX_BYTES: raise ValueError("OFMX ZIP exceeds size cap")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names=[name for name in archive.namelist() if "/embedded/" in name.lower()]
        keys={f"ofmx_{source['regionKey'].lower()}",f"ofmx_{source['archiveKey'].lower()}"}
        selected=[name for name in names if Path(name).name.lower() in keys]
        if len(selected)!=1: raise ValueError(f"expected one OFMX embedded member for {source['region']}; found {len(selected)}")
        if archive.getinfo(selected[0]).file_size>MAX_XML_BYTES: raise ValueError("OFMX embedded XML exceeds size cap")
        return archive.read(selected[0])

def atomic_pair(csv_path,meta_path,csvdata,metadata):
    csv_path.parent.mkdir(parents=True,exist_ok=True);meta_path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=csv_path.parent) as temp_dir:
        csv_temp=Path(temp_dir)/"points.csv";meta_temp=Path(temp_dir)/"meta.json"
        csv_temp.write_bytes(csvdata)
        meta_temp.write_text(json.dumps(metadata,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        old_csv=csv_path.read_bytes() if csv_path.exists() else None
        old_meta=meta_path.read_bytes() if meta_path.exists() else None
        try:
            os.replace(csv_temp,csv_path);os.replace(meta_temp,meta_path)
        except Exception:
            if old_csv is None: csv_path.unlink(missing_ok=True)
            else: csv_path.write_bytes(old_csv)
            if old_meta is None: meta_path.unlink(missing_ok=True)
            else: meta_path.write_bytes(old_meta)
            raise

def run(config=CONFIG,dry=False):
    cfg=json.loads(Path(config).read_text(encoding="utf-8"))
    airac=current_airac() if cfg.get("airac")=="auto" else str(cfg.get("airac"))
    sources=cfg.get("regions",[])
    if not sources: print("No OFMA regions configured; existing data retained.");return 0
    for source in sources: validate_source(source)
    if len({source["region"] for source in sources})!=len(sources): raise ValueError("duplicate OFMA source region")
    ARCHIVES.mkdir(parents=True,exist_ok=True)
    all_rows=[];source_meta=[]
    with tempfile.TemporaryDirectory(prefix=".ofma-vfr-stage-",dir=ARCHIVES) as stage:
        stage_dir=Path(stage)
        for source in sources:
            package_url,service_url,service_sha,page_sha=resolve_ofmx_source(source,airac)
            raw,_=fetch(package_url)
            (stage_dir/(source["region"].lower()+".zip")).write_bytes(raw)
            xml=xml_from_zip(raw,source)
            source["cycle"]=airac
            records=parse_xml(xml,source)
            all_rows.extend(records)
            source_meta.append({
                "region":source["region"],"regionName":source["regionName"],"regionCode":source["regionCode"],
                "sourcePage":source["sourcePage"],"sourcePageSha256":page_sha,
                "publicationServiceUrl":service_url,"publicationServiceSha256":service_sha,
                "downloadUrl":package_url,"cycle":airac,"effectiveDate":None,
                "license":"OFMA General Users License","attribution":source.get("attribution","OpenFlightMaps Association (OFMA)"),
                "sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"parsedVfrPoints":len(records),
                "status":"published_with_vfr_points" if records else "published_no_vfr_dpn",
            })
        if not all_rows: raise ValueError("all official OFMA packages parsed zero VFR points; preserving prior dataset")
        merged={}
        for row in all_rows:
            key=(row["feature_region"] or row["region"],row["code"],row["lat"],row["lon"],row["kind"])
            if key not in merged: merged[key]=row
            else: merged[key]["source_regions"]+=";"+row["region"]
        rows=sorted(merged.values(),key=lambda row:(row["feature_region"],row["kind"],row["code"],row["lat"],row["lon"]))
        for row in rows: row["source_regions"]=";".join(sorted(set(row["source_regions"].split(";"))))
        by_type={};by_feature_region={}
        for row in rows:
            by_type[row["kind"]]=by_type.get(row["kind"],0)+1
            feature_region=row["feature_region"] or "UNKNOWN"
            by_feature_region[feature_region]=by_feature_region.get(feature_region,0)+1
        reused={}
        for row in rows:
            key=(row["feature_region"] or row["region"],row["code"])
            reused[key]=reused.get(key,0)+1
        reused_codes=sum(count>1 for count in reused.values())
        buffer=io.StringIO();buffer.write("#version=2,generated_utc="+stamp()+"\n")
        writer=csv.DictWriter(buffer,fieldnames=COLUMNS);writer.writeheader();writer.writerows(rows)
        csv_data=buffer.getvalue().encode("utf-8")
        metadata={
            "schemaVersion":2,"generatedUtc":stamp(),"airac":airac,"count":len(rows),
            "regions":[source["region"] for source in sources],
            "sourceRegionsWithVfrPoints":[item["region"] for item in source_meta if item["parsedVfrPoints"]],
            "sourceRegionsWithoutVfrPoints":[item["region"] for item in source_meta if not item["parsedVfrPoints"]],
            "featureRegions":by_feature_region,"countsByType":by_type,"reusedCodeGroups":reused_codes,
            "sources":source_meta,
            "coverage":"All current OFMA catalogue regions with an official OFMX publication; OFMA is regional and does not provide worldwide geographic coverage.",
            "sourcePolicy":"Official OFMA publication-services XML and OFMA OFMX snapshots only; this pipeline fetches no AIP websites or files.",
            "license":"OFMA General Users License","licenseUrl":"https://www.openflightmaps.org/live/downloads/20150306-GUL.pdf",
            "commercialUseAllowed":True,
            "licenseNotes":"Commercial use is explicitly permitted by OFMA GUL subject to its conditions. Preserve attribution; communicate alterations within 15 days; if users can alter OFMA data, provide the direct contributor interface required by GUL section 4.4.",
            "attribution":"Contains information from the open flightmaps database, see www.openflightmaps.org",
            "ifrReusePolicy":{
                "rule":"Only the same normalized name and exactly equal latitude/longitude may be shared with a separately licensed IFR point; no ident-only, fuzzy, or near-coordinate match.",
                "implementation":"scripts/exact_point_matching.py",
                "currentGlobalIFRSourceStatus":"No current commercially reusable worldwide IFR fix layer is active in this repository; the stale 2012.08 global baseline remains excluded from app downloads."
            },
            "sha256":hashlib.sha256(csv_data).hexdigest(),"sizeBytes":len(csv_data),
            "operationalUse":False,"stablePointIds":True,
        }
        if dry:
            print(json.dumps({"count":len(rows),"regions":metadata["regions"],"featureRegions":by_feature_region,
                "countsByType":by_type,"sources":[{"region":item["region"],"parsedVfrPoints":item["parsedVfrPoints"],"status":item["status"],"downloadUrl":item["downloadUrl"]} for item in source_meta]},indent=2))
            return 0
        atomic_pair(OUT,META,csv_data,metadata)
        for old in ARCHIVES.glob("*.zip"): old.unlink()
        for staged in stage_dir.glob("*.zip"): os.replace(staged,ARCHIVES/staged.name)
    print(f"Imported {len(rows)} deduplicated OFMA VFR points from {len(sources)} official regions; {len(by_feature_region)} feature regions; cycle {airac}")
    return 0

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",type=Path,default=CONFIG)
    parser.add_argument("--dry-run",action="store_true")
    args=parser.parse_args()
    return run(args.config,args.dry_run)

if __name__=="__main__": raise SystemExit(main())
