#!/usr/bin/env python3
"""Aircraft leg segmentation with ground-dwell splits (even with zero timestamp gap)."""
from __future__ import annotations
import math
from typing import Iterable

def haversine_nm(a,b):
 p1,p2=math.radians(a[0]),math.radians(b[0]); dp=p2-p1; dl=math.radians(b[1]-a[1])
 h=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
 return 3440.065*2*math.asin(math.sqrt(h))

def near_airport(point, airports, radius_nm=3.0):
 return min((haversine_nm((point["lat"],point["lon"]),(a["lat"],a["lon"])) for a in airports),default=float("inf"))<=radius_nm

def is_ground_candidate(p, airports, speed_threshold=40, elevation_tolerance_ft=500, airport_radius_nm=3):
 speed=p.get("ground_speed_kt",p.get("gs"))
 alt=p.get("altitude_ft",p.get("alt"))
 if alt in ("ground",None): alt_ok=True
 else:
  try: alt=float(alt); elev=p.get("airport_elevation_ft")
  except (ValueError,TypeError): return False
  if elev is None:
   # If aircraft is explicitly tagged ground by the source, altitude can be absent;
   # otherwise require a known airport elevation to prevent low-altitude false positives.
   alt_ok=False
  else: alt_ok=abs(alt-float(elev))<=elevation_tolerance_ft
 try: slow=speed is not None and float(speed)<speed_threshold
 except (ValueError,TypeError): slow=False
 return slow and alt_ok and near_airport(p,airports,airport_radius_nm)

def segment_legs(points, airports, min_ground_seconds=300, max_gap_seconds=1200):
 """Return legs with indices and split reasons. Ground dwell splits sectors independent of gap."""
 pts=sorted(points,key=lambda p:float(p["timestamp"]))
 if not pts:return []
 ground=[]
 for p in pts: ground.append(is_ground_candidate(p,airports))
 # identify sustained ground runs, with no timestamp-gap requirement
 runs=[]; i=0
 while i<len(pts):
  if not ground[i]: i+=1; continue
  j=i
  while j+1<len(pts) and ground[j+1] and float(pts[j+1]["timestamp"])-float(pts[j]["timestamp"])<=max_gap_seconds: j+=1
  duration=float(pts[j]["timestamp"])-float(pts[i]["timestamp"])
  if duration>=min_ground_seconds: runs.append((i,j,duration))
  i=j+1
 # start/end indexes excluding confirmed ground run
 boundaries=[]
 for i,j,d in runs: boundaries.append((i,j,"confirmed_ground_dwell"))
 legs=[]; start=0
 for gi,gj,reason in boundaries:
  end=gi-1
  if end>=start and len(pts[start:end+1])>=2: legs.append({"start_index":start,"end_index":end,"split_reason":reason})
  start=gj+1
 if start<len(pts) and len(pts[start:])>=2: legs.append({"start_index":start,"end_index":len(pts)-1,"split_reason":"end_of_trace"})
 return legs

def summarize(points,legs):
 out=[]
 for n,l in enumerate(legs,1):
  p=points[l["start_index"]:l["end_index"]+1]
  out.append({"leg":n,"start_utc":p[0].get("timestamp"),"end_utc":p[-1].get("timestamp"),"point_count":len(p),
   "start_position":[p[0].get("lat"),p[0].get("lon")],"end_position":[p[-1].get("lat"),p[-1].get("lon")],
   "split_reason":l["split_reason"]})
 return out
