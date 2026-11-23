import tempfile
import unittest
import zipfile
from pathlib import Path
from scripts.audit_ofmx_features import audit_path, inventory_xml

class OfmxAuditTests(unittest.TestCase):
    def test_xml_inventory_counts_tags_and_namespace(self):
        report = inventory_xml(b'<root xmlns="urn:test"><Airport><Runway/></Airport><Airspace/></root>')
        self.assertEqual(report["root"], "root")
        self.assertEqual(report["namespace"], "urn:test")
        self.assertEqual(report["tagCounts"]["Runway"], 1)
        self.assertEqual(report["tagCounts"]["Airspace"], 1)

    def test_rejects_dtd(self):
        with self.assertRaises(ValueError):
            inventory_xml(b'<!DOCTYPE root [<!ENTITY x "bad">]><root>&x;</root>')

    def test_zip_audit_hashes_and_reports_xml(self):
        with tempfile.TemporaryDirectory() as td:
            zpath = Path(td) / "sample.zip"
            with zipfile.ZipFile(zpath, "w") as z:
                z.writestr("sample.ofmx", b'<OFMX><Airport/><Airspace/></OFMX>')
                z.writestr("readme.txt", "ignored")
            report = audit_path(zpath)
            self.assertEqual(len(report["memberReports"]), 1)
            self.assertTrue(report["sha256"])
            self.assertEqual(report["memberReports"][0]["tagCounts"]["Airspace"], 1)

if __name__ == "__main__":
    unittest.main()
