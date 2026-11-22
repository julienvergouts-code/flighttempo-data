import sys, tempfile, unittest, csv, io, hashlib, json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import register_faa_vfr_points_manifest as mod

class Tests(unittest.TestCase):
    def test_metadata_comment_skipped_and_schema_counted(self):
        raw=b"#version=1,generated_utc=2026-11-21T23:18:04Z\nicao,code,name,lat,lon,role,source,updated_date\n,VPABC,VPABC,38.8,-77.0,VFR_WAYPOINT,FAA,2026-11-26\n"
        rows=mod.parse_rows(raw)
        self.assertEqual(len(rows),1)
    def test_invalid_coordinate_rejected(self):
        raw=b"icao,code,name,lat,lon,role,source,updated_date\n,VPABC,VPABC,91,-77,VRP,FAA,2026-11-26\n"
        with self.assertRaises(ValueError): mod.parse_rows(raw)
    def test_wrong_source_rejected(self):
        raw=b"icao,code,name,lat,lon,role,source,updated_date\n,VPABC,VPABC,38.8,-77.0,VRP,OFMA,2026-11-26\n"
        with self.assertRaises(ValueError): mod.parse_rows(raw)
    def test_wrong_role_rejected(self):
        raw=b"icao,code,name,lat,lon,role,source,updated_date\n,VPABC,VPABC,38.8,-77.0,VRP,FAA,2026-11-26\n"
        with self.assertRaisesRegex(ValueError,"VFR waypoint role"):
            mod.parse_rows(raw)
    def test_non_vfr_identifier_rejected(self):
        raw=b"icao,code,name,lat,lon,role,source,updated_date\n,ABC,ABC,38.8,-77.0,VRP,FAA,2026-11-26\n"
        with self.assertRaisesRegex(ValueError,"VFR waypoint identifier"):
            mod.parse_rows(raw)
    def test_registration_publishes_small_reference_only_download_with_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            csv_path=root/"vfr_points.csv"
            meta_path=root/"vfr_points_meta.json"
            manifest_path=root/"navigation_manifest.json"
            raw=(b"#version=1,generated_utc=2026-11-21T23:18:04Z\n"
                 b"icao,code,name,lat,lon,role,source,updated_date\n"
                 b",VPABC,VPABC,38.8,-77.0,VFR_WAYPOINT,FAA,2026-11-26\n")
            csv_path.write_bytes(raw)
            meta_path.write_text(json.dumps({"generated_utc":"2026-11-21T23:18:04Z"}),encoding="utf-8")
            manifest_path.write_text(json.dumps({"datasets":[],"statistics":{},"dataSources":[]}),encoding="utf-8")
            with patch.object(mod,"CSV_PATH",csv_path), patch.object(mod,"META_PATH",meta_path), patch.object(mod,"MANIFEST_PATH",manifest_path):
                dataset=mod.register()
            self.assertTrue(dataset["available"])
            self.assertEqual(dataset["recordCount"],1)
            self.assertEqual(dataset["sizeBytes"],len(raw))
            self.assertEqual(dataset["sha256"],hashlib.sha256(raw).hexdigest())
            self.assertEqual(dataset["downloadPurpose"],"reference_only")
            self.assertFalse(dataset["operationallyAvailable"])
            self.assertEqual(dataset["coverage"],"United States NASR VFR waypoints (VP-prefixed FIX records; visual-checkpoint association varies)")
            self.assertEqual(dataset["licenseStatus"],"public_domain")
            self.assertTrue(json.loads(manifest_path.read_text(encoding="utf-8"))["capabilities"]["faaVfrReportingPoints"])
if __name__=="__main__": unittest.main()
