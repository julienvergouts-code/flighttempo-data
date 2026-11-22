import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import fetch_sia_aixm_fixes as mod


class FetchSiaAixmFixesTests(unittest.TestCase):
    def test_selects_latest_current_or_upcoming_cycle_archive(self):
        hrefs = [
            "export_xml_bd_SIA2026-10-29.zip",
            "export_xml_bd_SIA2026-11-26.zip",
            "export_xml_bd_SIA2027-03-04.zip",
            "readme.pdf",
        ]
        url, effective = mod.select_archive(hrefs, date(2026, 11, 22))
        self.assertEqual(url, "export_xml_bd_SIA2026-11-26.zip")
        self.assertEqual(effective, date(2026, 11, 26))

    def test_rejects_mirror_index_without_a_current_cycle(self):
        with self.assertRaisesRegex(RuntimeError, "observed links.*export_xml_bd_SIA2026-09-03.zip"):
            mod.select_archive(["export_xml_bd_SIA2026-09-03.zip"], date(2026, 11, 22))

    def test_latest_archive_reads_index_then_validates_zip_header(self):
        html = b'<a href="export_xml_bd_SIA2026-11-26.zip">current</a>'
        with patch.object(mod, "fetch", side_effect=[html, b"PK\x03\x04test"]):
            url, effective, archive = mod.latest_archive(today=date(2026, 11, 22))
        self.assertEqual(url, "https://data.cquest.org/dgac/aip/export_xml_bd_SIA2026-11-26.zip")
        self.assertEqual(effective, date(2026, 11, 26))
        self.assertTrue(archive.startswith(b"PK\x03\x04"))

    def test_rejects_non_zip_download(self):
        html = b'<a href="export_xml_bd_SIA2026-11-26.zip">current</a>'
        with patch.object(mod, "fetch", side_effect=[html, b"not a zip"]):
            with self.assertRaisesRegex(RuntimeError, "not a ZIP"):
                mod.latest_archive(today=date(2026, 11, 22))


if __name__ == "__main__":
    unittest.main()
