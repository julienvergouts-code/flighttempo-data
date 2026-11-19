#!/usr/bin/env python3
"""Fail-closed validation for candidate observed corridor data."""
from __future__ import annotations
import argparse,csv,json,math
from pathlib import Path
from datetime import datetime,timezone
def nm(a,b):
 p1,p2=math.radians(a[0]),math.radians(b[0]); dp=p2-p1; dl=math.radians(b[1]-a[1]); h=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
 return 3440.065*2*math.asin(math.sqrt(h))
def main():
 p=argparse.ArgumentParser();p.add_argument("--input",default="preferred_routes/europe.json");p.add_argument("--fixes",default="navigation/waypoints/flightgear_fixes.csv");p.add_argument("--min-samples",type=int,default=5);p.add_argument("--max-jump-nm",type=float,default=50);p.add_argument("--manifest",default="preferred_routes/manifest.json");a=p.parse_args()
 data=json.loads(Path(a.input).read_text()); known=set()
 with open(a.fixes,newline="",encoding="utf-8") as f:
  for r in csv.DictReader(f):
   ident=r.get("ident") or r.get("id") or r.get("name")
   if ident:known.add(ident)
 errors=[]
 for c in data.get("corridors",[]):
  cid=c.get("id","unknown")
  if c.get("sample_size",0)<a.min_samples:errors.append(f"{cid}: sample_size below {a.min_samples}")
  geom=c.get("geometry",[])
  for x,y in zip(geom,geom[1:]):
   if nm(x,y)>a.max_jump_nm:errors.append(f"{cid}: consecutive geometry jump exceeds {a.max_jump_nm} NM")
  for f in c.get("matched_fixes",[]):
   ident=f.get("ident") if isinstance(f,dict) else f
   if ident not in known:errors.append(f"{cid}: matched fix {ident} absent from fixes CSV")
 if errors:
  print("VALIDATION BLOCKED");[print(" - "+e) for e in errors];raise SystemExit(1)
 manifest={"schema_version":1,"version":datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),"generated_at_utc":datetime.now(timezone.utc).isoformat(),"data_file":str(Path(a.input)),"license":"ODbL-1.0","source":"adsb.lol","corridor_count":len(data.get("corridors",[])),"validation":{"passed":True,"minimum_sample_size":a.min_samples,"maximum_consecutive_jump_nm":a.max_jump_nm}}
 out=Path(a.manifest);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(manifest,indent=2)+"\n");print(f"VALIDATION PASSED; manifest written: {out}")
if __name__=="__main__":main()
