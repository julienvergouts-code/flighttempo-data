import unittest
from scripts.audit_navaid_frequencies import audit_rows

class NavaidFrequencyAuditTests(unittest.TestCase):
    def test_valid_vor_and_ndb_are_not_flagged(self):
        rows = [
            {"ident":"BUB","type":"VOR","frequency_khz":"114600","latitude_deg":"50","longitude_deg":"4"},
            {"ident":"ABC","type":"NDB","frequency_khz":"350","latitude_deg":"51","longitude_deg":"2"},
        ]
        report = audit_rows(rows)
        self.assertEqual(report["anomalyCount"], 0)
        self.assertEqual(report["recordsAudited"], 2)

    def test_out_of_range_frequency_is_reported_not_mutated(self):
        rows = [{"ident":"TEST","type":"VOR","frequency_khz":"1140000","latitude_deg":"50","longitude_deg":"4"}]
        report = audit_rows(rows)
        self.assertEqual(report["anomalyCount"], 1)
        self.assertEqual(report["anomalies"][0]["issue"], "frequency_out_of_range")
        self.assertEqual(rows[0]["frequency_khz"], "1140000")

    def test_missing_frequency_is_flagged_for_known_type(self):
        report = audit_rows([{"ident":"ABC","type":"NDB","frequency_khz":"","latitude_deg":"0","longitude_deg":"0"}])
        self.assertEqual(report["anomalies"][0]["issue"], "missing_frequency")

    def test_unknown_types_are_not_assumed_to_have_vor_ndb_ranges(self):
        report = audit_rows([{"ident":"TAC","type":"TACAN","frequency_khz":"0","latitude_deg":"0","longitude_deg":"0"}])
        self.assertEqual(report["anomalyCount"], 0)

    def test_identical_duplicate_is_counted(self):
        row = {"ident":"ABC","type":"VOR","frequency_khz":"113000","latitude_deg":"1","longitude_deg":"2"}
        report = audit_rows([row, dict(row)])
        self.assertEqual(report["identicalDuplicateRecords"], 1)

if __name__ == "__main__":
    unittest.main()
