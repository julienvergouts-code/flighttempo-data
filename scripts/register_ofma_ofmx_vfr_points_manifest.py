#!/usr/bin/env python3
"""Register OFMA OFMX-derived VFR reference points in the navigation manifest."""
import csv,hashlib,json
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];CSV=ROOT/"data/ofma_ofmx_vfr_points.csv";META=ROOT/"data/ofma_ofmx_vfr_points_meta.json";MAN=ROOT/"navigation_manifest.json"
ID="ofma_ofmx_vfr_reference_points";URL="https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/data/ofma_ofmx_vfr_points.csv"
def register():
 raw=CSV.read_bytes();meta=json.loads(META.read_text());rows=list(csv.DictReader(line for line in raw.decode("utf-8-sig").splitlines() if not line.startswith("#version")))
 if not rows or len(rows)!=meta.get("count"):raise ValueError("OFMA OFMX count mismatch or empty dataset")
 if any(x.get("source")!="OFMA" or x.get("license")!="OFMA_GUL" for x in rows):raise ValueError("source/licence validation failed")
 m=json.loads(MAN.read_text());d={"id":ID,"path":"data/ofma_ofmx_vfr_points.csv","downloadUrl":URL,"available":True,"recordCount":len(rows),"sizeBytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"sourceProvider":"OpenFlightMaps Association","sourceUrl":"https://openflightmaps.org/","coverage":"EB Belgium, ED Germany, EH Netherlands; VFR designated points only","license":"OFMA General Users License","licenseStatus":"GUL_commercial_use_subject_to_conditions","attribution":"OpenFlightMaps Association (OFMA)","dataCycle":meta.get("airac"),"effectiveDate":None,"provenanceVerification":"official_OFMA_snapshot_endpoint","downloadPurpose":"reference_only","operationallyAvailable":False,"status":"regional_reference_dataset"}
 ds=m.setdefault("datasets",[]);old=next((x for x in ds if x.get("id")==ID),None);ds=[x for x in ds if x.get("id")!=ID];ds.append(d);m["datasets"]=ds
 stats=m.setdefault("statistics",{});old_count=stats.get("ofmaOfmxVfrReferencePoints");stats["ofmaOfmxVfrReferencePoints"]=len(rows);m.setdefault("capabilities",{})["ofmaOfmxVfrReferencePoints"]=True
 if old!=d or old_count!=len(rows):m["generatedAtUtc"]=datetime.now(timezone.utc).isoformat()
 MAN.write_text(json.dumps(m,indent=2)+"\n");print(f"Registered {len(rows)} OFMA OFMX VFR points")
if __name__=="__main__":register()
