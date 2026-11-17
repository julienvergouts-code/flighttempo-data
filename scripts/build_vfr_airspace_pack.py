#!/usr/bin/env python3
"""Fail-closed AIXM 4.x to offline VFR airspace pack importer."""
from __future__ import annotations
import argparse, gzip, hashlib, json, math, re, sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

KEEP={"CTR","TMA","D","P","R","RMZ"}
CURVES={"Arc","ArcString","ArcByCenterPoint","Circle","CircleByCenterPoint","Geodesic","GeodesicString","CompositeCurve","Curve","LineStringSegment"}
NUMBER=re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")

def lname(tag): return tag.rsplit("}",1)[-1].split(":")[-1]
def first(node,names):
    for e in node.iter():
        if e is not node and lname(e.tag) in names and e.text and e.text.strip(): return e.text.strip()
    return None
def val(node,names):
    for e in node.iter():
        if e is not node and lname(e.tag) in names and e.text and e.text.strip():
            return {"value":e.text.strip(),"uom":e.attrib.get("uom")}
    return None
def order_for(node,override):
    if override!="auto": return override
    for e in node.iter():
        labels=e.attrib.get("axisLabels","").lower().replace(","," ").split()
        if len(labels)>=2:
            if labels[0] in {"lat","latitude","north"}: return "latlon"
            if labels[0] in {"lon","long","longitude","east"}: return "lonlat"
        crs=e.attrib.get("srsName","").lower()
        if "crs84" in crs or "crs:84" in crs: return "lonlat"
    return "lonlat" # documented AIXM aviation convention; override after CRS inspection

def ring_points(ring,order):
    for e in ring.iter():
        if lname(e.tag) in CURVES: raise ValueError("unsupported curved primitive: "+lname(e.tag))
    for e in ring.iter():
        if lname(e.tag)=="posList" and e.text:
            dim=int(e.attrib.get("srsDimension",e.attrib.get("dimension","2")))
            nums=[float(x) for x in NUMBER.findall(e.text)]
            if dim!=2 or len(nums)<6 or len(nums)%2: raise ValueError("invalid 2D posList")
            pts=[]
            for a,b in zip(nums[::2],nums[1::2]):
                lon,lat=(a,b) if order=="lonlat" else (b,a)
                if not (-180<=lon<=180 and -90<=lat<=90): raise ValueError("coordinate outside WGS84 bounds")
                pts.append([round(lon,7),round(lat,7)])
            if pts[0]!=pts[-1]: pts.append(pts[0][:])
            if len(pts)<4: raise ValueError("ring needs >=4 positions")
            return pts
    positions=[]
    for e in ring.iter():
        if lname(e.tag)=="pos" and e.text:
            nums=[float(x) for x in NUMBER.findall(e.text)]
            if len(nums)!=2: raise ValueError("unsupported gml:pos dimension")
            a,b=nums; lon,lat=(a,b) if order=="lonlat" else (b,a)
            positions.append([lon,lat])
    if positions:
        if positions[0]!=positions[-1]: positions.append(positions[0][:])
        if len(positions)>=4: return positions
    raise ValueError("ring has no supported posList/pos")

def polygon(poly,order):
    exterior=None; holes=[]
    for e in poly.iter():
        n=lname(e.tag)
        if n in CURVES: raise ValueError("unsupported curved primitive: "+n)
        if n in {"exterior","outerBoundaryIs","interior","innerBoundaryIs"}:
            rings=[x for x in e.iter() if lname(x.tag) in {"LinearRing","Ring"}]
            if rings:
                pts=ring_points(rings[0],order)
                if n in {"exterior","outerBoundaryIs"}: exterior=pts
                else: holes.append(pts)
    if exterior is None:
        rings=[x for x in poly.iter() if lname(x.tag) in {"LinearRing","Ring"}]
        if rings: exterior=ring_points(rings[0],order)
    if exterior is None: raise ValueError("polygon missing exterior ring")
    return {"type":"Polygon","coordinates":[exterior,*holes]}

def geometry(volume,axis_order):
    wrappers={"horizontalProjection","horizontalBoundary","geometry","theGeom"}
    wrappers_found=[e for e in volume.iter() if lname(e.tag) in wrappers]
    root=wrappers_found[0] if wrappers_found else volume
    order=order_for(root,axis_order); polys=[]
    for e in root.iter():
        n=lname(e.tag)
        if n in CURVES: raise ValueError("unsupported curved primitive: "+n)
        if n in {"Polygon","PolygonPatch"}: polys.append(polygon(e,order))
    if not polys: return None
    return polys[0] if len(polys)==1 else {"type":"MultiPolygon","coordinates":[p["coordinates"] for p in polys]}

def bbox(g):
    polys=[g["coordinates"]] if g["type"]=="Polygon" else g["coordinates"]
    pts=[p for poly in polys for ring in poly for p in ring]
    return [round(min(p[0] for p in pts),7),round(min(p[1] for p in pts),7),
            round(max(p[0] for p in pts),7),round(max(p[1] for p in pts),7)]

def extract(root,axis_order):
    records=[]; errors=Counter()
    for fi,feature in enumerate(e for e in root.iter() if lname(e.tag) in {"Airspace","AirspaceType"}):
        name=first(feature,{"txtName","name","txtLocalName","designator"}) or ""
        kind=(first(feature,{"codeType","type","codeAirspaceType"}) or "").upper()
        kind={"CONTROL_ZONE":"CTR","CONTROL_AREA":"TMA"}.get(kind,kind)
        if kind not in KEEP: continue
        fid=feature.attrib.get("id") or feature.attrib.get("{http://www.opengis.net/gml}id") or f"feature-{fi}"
        volumes=[e for e in feature.iter() if e is not feature and lname(e.tag) in {"AirspaceVolume","AirspaceVolumeType"}]
        if not volumes: volumes=[feature]
        for vi,volume in enumerate(volumes):
            try:
                g=geometry(volume,axis_order)
                if g is None: errors["missing_geometry"]+=1; continue
                records.append({"id":f"{fid}:volume-{vi}","sourceFeatureId":fid,"name":name,"airspaceType":kind,
                    "lowerLimit":val(volume,{"valLowerLimit","lowerLimit","lowerLimitValue"}),
                    "lowerLimitReference":first(volume,{"codeLowerLimitReference","lowerLimitReference","codeLowerReference"}),
                    "upperLimit":val(volume,{"valUpperLimit","upperLimit","upperLimitValue"}),
                    "upperLimitReference":first(volume,{"codeUpperLimitReference","upperLimitReference","codeUpperReference"}),
                    "geometry":g,"bbox":bbox(g)})
            except (ValueError,TypeError) as ex: errors[str(ex)]+=1
    return records,errors

def write_gzip(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
    with path.open("wb") as f:
        with gzip.GzipFile(filename="",mode="wb",fileobj=f,mtime=0,compresslevel=9) as z: z.write(raw)
    data=path.read_bytes()
    return hashlib.sha256(data).hexdigest(),len(data)

def build(src,out,meta,country,effective,axis):
    root=ET.parse(src).getroot()
    rows,errors=extract(root,axis)
    if not rows: raise RuntimeError("No supported polygons extracted; refusing to publish empty pack")
    digest,size=write_gzip(out,rows)
    manifest={"schemaVersion":1,"dataset":"vfr-airspace","country":country,"sourceFile":src.name,
      "sourceSha256":hashlib.sha256(src.read_bytes()).hexdigest(),"sourceFormat":"AIXM 4.x XML",
      "effectiveDate":effective,"generatedAtUtc":datetime.now(timezone.utc).isoformat(),
      "coordinateReference":"WGS84","coordinateOrder":"longitude,latitude","axisOrderMode":axis,
      "recordCount":len(rows),"airspaceTypeCounts":dict(Counter(r["airspaceType"] for r in rows)),
      "errorCounts":dict(errors),"packPath":str(out),"packSha256":digest,"packSizeBytes":size,
      "curveHandling":"Curved GML primitives fail closed; no silent straight-line approximation",
      "operationallyAvailable":False,
      "notes":["Each AirspaceVolume remains a separate record with its own vertical limits.",
       "Interior rings are retained. Vertical values, units and references are preserved as supplied.",
       "Do not release until source CRS, classification mapping and all unsupported geometry are reviewed."]}
    meta.parent.mkdir(parents=True,exist_ok=True); meta.write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    return manifest

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",required=True,type=Path); p.add_argument("--country",required=True,choices=["BE","FR"])
    p.add_argument("--effective-date"); p.add_argument("--axis-order",choices=["auto","lonlat","latlon"],default="auto")
    p.add_argument("--output",type=Path,default=Path("navigation/vfr/airspace_vfr.json.gz"))
    p.add_argument("--manifest",type=Path,default=Path("navigation/vfr/vfr_meta.json"))
    a=p.parse_args()
    try:
        m=build(a.input,a.output,a.manifest,a.country,a.effective_date,a.axis_order)
        print(json.dumps({k:m[k] for k in ("country","recordCount","airspaceTypeCounts","errorCounts","packSha256")},indent=2))
    except Exception as e: print("ERROR:",e,file=sys.stderr); return 2
    return 0
if __name__=="__main__": raise SystemExit(main())
