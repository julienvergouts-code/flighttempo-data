#!/usr/bin/env python3
"""Import explicitly configured OpenFlightMaps CUP reference points (not operational navigation)."""
import argparse,csv,hashlib,io,json,re,tempfile,urllib.request,zipfile
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; CONFIG=ROOT/"data/ofma_sources.json"; OUT=ROOT/"data/ofma_vfr_points.csv"; META=ROOT/"data/ofma_vfr_points_meta.json"
COLUMNS=["region","code","name","lat","lon","kind","source","license","updated_date"]; MAX_BYTES=40*1024*1024
UA="FlightTempo-OFMA-VFR-Importer/1.0 (+https://github.com/julienvergouts-code/flighttempo-data)"
def stamp():return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def clean(x):return re.sub(r"\\s+"," ",str(x or "")).strip()
def parse_coordinate(value):
 s=clean(value).upper()
 if not s:raise ValueError("empty coordinate")
 try:return float(s)
 except ValueError:pass
 m=re.fullmatch(r"(\\d{2,3})(?::(\\d{2}(?:\\.\\d+)?)(?:')?(?:\\s*(\\d{2}(?:\\.\\d+)?)(?:\\")?)?|(?:(\\d{2})(?:\\.(\\d+))?))(?:\\s*([NSEW]))",s)
 if not m:raise ValueError(f"unsupported CUP coordinate: {value!r}")
 deg=int(m.group(1)); hemi=m.group(6)
 if m.group(2):
  minutes=float(m.group(2)); seconds=float(m.group(3) or 0)
 elif m.group(4):
  minutes=float(m.group(4)); seconds=0
  # A six-digit integer DDMMSS is parsed as minutes+seconds only when the
  # numeric minutes field exceeds 59; otherwise standard DDMM[.fraction] is used.
  if minutes>=60:
   minutes=int(m.group(4)[:2]);seconds=int(m.group(4)[2:])+(float("0."+m.group(5)) if m.group(5) else 0)
 else:minutes=0;seconds=0
 if minutes>=60 or seconds>=60:raise ValueError("minutes/seconds out of range")
 result=deg+minutes/60+seconds/3600
 if hemi in "SW":result=-result
 limit=90 if hemi in "NS" else 180
 if deg>limit or result>limit:raise ValueError("coordinate degrees out of range")
 return result
def payload(raw):
 if len(raw)>MAX_BYTES:raise ValueError("source exceeds byte cap")
 if raw.startswith(b"PK"):
  with zipfile.ZipFile(io.BytesIO(raw)) as z:
   names=[n for n in z.namelist() if n.lower().endswith(".cup") and not n.startswith("__MACOSX/")]
   if len(names)!=1:raise ValueError(f"ZIP must contain exactly one CUP file, found {len(names)}")
   raw=z.read(names[0])
 return raw.decode("utf-8-sig",errors="replace")
def parse_cup(text,src):
 reader=csv.DictReader(io.StringIO(text));headers={x.strip().lower() for x in (reader.fieldnames or [])}
 need={"name","code","lat","lon"}
 if not need<=headers:raise ValueError(f"CUP schema missing {sorted(need-headers)}")
 out=[]
 for row in reader:
  row={k.strip().lower():v for k,v in row.items() if k};code=clean(row.get("code")).upper();name=clean(row.get("name"))
  if not code and not name:continue
  lat=parse_coordinate(row.get("lat"));lon=parse_coordinate(row.get("lon"))
  if not -90<=lat<=90 or not -180<=lon<=180 or (lat==0 and lon==0):raise ValueError(f"invalid coordinates: {code or name}")
  out.append({"region":src["region"],"code":code or name[:32],"name":name or code,"lat":round(lat,6),"lon":round(lon,6),"kind":clean(row.get("style")) or clean(row.get("type")) or "CUP_POINT","source":"OFMA","license":"OFMA_GUL","updated_date":src.get("effectiveDate") or src.get("cycle") or stamp()[:10]})
 if not out:raise ValueError(f"zero points in {src['region']}")
 return out
def validate_source(s):
 for k in ("region","regionName","url","sourcePage","license"):
  if not clean(s.get(k)):raise ValueError(f"source missing {k}")
 if s["license"] not in ("OFMA_GUL","OFMA_GUL_CONFIRMED"):raise ValueError("OFMA GUL licence tag required")
 if not s["url"].startswith("https://") or not s["sourcePage"].startswith("https://openflightmaps.org/"):raise ValueError("HTTPS and official OFMA source page required")
def fetch(url):
 req=urllib.request.Request(url,headers={"User-Agent":UA})
 with urllib.request.urlopen(req,timeout=60) as r:raw=r.read(MAX_BYTES+1)
 if len(raw)>MAX_BYTES:raise ValueError("download too large")
 return raw
def atomic_pair(csv_path,meta_path,csvdata,metadata):
 csv_path.parent.mkdir(parents=True,exist_ok=True);meta_path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(dir=csv_path.parent) as td:
  c=Path(td)/"points.csv";m=Path(td)/"meta.json";c.write_bytes(csvdata);m.write_text(json.dumps(metadata,indent=2)+"\\n",encoding="utf-8")
  oldc=csv_path.read_bytes() if csv_path.exists() else None;oldm=meta_path.read_bytes() if meta_path.exists() else None
  try:csv_path.replace(c) if False else None;csv_path.write_bytes(c.read_bytes());meta_path.write_bytes(m.read_bytes())
  except Exception:
   if oldc is None:csv_path.unlink(missing_ok=True)
   else:csv_path.write_bytes(oldc)
   if oldm is None:meta_path.unlink(missing_ok=True)
   else:meta_path.write_bytes(oldm)
   raise
def run(config=CONFIG,dry=False):
 cfg=json.loads(Path(config).read_text());sources=cfg.get("sources",[])
 if not sources:print("No verified OFMA URLs configured. Existing dataset retained; no publication.");return 0
 rows=[];sm=[]
 for src in sources:
  validate_source(src);raw=fetch(src["url"]);records=parse_cup(payload(raw),src);rows+=records
  sm.append({"region":src["region"],"regionName":src["regionName"],"sourcePage":src["sourcePage"],"downloadUrl":src["url"],"cycle":src.get("cycle"),"effectiveDate":src.get("effectiveDate"),"license":"OFMA General Users License","attribution":src.get("attribution","OpenFlightMaps Association (OFMA)"),"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"parsedPoints":len(records)})
 uniq={(r["region"],r["code"],r["lat"],r["lon"]):r for r in rows};rows=sorted(uniq.values(),key=lambda r:(r["region"],r["code"],r["lat"],r["lon"]))
 buf=io.StringIO();buf.write("#version=1,generated_utc="+stamp()+"\\n");w=csv.DictWriter(buf,fieldnames=COLUMNS);w.writeheader();w.writerows(rows);csvdata=buf.getvalue().encode()
 meta={"schemaVersion":1,"generatedUtc":stamp(),"count":len(rows),"regions":sorted({r["region"] for r in rows}),"sources":sm,"license":"OFMA General Users License","licenseNotes":"Commercial use is permitted subject to GUL conditions. Preserve attribution; report alterations and user corrections as required. Reference-only, not primary navigation.","attribution":"OpenFlightMaps Association (OFMA)","sha256":hashlib.sha256(csvdata).hexdigest(),"sizeBytes":len(csvdata),"operationalUse":False}
 if dry:print(json.dumps({"pointCount":len(rows),"regions":meta["regions"],"sources":sm},indent=2));return 0
 atomic_pair(OUT,META,csvdata,meta);print(f"Imported {len(rows)} OFMA CUP points in {len(meta['regions'])} regions");return 0
def main():
 p=argparse.ArgumentParser();p.add_argument("--config",type=Path,default=CONFIG);p.add_argument("--dry-run",action="store_true");a=p.parse_args();return run(a.config,a.dry_run)
if __name__=="__main__":raise SystemExit(main())
