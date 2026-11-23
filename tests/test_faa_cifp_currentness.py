import unittest
from datetime import date

from scripts.check_faa_cifp_currentness import build_status, parse_cycles


HTML = """
<table>
<tr><th>Product</th><th>Effective</th><th>Ending</th></tr>
<tr><td>CIFP 261029 (Zip)</td><td>Oct 29, 2026</td><td>Nov 26, 2026</td></tr>
<tr><td>CIFP 261126 (Zip)</td><td>Nov 26, 2026</td><td>Dec 24, 2026</td></tr>
</table>
"""


class FaaCifpCurrentnessTests(unittest.TestCase):
    def test_parses_current_and_next_cycle_from_official_table(self):
        cycles = parse_cycles(HTML)
        self.assertEqual([x["cycleToken"] for x in cycles], ["261029", "261126"])
        self.assertEqual(cycles[1]["effectiveDate"], "2026-11-26")

    def test_marks_packaged_cycle_current_when_next_is_future(self):
        manifest = {"datasets": [
            {"id": "sids", "sourceUrl": "https://aeronav.faa.gov/Upload_313-d/cifp/CIFP_261029.zip", "effectiveDate": "2026-10-29", "expiryDate": "2026-11-26"},
            {"id": "stars", "sourceUrl": "https://aeronav.faa.gov/Upload_313-d/cifp/CIFP_261029.zip", "effectiveDate": "2026-10-29", "expiryDate": "2026-11-26"},
            {"id": "approaches", "sourceUrl": "https://aeronav.faa.gov/Upload_313-d/cifp/CIFP_261029.zip", "effectiveDate": "2026-10-29", "expiryDate": "2026-11-26"},
        ]}
        result = build_status(manifest, parse_cycles(HTML), today=date(2026, 11, 17))
        self.assertEqual(result["status"], "packaged_cycle_current_next_cycle_published")
        self.assertEqual(result["packagedCycle"]["cycleToken"], "261029")

    def test_flags_new_cycle_on_effective_date(self):
        manifest = {"datasets": [
            {"id": "sids", "sourceUrl": "CIFP_261029.zip", "effectiveDate": "2026-10-29", "expiryDate": "2026-11-26"},
            {"id": "stars", "sourceUrl": "CIFP_261029.zip", "effectiveDate": "2026-10-29", "expiryDate": "2026-11-26"},
            {"id": "approaches", "sourceUrl": "CIFP_261029.zip", "effectiveDate": "2026-10-29", "expiryDate": "2026-11-26"},
        ]}
        result = build_status(manifest, parse_cycles(HTML), today=date(2026, 11, 26))
        self.assertEqual(result["status"], "new_cycle_effective_import_required")
        self.assertEqual(result["latestPublishedCycle"]["cycleToken"], "261126")

    def test_flags_expired_packaged_cycle(self):
        manifest = {"datasets": [
            {"id": "sids", "sourceUrl": "CIFP_261029.zip", "effectiveDate": "2026-10-29", "expiryDate": "2026-11-26"},
            {"id": "stars", "sourceUrl": "CIFP_261029.zip", "effectiveDate": "2026-10-29", "expiryDate": "2026-11-26"},
            {"id": "approaches", "sourceUrl": "CIFP_261029.zip", "effectiveDate": "2026-10-29", "expiryDate": "2026-11-26"},
        ]}
        result = build_status(manifest, parse_cycles(HTML), today=date(2026, 11, 27))
        self.assertEqual(result["status"], "stale_update_required")


if __name__ == "__main__":
    unittest.main()
