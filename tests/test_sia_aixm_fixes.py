import tempfile
import unittest
from pathlib import Path

from scripts.import_sia_aixm_fixes import extract_points, parse_aixm_coordinate


class SiaAixmFixImporterTests(unittest.TestCase):
    def test_coordinate_conversion_handles_latitude_and_longitude_formats(self):
        self.assertEqual(parse_aixm_coordinate("464000.00N", "lat"), "46.66666667")
        self.assertEqual(parse_aixm_coordinate("0060711.00E", "lon"), "6.11972222")
        self.assertEqual(parse_aixm_coordinate("443227N", "lat"), "44.54083333")
        self.assertEqual(parse_aixm_coordinate("0431636.09W", "lon"), "-43.27669167")

    def test_rejects_invalid_or_out_of_range_coordinate(self):
        for value, axis in (("915959N", "lat"), ("0066060E", "lon"), ("bad", "lat")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_aixm_coordinate(value, axis)

    def test_extracts_only_wgs84_dpn_and_retains_duplicate_identifiers(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <AIXM-Snapshot version="4.5">
          <Dpn>
            <DpnUid mid="1">
              <codeId>DINOX</codeId>
              <geoLat>464000.00N</geoLat>
              <geoLong>0060711.00E</geoLong>
            </DpnUid>
            <codeDatum>WGE</codeDatum>
            <codeType>ICAO</codeType>
            <txtName>DINOX</txtName>
          </Dpn>
          <Dpn>
            <DpnUid mid="2">
              <codeId>DUP</codeId>
              <geoLat>443227N</geoLat>
              <geoLong>0035740.96E</geoLong>
            </DpnUid>
            <codeDatum>WGS84</codeDatum>
            <codeType>OTHER</codeType>
          </Dpn>
          <Dpn>
            <DpnUid mid="3">
              <codeId>DUP</codeId>
              <geoLat>450000N</geoLat>
              <geoLong>0040000E</geoLong>
            </DpnUid>
            <codeDatum>WGE</codeDatum>
            <codeType>OTHER</codeType>
          </Dpn>
          <Dpn>
            <DpnUid mid="4">
              <codeId>LOCAL</codeId>
              <geoLat>450000N</geoLat>
              <geoLong>0040000E</geoLong>
            </DpnUid>
            <codeDatum>UNKNOWN</codeDatum>
            <codeType>OTHER</codeType>
          </Dpn>
        </AIXM-Snapshot>
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.xml"
            path.write_text(xml, encoding="utf-8")
            points, digest, member = extract_points(path)

        self.assertEqual(len(points), 3)
        self.assertEqual(digest, points[0]["source_sha256"])
        self.assertEqual(member, "sample.xml")
        self.assertEqual(points[0]["ident"], "DINOX")
        self.assertEqual(points[0]["latitude"], "46")
        self.assertEqual(points[0]["longitude"], "6.11972222")
        self.assertEqual(points[0]["datum"], "WGS84")
        self.assertEqual([p["ident"] for p in points].count("DUP"), 2)
        self.assertNotIn("LOCAL", [p["ident"] for p in points])


if __name__ == "__main__":
    unittest.main()
