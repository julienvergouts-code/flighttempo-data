import csv
import json
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openpyxl import Workbook
from scripts.import_aerosors_tables import FIELDS, decimal_coordinate, listed_cycle, workbook_records, write_csv


class AeroSorsWorkbookTests(unittest.TestCase):
    def make_workbook(self, sheet_name, rows):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = sheet_name
        for row in rows:
            sheet.append(row)
        buffer = BytesIO()
        workbook.save(buffer)
        workbook.close()
        return buffer.getvalue()

    def test_extracts_vor_ndb_rows_and_preserves_raw_fields(self):
        payload = self.make_workbook("VOR NDB", [
            ["Aero.Sors VOR/NDB Table 2611-R1"],
            ["Identifier", "Name", "Type", "Frequency MHz", "Latitude", "Longitude", "Range NM"],
            ["ABC", "ALPHA BRAVO", "VOR-DME", 113.2, 50.1, 4.2, 130],
            ["NDB1", "NDB ONE", "NDB", 350, 49.9, 3.5, 50],
        ])
        rows, info = workbook_records(payload, "vor_ndb")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["ident"], "ABC")
        self.assertEqual(rows[0]["record_status"], "navigation_record")
        self.assertEqual(rows[0]["frequency"], "113.2")
        self.assertEqual(rows[0]["frequency_unit"], "MHz")
        self.assertEqual(rows[0]["latitude_deg"], "50.1")
        self.assertEqual(json.loads(rows[0]["raw_fields_json"])["name"], "ALPHA BRAVO")
        self.assertEqual(info["embeddedCycle"], "2611-R1")

    def test_extracts_ils_rows(self):
        payload = self.make_workbook("ILS", [
            ["ICAO", "Runway", "Localizer ident", "Frequency MHz", "Course deg", "Glide Slope Angle"],
            ["LFPG", "08L", "IPN", 109.5, 88.4, 3.0],
        ])
        rows, _ = workbook_records(payload, "ils")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["airport_icao"], "LFPG")
        self.assertEqual(rows[0]["record_status"], "navigation_record")
        self.assertEqual(rows[0]["runway"], "08L")
        self.assertEqual(rows[0]["ident"], "IPN")
        self.assertEqual(rows[0]["frequency_unit"], "MHz")
        self.assertEqual(rows[0]["course_deg"], "88.4")

    def test_cycle_listing_parser(self):
        page = "<html><a>VOR/NDB table <b>(2611-R1)</b></a><a>ILS table (2611-R1)</a></html>"
        self.assertEqual(listed_cycle(page), "2611-R1")

    def test_coordinate_parser_does_not_guess_dms(self):
        self.assertEqual(decimal_coordinate("N50.1", "lat"), "50.1")
        self.assertEqual(decimal_coordinate("W004.2", "lon"), "-4.2")
        self.assertEqual(decimal_coordinate("N50 10 20", "lat"), "")
        self.assertEqual(decimal_coordinate("E181.0", "lon"), "")

    def test_csv_export_has_fixed_complete_schema(self):
        payload = self.make_workbook("VOR", [
            ["Identifier", "Latitude", "Longitude"],
            ["ABC", 1.0, 2.0],
        ])
        records, _ = workbook_records(payload, "vor_ndb")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.csv"
            metadata = write_csv(path, records, "2611-R1")
            self.assertEqual(metadata["recordCount"], 1)
            self.assertGreater(metadata["sizeBytes"], 0)
            self.assertEqual(len(metadata["sha256"]), 64)
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, FIELDS)
                row = next(reader)
            self.assertEqual(row["source_cycle"], "2611-R1")


if __name__ == "__main__":
    unittest.main()
