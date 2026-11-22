#!/usr/bin/env python3
"""Register the FAA VFR reporting-point CSV in the app navigation manifest."""
from __future__ import annotations
import csv, hashlib, json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CSV_PATH=ROOT/"data/vfr_points.csv"
META_PATH=ROOT/"data/vfr_points_meta.json"
MANIFEST_PATH=ROOT/"navigation_manifest.json"
DATASET_ID="faa_vfr_reporting_points"
DOWNLOAD_URL="https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/data/vfr_points.csv"
SOURCE_URL="https://www.faa.gov/air_traffic/flight_info/aeronav/Aero_Data/NASR_Subscription/"

def parse_rows(raw:bytes):
    text=raw.decode("utf-8-sig")
    reader=csv.DictReader(line for line in text.splitlines() if not line.lstrip().startswith("#version"))
    rows=list(reader)
    required={"icao","code","name","lat","lon","role","source","updated_date"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError(f"VFR CSV schema missing required columns: {required-set(reader.fieldnames or [])}")
    if not rows: raise ValueError("VFR CSV has no data records")
    for row in rows:
        lat,lon=float(row["lat"]),float(row["lon"])
        if not (-90<=lat<=90 and -180<=lon<=180) or (lat==0 and lon==0):
            raise ValueError(f"Invalid coordinate for point {row.get('code')}")
        if row["source"]!="FAA": raise ValueError(f"Unexpected source in FAA dataset: {row['source']}")
    return rows

def register():
    raw=CSV_PATH.read_bytes();rows=parse_rows(raw)
    meta=json.loads(META_PATH.read_text(encoding="utf-8"))
    manifest=json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    updated=max((r["updated_date"] for r in rows),default="")
    generated=meta.get("generated_utc","")
    if not generated: raise ValueError("VFR metadata has no generated_utc timestamp")
    dataset={
        "id":DATASET_ID,"path":"data/vfr_points.csv","downloadUrl":DOWNLOAD_URL,
        "available":True,"recordCount":len(rows),"sizeBytes":len(raw),
        "sha256":hashlib.sha256(raw).hexdigest(),
        "sourceProvider":"FAA Aeronautical Information Services / NASR FIX",
        "sourceUrl":SOURCE_URL,
        "coverage":"United States NASR VFR reporting points (VP-prefixed FIX records)",
        "sourceTag":f"FAA_NASR_FIX_{updated}",
        "license":"US Government public-domain data",
        "licenseStatus":"public_domain","dataCycle":updated,
        "effectiveDate":updated,"expiryDate":"",
        "provenanceVerification":"source_snapshot",
        "downloadPurpose":"reference_only","operationallyAvailable":False,
        "status":"present_reference_dataset"
    }
    datasets=manifest.setdefault("datasets",[])
    found=[i for i,d in enumerate(datasets) if d.get("id")==DATASET_ID]
    if len(found)>1: raise ValueError(f"Duplicate manifest dataset id: {DATASET_ID}")
    changed=False
    if found:
        if datasets[found[0]]!=dataset:
            datasets[found[0]]=dataset;changed=True
    else:
        datasets.append(dataset);changed=True
    stats=manifest.setdefault("statistics",{})
    if stats.get("faaVfrReportingPoints")!=len(rows):
        stats["faaVfrReportingPoints"]=len(rows);changed=True
    manifest.setdefault("dataSources",[])
    source={
        "dataset":"faa_vfr_reporting_points","url":SOURCE_URL,"provider":"FAA Aeronautical Information Services",
        "license":"US Government public-domain data","downloadedAt":generated,
        "sizeBytes":len(raw),"sha256":dataset["sha256"],"recordCount":len(rows)
    }
    old=[i for i,d in enumerate(manifest["dataSources"]) if d.get("dataset")=="faa_vfr_reporting_points"]
    if len(old)>1: raise ValueError("Duplicate VFR dataSources metadata entries")
    if old:
        if manifest["dataSources"][old[0]]!=source:
            manifest["dataSources"][old[0]]=source;changed=True
    else:
        manifest["dataSources"].append(source);changed=True
    if changed:
        manifest["generatedAtUtc"]=datetime.now(timezone.utc).isoformat()
        MANIFEST_PATH.write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    else:
        print("Manifest VFR entry already current; no changes.")
    print(f"Registered {len(rows)} FAA VFR reporting points; {len(raw)} bytes; sha256={dataset['sha256']}; source date={updated}")
    return dataset

if __name__=="__main__": register()
