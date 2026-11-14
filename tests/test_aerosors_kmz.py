import csv
import json
import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.import_aerosors_kmz import FIELDS, extract_kmz, listed_cycle, write_csv


class AeroSorsKmlTests(unittest.TestCase):
    def kmz(self, kml):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("doc.kml", kml)
        return buffer.getvalue()

    def test_extracts_navaid_point_and_extended_data(self):
        kml = '''<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><Folder><name>VOR</name><Placemark><name>ABC</name><ExtendedData><Data name="identifier"><value>ABC</value></Data><Data name="frequency_mhz"><value>113.20</value></Data><Data name="type"><value>VOR-DME</value></Data></ExtendedData><Point><coordinates>4.2,50.1,100</coordinates></Point></Placemark></Folder></Document></kml>'''
        rows, info = extract_kmz(self.kmz(kml), "NAVAID", "GENavaids.kmz", "2611-R1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ident"], "ABC")
        self.assertEqual(rows[0]["latitude_deg"], "50.1")
        self.assertEqual(rows[0]["longitude_deg"], "4.2")
        self.assertEqual(rows[0]["altitude_m"], "100")
        self.assertEqual(rows[0]["source_folder"], "VOR")
        self.assertEqual(json.loads(rows[0]["extended_data_json"])["frequency_mhz"], "113.20")
        self.assertEqual(info["placemarkCount"], 1)
        self.assertEqual(info["coordinateCount"], 1)

    def test_preserves_metadata_only_placemarks(self):
        kml = '''<kml><Document><Placemark><name>Airport label</name><description>Unplaced item</description></Placemark></Document></kml>'''
        rows, info = extract_kmz(self.kmz(kml), "AIRPORT", "GEAirports.kmz", "2611-R1")
        self.assertEqual(rows[0]["record_status"], "metadata_only")
        self.assertEqual(rows[0]["name"], "Airport label")
        self.assertEqual(rows[0]["description"], "Unplaced item")
        self.assertEqual(info["pointRecordCount"], 0)

    def test_multiple_point_coordinates(self):
        kml = '''<kml><Document><Placemark><name>Cluster</name><MultiGeometry><Point><coordinates>1,2,0 3,4,0</coordinates></Point></MultiGeometry></Placemark></Document></kml>'''
        rows, info = extract_kmz(self.kmz(kml), "NAVAID", "x.kmz", "unknown")
        self.assertEqual(len(rows), 2)
        self.assertEqual(info["coordinateCount"], 2)

    def test_cycle_parser(self):
        self.assertEqual(listed_cycle("<p>World FSXP3D package (2611-R1)</p>"), "2611-R1")

    def test_csv_schema_and_counts(self):
        kml = '''<kml><Document><Placemark><name>ABC</name><Point><coordinates>1,2,0</coordinates></Point></Placemark></Document></kml>'''
        rows, _ = extract_kmz(self.kmz(kml), "NAVAID", "x.kmz", "2611-R1")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            stats = write_csv(path, rows)
            self.assertEqual(stats["recordCount"], 1)
            self.assertEqual(stats["pointRecordCount"], 1)
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, FIELDS)
                self.assertEqual(next(reader)["latitude_deg"], "2")


if __name__ == "__main__":
    unittest.main()
