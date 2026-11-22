#!/usr/bin/env python3
"""Register OFMA OFMX VFR points in the shared navigation manifest."""
import csv, hashlib, json
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1]
CSV=ROOT/"data/ofma_ofmx_vfr_points.csv"
META=ROOT/"data/ofma_ofmx_vfr_points_meta.json"
MAN=ROOT/"navigation_manifest.json"
ID="ofma_ofmx_vfr_reference_points"
URL="https://raw.githubusercontent.com/julienvergouts-code/flighttempo-data/main/data/ofma_ofmx_vfr_points.csv"

def register():
    raw=CSV.read_bytes()
    meta=json.loads(META.read_text(encoding="utf-8"))
    rows=list(csv.DictReader(line for line in raw.decode("utf-8-sig").splitlines() if not line.startswith("#version")))
    if not rows or len(rows)!=meta.get("count"): raise ValueError("OFMA OFMX count mismatch or empty dataset")
    if any(row.get("source")!="OFMA" or row.get("license")!="OFMA_GUL" for row in rows):
        raise ValueError("source/licence validation failed")
    sources=meta.get("sources",[])
    expected_regions={item.get("region") for item in sources}
    if len(expected_regions)!=len(sources) or expected_regions!=set(meta.get("regions",[])):
        raise ValueError("OFMA source region metadata is incomplete or inconsistent")
    if any(not item.get("downloadUrl","").startswith("https://snapshots.openflightmaps.org/live/") for item in sources):
        raise ValueError("non-official OFMA snapshot URL in source metadata")
    coverage=f"{len(sources)} official OFMA regions ({', '.join(sorted(expected_regions))}); regional coverage only, not worldwide geographic coverage; VFR-designated points."
    manifest=json.loads(MAN.read_text(encoding="utf-8"))
    dataset={
        "id":ID,"path":"data/ofma_ofmx_vfr_points.csv","downloadUrl":URL,
        "available":True,"recordCount":len(rows),"sizeBytes":len(raw),
        "sha256":hashlib.sha256(raw).hexdigest(),"sourceProvider":"OpenFlightMaps Association",
        "sourceUrl":"https://openflightmaps.org/","coverage":coverage,
        "license":"OFMA General Users License","licenseStatus":"commercial_use_permitted_subject_to_OFMA_GUL",
        "attribution":"Contains information from the open flightmaps database, see www.openflightmaps.org",
        "licenseUrl":"https://www.openflightmaps.org/live/downloads/20150306-GUL.pdf",
        "commercialUseAllowed":True,
        "licenseConditions":[
            "Preserve OFMA attribution in every use or redistribution.",
            "Communicate any alterations to OFMA within 15 days.",
            "If the consuming app lets users alter OFMA data, provide the direct OFMA contributor interface required by GUL section 4.4."
        ],
        "dataCycle":meta.get("airac"),"effectiveDate":None,
        "provenanceVerification":"official_OFMA_publication_service_and_snapshot",
        "downloadPurpose":"reference_only","operationallyAvailable":False,"status":"reference_dataset"
    }
    datasets=manifest.setdefault("datasets",[])
    old=next((item for item in datasets if item.get("id")==ID),None)
    manifest["datasets"]=[item for item in datasets if item.get("id")!=ID]+[dataset]
    statistics=manifest.setdefault("statistics",{})
    old_count=statistics.get("ofmaOfmxVfrReferencePoints")
    statistics["ofmaOfmxVfrReferencePoints"]=len(rows)
    manifest.setdefault("capabilities",{})["ofmaOfmxVfrReferencePoints"]=True
    if old!=dataset or old_count!=len(rows): manifest["generatedAtUtc"]=datetime.now(timezone.utc).isoformat()
    MAN.write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    print(f"Registered {len(rows)} OFMA OFMX VFR points from {len(sources)} regional packages")

if __name__=="__main__": register()
