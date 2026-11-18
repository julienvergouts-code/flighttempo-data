#!/usr/bin/env python3
"""Compile FlightGear fix/airway CSVs into the versioned FTWG binary graph."""
import argparse, csv, math, struct, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FIXES=ROOT/"navigation/waypoints/flightgear_fixes.csv"
NAVAIDS=ROOT/"navigation/navaids/flightgear_navaids.csv"
AIRWAYS=ROOT/"navigation/airways/flightgear_airway_segments.csv"
OUTPUT=ROOT/"navigation/graph/ftwg_navgraph.bin"
MAGIC=b"FTWG"; VERSION=1
HEADER=struct.Struct("<4sHHII")
NODE=struct.Struct("<8siiB3x")
EDGE=struct.Struct("<IIH6s")
R=3440.065

def distance(a,b):
 p1,p2=math.radians(a[0]),math.radians(b[0]); dp=math.radians(b[0]-a[0]); dl=math.radians(b[1]-a[1])
 x=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
 return 2*R*math.atan2(math.sqrt(x),math.sqrt(1-x))

def field(row,*names):
 for n in names:
  if row.get(n) not in (None,""): return row[n].strip()
 return ""

def load_nodes():
 nodes={}
 for path,kind in ((NAVAIDS,2),(FIXES,1)):
  if not path.exists():
   if kind==1: raise FileNotFoundError(path)
   continue
  with path.open(newline="",encoding="utf-8",errors="replace") as f:
   for row in csv.DictReader(f):
    ident=field(row,"ident","id","fix_id","navaid_id","name").upper()
    if not ident or len(ident)>8: continue
    try: lat=float(field(row,"lat","latitude","latitude_deg")); lon=float(field(row,"lon","longitude","longitude_deg"))
    except ValueError: continue
    if not(-90<=lat<=90 and -180<=lon<=180): continue
    key=(ident,round(lat*100),round(lon*100))
    nodes.setdefault(key,(ident,lat,lon,kind))
 return sorted(nodes.values(),key=lambda n:(n[0],n[3],n[1],n[2]))

def compile_graph(out):
 nodes=load_nodes()
 if not nodes: raise RuntimeError("No navigation nodes loaded")
 by={}
 for i,n in enumerate(nodes): by.setdefault(n[0],[]).append(i)
 if not AIRWAYS.exists(): raise FileNotFoundError(AIRWAYS)
 edges={}
 with AIRWAYS.open(newline="",encoding="utf-8",errors="replace") as f:
  for row in csv.DictReader(f):
   airway=field(row,"airway","airway_id","route").upper()[:6]
   a=field(row,"from_fix","start_fix","fix1","from_id","source_fix").upper()
   b=field(row,"to_fix","end_fix","fix2","to_id","target_fix").upper()
   if a not in by or b not in by or a==b: continue
   best=None
   for u in by[a]:
    for v in by[b]:
     d=distance(nodes[u][1:3],nodes[v][1:3])
     if best is None or d<best[0]: best=(d,u,v)
   if best is None or best[0]>1500: continue
   d,u,v=best; tenths=min(65535,max(1,round(d*10)))
   direction=field(row,"direction","dir").upper()
   pairs=[(u,v)] if direction in ("F","FORWARD","1") else [(u,v),(v,u)]
   for x,y in pairs: edges[(x,y,airway)]=(x,y,tenths,airway)
 if not edges:
  raise RuntimeError(f"No airway edges resolved from {rows} CSV rows; inspect the logged header and map its endpoint columns.")
 packed=sorted(edges.values())
 out.parent.mkdir(parents=True,exist_ok=True)
 with out.open("wb") as f:
  f.write(HEADER.pack(MAGIC,VERSION,0,len(nodes),len(packed)))
  for ident,lat,lon,kind in nodes:
   f.write(NODE.pack(ident.encode("ascii","ignore")[:8],round(lat*1e6),round(lon*1e6),kind))
  for u,v,d,awy in packed:
   f.write(EDGE.pack(u,v,d,awy.encode("ascii","ignore")[:6]))
 expected=16+20*len(nodes)+16*len(packed)
 if out.stat().st_size!=expected: raise RuntimeError("FTWG binary size verification failed")
 print(f"[FTWG] compiled {len(nodes):,} nodes, {len(packed):,} directed edges, {out.stat().st_size:,} bytes")

if __name__=="__main__":
 p=argparse.ArgumentParser(); p.add_argument("--out",type=Path,default=OUTPUT); a=p.parse_args()
 try: compile_graph(a.out)
 except Exception as e: sys.exit(f"[FTWG ERROR] {e}")
