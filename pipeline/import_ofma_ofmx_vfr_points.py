#!/usr/bin/env python3
"""Import OFMA OFMX designated points classified as VFR; reference-only."""
from __future__ import annotations
import argparse,csv,hashlib,io,json,os,re,tempfile,urllib.request,zipfile
from datetime import datetime,timezone,date
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/"data/ofma_ofmx_sources.json"
OUT=ROOT/"data/ofma_ofmx_vfr_points.csv"
META=ROOT/"data/ofma_ofmx_vfr_points_meta.json"
COLUMNS=["region","code","name","lat","lon","kind","source","license","cycle"]
VFR_TYPES={"VFR-RP","VFR-MRP","VFR-ENR","VFR-GLDR","VFR-HELI"}
MAX_BYTES=80*1024*1024
UA="FlightTempo-OFMA-OFMX-VFR-Importer/1.0 (+https://github.com/julienvergouts-code/flighttempo-data)"
def stamp():return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def current_airac(today=None):
 today=today or datetime.now(timezone.utc).date()
 anchor=date(2026,1,22) # AIRAC 2601 start; 28-day cycles
 n=(today-anchor).days//28
 if n<0:raise ValueError("date predates AIRAC anchor")
 year=2026+n//13;cycle=n%13+1
 return f"{year%100:02d}{cycle:02d}"
def clean(x):return re.sub(r"\s+"," ",str(x or "")).strip()
def parse_coord(s):
 s=clean(s).upper()
 hem=s[-1] if s and s[-1] in "NSEW" else ""
 if not hem:raise ValueError(f"bad OFMX coordinate {s!r}")
 body=s[:-1]
 limit=90 if hem in "NS" else 180
 # OFMX commonly uses decimal degrees with hemisphere (e.g. 48.98444444N).
 if re.fullmatch(r"\d{1,3}\.\d+",body):
  v=float(body)
  if v>limit:raise ValueError(f"coordinate degrees out of range: {s}")
 else:
  m=re.fullmatch(r"(\d{2,3})(\d{2})(?:(\d{2}(?:\.\d+)?))?",body)
  if not m:raise ValueError(f"bad OFMX coordinate {s!r}")
  deg=int(m.group(1));mins=int(m.group(2));secs=float(m.group(3) or 0)
  if mins>=60 or secs>=60:raise ValueError(f"coordinate minute/second out of range: {s}")
  if deg>limit or (deg==limit and (mins or secs)):raise ValueError(f"coordinate degrees out of range: {s}")
  v=deg+mins/60+secs/3600
 return -v if hem in "SW" else v
def text(node,name):
 for child in list(node):
  if child.tag.split("}")[-1]==name:return clean(child.text)
 return ""
def parse_xml(raw,src):
 if len(raw)>MAX_BYTES:raise ValueError("OFMX XML exceeds size cap")
 root=ET.fromstring(raw)
 records=[]
 for dpn in root.iter():
  if dpn.tag.split("}")[-1]!="Dpn":continue
  uid=next((x for x in list(dpn) if x.tag.split("}")[-1]=="DpnUid"),None)
  if uid is None:continue
  typ=text(dpn,"codeType").upper()
  if typ not in VFR_TYPES:continue
  code=text(uid,"codeId");name=text(dpn,"txtName") or code
  lat_s=text(uid,"geoLat") or text(dpn,"geoLat")
  lon_s=text(uid,"geoLong") or text(dpn,"geoLon") or text(dpn,"geoLong")
  if not lat_s or not lon_s:continue
  lat=parse_coord(lat_s);lon=parse_coord(lon_s)
  if not -90<=lat<=90 or not -180<=lon<=180 or (lat==0 and lon==0):raise ValueError(f"invalid point coordinates: {code or name}")
  if not code and not name:continue
  records.append({"region":src["region"],"code":code or name[:32],"name":name or code,"lat":round(lat,6),"lon":round(lon,6),"kind":typ,"source":"OFMA","license":"OFMA_GUL","cycle":src.get("cycle") or stamp()[:10]})
 if not records:raise ValueError(f"no VFR Dpn records parsed for {src['region']}; schema/endpoint may have changed")
 return records
def xml_from_zip(raw,region_key):
 if len(raw)>MAX_BYTES:raise ValueError("download exceeds size cap")
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  names=[n for n in z.namelist() if not n.endswith("/") and ("/embedded/" in n.lower() or n.lower().endswith((".ofmx",".xml")))]
  if not names:raise ValueError("OFMX archive contains no XML/embedded file")
  target=f"ofmx_{region_key}".lower()
  preferred=[n for n in names if n.rsplit("/",1)[-1].lower() in (target,target+".ofmx")]
  selected=preferred or names
  if len(selected)!=1:raise ValueError(f"ambiguous OFMX archive members: {len(selected)} candidates")
  return z.read(selected[0])
def validate_source(s):
 for k in ("region","regionName","regionKey","url","sourcePage","license"):
  if not clean(s.get(k)):raise ValueError(f"source missing {k}")
 if s["license"]!="OFMA_GUL":raise ValueError("OFMA GUL required")
 if not s["url"].startswith("https://snapshots.openflightmaps.org/live/") or not s["sourcePage"].startswith("https://openflightmaps.org/downloads/"):raise ValueError("source must use official snapshot and regional page")
def fetch(url):
 req=urllib.request.Request(url,headers={"User-Agent":UA})
 with urllib.request.urlopen(req,timeout=60) as r:
  raw=r.read(MAX_BYTES+1)
 if len(raw)>MAX_BYTES:raise ValueError("download exceeds size cap")
 return raw
def atomic_pair(csv_path,meta_path,csvdata,metadata):
 csv_path.parent.mkdir(parents=True,exist_ok=True);meta_path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(dir=csv_path.parent) as td:
  c=Path(td)/"points.csv";m=Path(td)/"meta.json";c.write_bytes(csvdata);m.write_text(json.dumps(metadata,indent=2)+"\n",encoding="utf-8")
  oldc=csv_path.read_bytes() if csv_path.exists() else None;oldm=meta_path.read_bytes() if meta_path.exists() else None
  try:os.replace(c,csv_path);os.replace(m,meta_path)
  except Exception:
   if oldc is None:csv_path.unlink(missing_ok=True)
   else:csv_path.write_bytes(oldc)
   if oldm is None:meta_path.unlink(missing_ok=True)
   else:meta_path.write_bytes(oldm)
   raise
def run(config=CONFIG,dry=False):
 cfg=json.loads(Path(config).read_text());airac=current_airac() if cfg.get("airac")=="auto" else str(cfg.get("airac"));sources=cfg.get("sources",[])
 if not sources:print("No OFMA OFMX sources configured; existing data retained.");return 0
 allrows=[];sm=[]
 for src in sources:
  validate_source(src);url=src["url"].replace("{airac}",airac);raw=fetch(url);xml=xml_from_zip(raw,src["regionKey"]);src["cycle"]=airac;records=parse_xml(xml,src);allrows.extend(records)
  sm.append({"region":src["region"],"regionName":src["regionName"],"sourcePage":src["sourcePage"],"downloadUrl":url,"cycle":airac,"effectiveDate":None,"license":"OFMA General Users License","attribution":src.get("attribution","OpenFlightMaps Association (OFMA)"),"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"parsedVfrPoints":len(records)})
 uniq={(r["region"],r["code"],r["lat"],r["lon"],r["kind"]):r for r in allrows};rows=sorted(uniq.values(),key=lambda r:(r["region"],r["kind"],r["code"],r["lat"],r["lon"]))
 buf=io.StringIO();buf.write("#version=1,generated_utc="+stamp()+"\n");w=csv.DictWriter(buf,fieldnames=COLUMNS);w.writeheader();w.writerows(rows);csvdata=buf.getvalue().encode()
 meta={"schemaVersion":1,"generatedUtc":stamp(),"airac":airac,"count":len(rows),"regions":sorted({r["region"] for r in rows}),"sources":sm,"license":"OFMA General Users License","licenseNotes":"Commercial use subject to GUL conditions. Preserve attribution; report errors/alterations and provide user error-reporting route as required. Reference-only, not primary navigation.","attribution":"OpenFlightMaps Association (OFMA)","sha256":hashlib.sha256(csvdata).hexdigest(),"sizeBytes":len(csvdata),"operationalUse":False}
 if dry:print(json.dumps({"pointCount":len(rows),"regions":meta["regions"],"sources":sm},indent=2));return 0
 atomic_pair(OUT,META,csvdata,meta);print(f"Imported {len(rows)} OFMA OFMX VFR points across {len(meta['regions'])} regions");return 0
def main():
 p=argparse.ArgumentParser();p.add_argument("--config",type=Path,default=CONFIG);p.add_argument("--dry-run",action="store_true");a=p.parse_args();return run(a.config,a.dry_run)
if __name__=="__main__":raise SystemExit(main())
