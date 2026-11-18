#!/usr/bin/env python3
"""Convert one ADS-B readsb aircraft trace into waypoint-match evidence.

Input is a readsb trace JSON object (metadata plus trace rows). This script
never promotes ADS-B-derived points into the authoritative navigation graph.
It writes versioned evidence and candidate waypoint matches only.
"""
import argparse, csv, json, math
from datetime import datetime, timezone
from pathlib import Path

def haversine_nm(lat1, lon1, lat2, lon2):
    r=3440.065
    p1,p2=math.radians(lat1),math.radians(lat2)
    dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(a))

def load_trace(path):
    obj=json.loads(Path(path).read_text())
    rows=obj.get("trace", [])
    out=[]
    for row in rows:
        if not isinstance(row,list) or len(row)<3: continue
        # readsb trace: [seconds_since_midnight, lat, lon, ...]
        try:
            sec,lat,lon=float(row[0]),float(row[1]),float(row[2])
        except (TypeError,ValueError): continue
        if not (-90<=lat<=90 and -180<=lon<=180): continue
        out.append({"seconds":sec,"lat":lat,"lon":lon,"raw":row})
    return obj,out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--trace",required=True)
    ap.add_argument("--waypoints",default="navigation/waypoints/flightgear_fixes.csv")
    ap.add_argument("--output",default="navigation/adsb_learning")
    ap.add_argument("--radius-nm",type=float,default=5.0)
    a=ap.parse_args()
    meta,pts=load_trace(a.trace)
    if not pts: raise SystemExit("No valid readsb trace positions found")
    fixes=[]
    with open(a.waypoints,newline="",encoding="utf-8") as f:
        for x in csv.DictReader(f):
            try: fixes.append((x["id"],float(x["latitude"]),float(x["longitude"])))
            except (KeyError,ValueError): continue
    matches=[]
    for name,lat,lon in fixes:
        nearest=min((haversine_nm(p["lat"],p["lon"],lat,lon),p) for p in pts)
        dist,p=nearest
        if dist<=a.radius_nm:
            matches.append({"fix":name,"latitude":lat,"longitude":lon,
                            "nearestTrackDistanceNm":round(dist,2),
                            "trackPosition":{"lat":p["lat"],"lon":p["lon"],"secondsSinceMidnight":p["seconds"]}})
    matches.sort(key=lambda x:x["trackPosition"]["secondsSinceMidnight"])
    ident={"icao":meta.get("icao"),"hex":meta.get("hex"),"flight":meta.get("flight"),
           "registration":meta.get("r"),"positions":len(pts)}
    out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload={"schemaVersion":1,"generatedAtUtc":datetime.now(timezone.utc).isoformat(),
             "source":"ADSB.lol/readsb historical trace supplied to workflow",
             "sourceLicense":"ODbL-1.0; derived database attribution/share-alike obligations apply",
             "identity":ident,"positionCount":len(pts),"matchRadiusNm":a.radius_nm,
             "matchedFixes":matches,
             "limitations":["A nearby ADS-B position is evidence of proximity, not proof the fix was crossed exactly.",
                            "ADS-B cannot establish filed airway, clearance, or procedure usage.",
                            "Candidates are not added to the authoritative navigation graph."]}
    (out/f"trace_{stamp}.json").write_text(json.dumps(payload,indent=2)+"\\n")
    # Aggregate only evidence-backed matches; repeated observations can later raise confidence.
    agg=out/"fix_evidence.json"
    old=json.loads(agg.read_text()) if agg.exists() else {"schemaVersion":1,"fixes":{}}
    for m in matches:
        rec=old["fixes"].setdefault(m["fix"],{"observations":0,"bestDistanceNm":None,"sources":[]})
        rec["observations"]+=1
        rec["bestDistanceNm"]=m["nearestTrackDistanceNm"] if rec["bestDistanceNm"] is None else min(rec["bestDistanceNm"],m["nearestTrackDistanceNm"])
        rec["sources"].append({"flight":ident,"distanceNm":m["nearestTrackDistanceNm"]})
    agg.write_text(json.dumps(old,indent=2)+"\\n")
    print(json.dumps({"identity":ident,"positions":len(pts),"matchedFixes":[m["fix"] for m in matches]},indent=2))
if __name__=="__main__": main()
