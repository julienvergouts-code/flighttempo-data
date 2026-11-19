#!/usr/bin/env python3
"""Cluster observed ADS-B trajectories and match vertices to a local open fix CSV."""
from __future__ import annotations
import argparse,csv,json,math
from pathlib import Path
from datetime import datetime,timezone
ATTRIBUTION="Contains information from adsb.lol, made available under the Open Database License (ODbL) 1.0."

def nm(a,b):
    p1,p2=math.radians(a[0]),math.radians(b[0]); dp=p2-p1; dl=math.radians(b[1]-a[1])
    h=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 3440.065*2*math.asin(math.sqrt(h))

def resample(line, spacing_nm=20):
    if len(line)<2:return line
    out=[line[0]]
    for a,b in zip(line,line[1:]):
        d=nm(a,b); n=max(1,math.ceil(d/spacing_nm))
        for i in range(1,n+1):
            t=i/n; out.append([a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t])
    return out

def distance_lines(a,b):
    aa=resample(a); bb=resample(b)
    if not aa or not bb:return float("inf")
    def directed(x,y): return sum(min(nm(p,q) for q in y) for p in x)/len(x)
    return (directed(aa,bb)+directed(bb,aa))/2

def load_fixes(path):
    fixes=[]
    with open(path,newline="",encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                ident=r.get("ident") or r.get("id") or r.get("name")
                lat=r.get("latitude") or r.get("lat"); lon=r.get("longitude") or r.get("lon")
                if ident and lat and lon: fixes.append({"ident":ident,"lat":float(lat),"lon":float(lon)})
            except ValueError: pass
    return fixes

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input-dir",default="observed_traces"); p.add_argument("--fixes",default="navigation/waypoints/flightgear_fixes.csv")
    p.add_argument("--output",default="preferred_routes/europe.json"); p.add_argument("--radius-nm",type=float,default=3.5)
    p.add_argument("--cluster-distance-nm",type=float,default=35); p.add_argument("--min-samples",type=int,default=2)
    a=p.parse_args(); traces=[]
    for f in Path(a.input_dir).glob("*.json"):
        try:
            x=json.loads(f.read_text()); line=x.get("geometry",[])
            if len(line)>=2: traces.append((x,line))
        except (OSError,json.JSONDecodeError): continue
    fixes=load_fixes(a.fixes)
    # Deterministic agglomerative grouping avoids a mandatory sklearn dependency.
    clusters=[]
    for item in traces:
        for c in clusters:
            if distance_lines(item[1],c["medoid"])<=a.cluster_distance_nm:
                c["items"].append(item); break
        else: clusters.append({"medoid":item[1],"items":[item]})
    corridors=[]
    for idx,c in enumerate(clusters,1):
        items=c["items"]
        if len(items)<a.min_samples: continue
        # Use the medoid's observed geometry as representative; never invent airway names.
        matched=[]
        for lat,lon in c["medoid"]:
            nearest=min(fixes,key=lambda f:nm((lat,lon),(f["lat"],f["lon"])),default=None)
            if nearest and nm((lat,lon),(nearest["lat"],nearest["lon"]))<=a.radius_nm:
                if not matched or matched[-1]["ident"]!=nearest["ident"]: matched.append({"ident":nearest["ident"],"lat":nearest["lat"],"lon":nearest["lon"]})
        first=min((x.get("date_utc","") for x,_ in items),default="")
        last=max((x.get("date_utc","") for x,_ in items),default="")
        origins={x.get("origin") for x,_ in items}; destinations={x.get("destination") for x,_ in items}
        corridors.append({"id":f"observed-{idx:04d}","origin":next(iter(origins)) if len(origins)==1 else None,
          "destination":next(iter(destinations)) if len(destinations)==1 else None,"geometry":c["medoid"],
          "sample_size":len(items),"first_seen":first,"last_seen":last,
          "confidence":round(min(0.99,0.5+0.1*math.log2(len(items))),3),
          "matched_fixes":matched,"source":"adsb.lol","license":"ODbL-1.0","attribution":ATTRIBUTION,
          "evidence":[{"icao":x.get("icao"),"callsign":x.get("callsign"),"date_utc":x.get("date_utc")} for x,_ in items]})
    result={"schema_version":1,"generated_at_utc":datetime.now(timezone.utc).isoformat(),"license":"ODbL-1.0",
      "source":"adsb.lol daily historical archive","attribution":ATTRIBUTION,"corridors":corridors}
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,indent=2)+"\n")
    print(f"Wrote {len(corridors)} corridor(s) from {len(traces)} trace(s) to {out}")
if __name__=="__main__":main()
