import sys, tempfile, unittest, csv, io
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import register_faa_vfr_points_manifest as mod

class Tests(unittest.TestCase):
    def test_metadata_comment_skipped_and_schema_counted(self):
        raw=b"#version=1,generated_utc=2026-11-21T23:18:04Z\nicao,code,name,lat,lon,role,source,updated_date\n,VPABC,VPABC,38.8,-77.0,VRP,FAA,2026-11-26\n"
        rows=mod.parse_rows(raw)
        self.assertEqual(len(rows),1)
    def test_invalid_coordinate_rejected(self):
        raw=b"icao,code,name,lat,lon,role,source,updated_date\n,VPABC,VPABC,91,-77,VRP,FAA,2026-11-26\n"
        with self.assertRaises(ValueError): mod.parse_rows(raw)
    def test_wrong_source_rejected(self):
        raw=b"icao,code,name,lat,lon,role,source,updated_date\n,VPABC,VPABC,38.8,-77.0,VRP,OFMA,2026-11-26\n"
        with self.assertRaises(ValueError): mod.parse_rows(raw)

    def test_registered_dataset_expires_at_end_of_the_cycle(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            (td/"vfr.csv").write_bytes(b"#version=1,generated_utc=2026-11-21T23:18:04Z\nicao,code,name,lat,lon,role,source,updated_date\n,VPABC,VPABC,38.8,-77.0,VRP,FAA,2026-11-26\n")
            (td/"meta.json").write_text('{"generated_utc":"2026-11-21T23:18:04Z"}')
            (td/"manifest.json").write_text('{"datasets":[],"statistics":{},"dataSources":[]}')
            saved=(mod.CSV_PATH,mod.META_PATH,mod.MANIFEST_PATH)
            mod.CSV_PATH,mod.META_PATH,mod.MANIFEST_PATH=td/"vfr.csv",td/"meta.json",td/"manifest.json"
            try:
                dataset=mod.register()
            finally:
                mod.CSV_PATH,mod.META_PATH,mod.MANIFEST_PATH=saved
        self.assertEqual(dataset["effectiveDate"],"2026-11-26")
        self.assertEqual(dataset["expiryDate"],"2026-12-23")

if __name__=="__main__": unittest.main()
