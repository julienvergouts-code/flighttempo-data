#!/usr/bin/env python3
"""Extract airport-pair candidate trajectories from locally downloaded adsb.lol daily traces.

adsb.lol publishes whole-sky daily archives, not a documented historical city-pair
search endpoint. Download/extract an archive separately, then point --input-dir at
its traces/ directory. Supports readsb trace JSON (timestamp + trace arrays) and
normalised point-list JSON fixtures.
"""
from __future__ import annotations
import argparse, json, math
from datetime import datetime, timezone
from pathlib import Path

ATTRIBUTION = "Contains information from adsb.lol, made available under the Open Database License (ODbL) 1.0."

def haversine_nm(a, b):
    p1,p2=math.radians(a[0]),math.radians(b[0]); dp=math.radians(b[0]-a[0]); dl=math.radians(b[1]-a[1])
    x=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 3440.065*2*math.asin(math.sqrt(x))

def rdp(points, epsilon_nm):
    if len(points)<3: return points
    start,end=points[0],points[-1]
    def distance(p):
        # local equirectangular cross-track approximation in NM
        lat0=math.radians((start["lat"]+end["lat"])/2)
        ax,ay=start["lon"]*60*math.cos(lat0),start["lat"]*60
        bx,by=end["lon"]*60*math.cos(lat0),end["lat"]*60
        px,py=p["lon"]*60*math.cos(lat0),p["lat"]*60
        dx,dy=bx-ax,by-ay
        if dx==dy==0: return math.hypot(px-ax,py-ay)
        t=max(0,min(1,((px-ax)*dx+(py-ay)*dy)/(dx*dx+dy*dy)))
        return math.hypot(px-(ax+t*dx),py-(ay+t*dy))
    idx=max(range(1,len(points)-1),key=lambda i:distance(points[i]))
    if distance(points[idx])>epsilon_nm:
        return rdp(points[:idx+1],epsilon_nm)[:-1]+rdp(points[idx:],epsilon_nm)
    return [start,end]

def read_trace(path):
    obj=json.loads(path.read_text())
    # readsb archive format: timestamp + trace rows [seconds, lat, lon, alt, gs, track, ...]
    if isinstance(obj,dict) and isinstance(obj.get("trace"),list):
        base=float(obj.get("timestamp",0)); out=[]
        for row in obj["trace"]:
            if not isinstance(row,list) or len(row)<4 or row[1] is None or row[2] is None: continue
            alt=row[3]
            if isinstance(alt,str) or alt is None: continue
            out.append({"timestamp":base+float(row[0]),"lat":float(row[1]),"lon":float(row[2]),"altitude_ft":float(alt),
                        "ground_speed_kt":row[4] if len(row)>4 else None,"track_deg":row[5] if len(row)>5 else None})
        return {"icao":obj.get("icao"),"callsign":obj.get("flight"),"points":out}
    if isinstance(obj,dict) and isinstance(obj.get("points"),list): return obj
    raise ValueError(f"Unsupported trace schema: {path}")

def airport_distance(point, airport):
    return haversine_nm((point["lat"],point["lon"]),(airport["lat"],airport["lon"]))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input-dir",required=True,help="Extracted adsb.lol traces directory")
    ap.add_argument("--airports",default="navigation/airports/ourairports_airports.csv")
    ap.add_argument("--origin",required=True); ap.add_argument("--destination",required=True)
    ap.add_argument("--date",required=True,help="UTC date YYYY-MM-DD")
    ap.add_argument("--output-dir",default="observed_traces")
    ap.add_argument("--airport-radius-nm",type=float,default=30)
    ap.add_argument("--min-altitude-ft",type=int,default=10000)
    ap.add_argument("--rdp-epsilon-nm",type=float,default=2.0)
    args=ap.parse_args()
    import csv
    airports={}
    with open(args.airports,newline="",encoding="utf-8") as f:
        for r in csv.DictReader(f):
            code=(r.get("ident") or r.get("gps_code") or "").upper()
            try: airports[code]={"lat":float(r["latitude_deg"]), "lon":float(r["longitude_deg"])}
            except (ValueError,KeyError): continue
    if args.origin not in airports or args.destination not in airports:
        raise SystemExit("Airport ICAO not found in OurAirports CSV (ident/gps_code).")
    outdir=Path(args.output_dir); outdir.mkdir(parents=True,exist_ok=True); saved=0
    for path in Path(args.input_dir).rglob("*"):
        if not path.is_file() or path.suffix not in (".json",".gz"): continue
        try:
            if path.suffix==".gz":
                import gzip
                obj=json.loads(gzip.decompress(path.read_bytes()))
                tmp=path.with_suffix(".json.tmp"); tmp.write_text(json.dumps(obj)); data=read_trace(tmp); tmp.unlink()
            else: data=read_trace(path)
            pts=sorted(data["points"],key=lambda p:p["timestamp"])
            if len(pts)<2: continue
            # Airport proximity is tested against the full trace, before cruise filtering.
            if min(airport_distance(p,airports[args.origin]) for p in pts)>args.airport_radius_nm: continue
            if min(airport_distance(p,airports[args.destination]) for p in pts)>args.airport_radius_nm: continue
            pts=[p for p in pts if p["altitude_ft"]>=args.min_altitude_ft and -90<=p["lat"]<=90 and -180<=p["lon"]<=180]
            if len(pts)<2: continue
            pts=rdp(pts,args.rdp_epsilon_nm)
            record={"schema_version":1,"origin":args.origin,"destination":args.destination,"date_utc":args.date,
                    "icao":data.get("icao"),"callsign":data.get("callsign"),"geometry":[[p["lat"],p["lon"]] for p in pts],
                    "points":pts,"source":"adsb.lol daily historical archive","license":"ODbL-1.0","attribution":ATTRIBUTION,
                    "retrieved_at_utc":datetime.now(timezone.utc).isoformat()}
            name=f"{args.origin}-{args.destination}-{args.date}-{data.get('icao') or path.stem}.json"
            (outdir/name).write_text(json.dumps(record,indent=2)+"\n"); saved+=1
        except (ValueError,KeyError,TypeError,json.JSONDecodeError,OSError) as e:
            print(f"SKIP {path}: {e}")
    print(f"Saved {saved} matching candidate trace(s).")
    if saved==0: raise SystemExit("No airport-pair traces found; archive may not cover the date/region.")

if __name__=="__main__": main()
