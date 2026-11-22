import unittest
from scripts.monitor_eurocontrol_fra_sources import DownloadLinkParser, inspect_workbook, parse_dms_coordinate
import io
from openpyxl import Workbook

class TestFraMonitor(unittest.TestCase):
    def test_detect_xlsx_links_and_label(self):
        parser = DownloadLinkParser()
        parser.feed('<a href="/latest.xlsx"> FRA points effective 26 Nov </a><a href="/other.pdf">PDF</a>')
        self.assertEqual(len(parser.links), 1)
        self.assertEqual(parser.links[0]["href"], "/latest.xlsx")
        self.assertIn("26 Nov", parser.links[0]["text"])

    def test_workbook_header_detection_metadata_only(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "FRA points"
        ws.append(["FRA points listing"])
        ws.append(["Point Name", "Latitude", "Longitude", "Availability"])
        ws.append(["ABC", 51.1, 4.2, "H24"])
        buffer = io.BytesIO()
        wb.save(buffer)
        result = inspect_workbook(buffer.getvalue())
        self.assertEqual(result["sheetCount"], 1)
        sheet = result["sheets"][0]
        self.assertEqual(sheet["maxRows"], 3)
        self.assertEqual(sheet["candidateHeaderRows"][0]["row"], 2)
        self.assertNotIn("records", sheet)

    def test_parse_dms_and_decimal_coordinates(self):
        self.assertAlmostEqual(parse_dms_coordinate('N510000', 'lat'), 51.0)
        self.assertAlmostEqual(parse_dms_coordinate('W0013000', 'lon'), -1.5)
        self.assertAlmostEqual(parse_dms_coordinate('S 33 30 00', 'lat'), -33.5)
        self.assertAlmostEqual(parse_dms_coordinate('4.25', 'lon'), 4.25)
        self.assertIsNone(parse_dms_coordinate('N916000', 'lat'))

    def test_header_detection_accepts_availability_and_fra_columns(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Point", "FRA", "Coordinates", "Availability"])
        ws.append(["ABCD", "North", "N5100 E00400", "H24"])
        buffer = io.BytesIO()
        wb.save(buffer)
        sheet = inspect_workbook(buffer.getvalue())["sheets"][0]
        self.assertEqual(sheet["candidateHeaderRows"][0]["row"], 1)

if __name__ == "__main__":
    unittest.main()
