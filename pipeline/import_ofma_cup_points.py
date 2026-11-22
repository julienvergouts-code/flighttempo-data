#!/usr/bin/env python3
"""Import explicitly configured OpenFlightMaps CUP reference points (not operational navigation)."""
import argparse,csv,hashlib,io,json,os,re,tempfile,urllib.request,zipfile
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; CONFIG=ROOT/"data/ofma_sources.json"; OUT=ROOT/"data/ofma_vfr_points.csv"; META=ROOT/"data/ofma_vfr_points_meta.json"
COLUMNS=["region","code","name","lat","lon","kind","source","license","updated_date"]; MAX_BYTES=40*1024*1024
UA="FlightTempo-OFMA-VFR-Importer/1.0 (+https://github.com/julienvergouts-code/flighttempo-data)"
def stamp():return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def clean(x):return re.sub(r"\s+"," ",str(x or "")).strip()
def parse_coordinate(value):
 s=clean(value).upper()
 if not s:raise ValueError("empty coordinate")
 try:return float(s)
 except ValueError:pass
 hemi=s[-1] if s[-1] in "NSEW" else ""
 if not hemi:raise ValueError(f"coordinate hemisphere missing: {value!r}")
 body=s[:-1].strip().replace(" ","")
 if ":" in body:
  parts=body.split(":")
  if len(parts) not in (2,3):raise ValueError(f"bad coordinate: {value!r}")
  deg=int(parts[0]);minutes=float(parts[1]);seconds=float(parts[2]) if len(parts)==3 else 0
 elif "." in body:
  digits,fraction=body.split(".",1)[0],body.split(".",1)[0]
  frac=body.split(".",1)[0]
  decimal_part="."+body.split(".",1)[1]
  if hemi in "NS" and len(digits)==4:
   deg=int(digits[:2]);minutes=float(digits[2:]+decimal_part);seconds=0
  elif hemi in "EW" and len(digits) in (4,5):
   width=len(digits)-2;deg=int(digits[:width]);minutes=float(digits[width:]+decimal_part);seconds=0
  else:
   deg=float(body);minutes=seconds=0
 else:
  digits=body
  if hemi in "NS":width=2
  elif len(digits) in (4,6):width=2
  else:width=3
  deg=int(digits[:width]);tail=digits[width:]
  if len(tail)==4:minutes=int(tail[:2]);seconds=int(tail[2:])
  elif len(tail)==2:minutes=int(tail);seconds=0
  elif len(tail)==0:minutes=seconds=0
  else:raise ValueError(f"unsupported coordinate digits: {value!r}")
 if minutes>=60 or seconds>=60:raise ValueError("minutes/seconds out of range")
 limit=90 if hemi in "NS" else 180
 if deg>limit or (deg==limit and (minutes or seconds)):raise ValueError("coordinate degrees out of range")
 result=deg+minutes/60+seconds/3600
 return -result if hemi in "SW" else result
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
 cfg=json.loads(Path(config).read_text());sources=cfg.get("sources",[])
 if not sources:print("No verified OFMA URLs configured. Existing dataset retained; no publication.");return 0
 rows=[];sm=[]
 for src in sources:
  validate_source(src);raw=fetch(src["url"]);records=parse_cup(payload(raw),src);rows+=records
  sm.append({"region":src["region"],"regionName":src["regionName"],"sourcePage":src["sourcePage"],"downloadUrl":src["url"],"cycle":src.get("cycle"),"effectiveDate":src.get("effectiveDate"),"license":"OFMA General Users License","attribution":src.get("attribution","OpenFlightMaps Association (OFMA)"),"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"parsedPoints":len(records)})
 uniq={(r["region"],r["code"],r["lat"],r["lon"]):r for r in rows};rows=sorted(uniq.values(),key=lambda r:(r["region"],r["code"],r["lat"],r["lon"]))
 buf=io.StringIO();buf.write("#version=1,generated_utc="+stamp()+"\n");w=csv.DictWriter(buf,fieldnames=COLUMNS);w.writeheader();w.writerows(rows);csvdata=buf.getvalue().encode()
 meta={"schemaVersion":1,"generatedUtc":stamp(),"count":len(rows),"regions":sorted({r["region"] for r in rows}),"sources":sm,"license":"OFMA General Users License","licenseNotes":"Commercial use is permitted subject to GUL conditions. Preserve attribution; report alterations and user corrections as required. Reference-only, not primary navigation.","attribution":"OpenFlightMaps Association (OFMA)","sha256":hashlib.sha256(csvdata).hexdigest(),"sizeBytes":len(csvdata),"operationalUse":False}
 if dry:print(json.dumps({"pointCount":len(rows),"regions":meta["regions"],"sources":sm},indent=2));return 0
 atomic_pair(OUT,META,csvdata,meta);print(f"Imported {len(rows)} OFMA CUP points in {len(meta['regions'])} regions");return 0
def main():
 p=argparse.ArgumentParser();p.add_argument("--config",type=Path,default=CONFIG);p.add_argument("--dry-run",action="store_true");a=p.parse_args();return run(a.config,a.dry_run)
if __name__=="__main__":raise SystemExit(main())
