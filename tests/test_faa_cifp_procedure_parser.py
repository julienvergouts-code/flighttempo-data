import unittest
from scripts.parse_faa_cifp_procedures import parse_procedure_record

class FaaCifpProcedureRecordTests(unittest.TestCase):
    def fixture(self, code, proc="DEEZZ6", transition="W04L", seq="010", fix=""):
        row = [" "] * 132
        row[0] = "S"
        row[1:3] = list("US")
        row[3:5] = list("AP")
        row[6:10] = list("KJFK")
        row[10:12] = list("K6")
        row[12] = code
        row[13:19] = list(proc)
        row[19] = "4"
        row[20] = "R"
        row[21:26] = list(transition.ljust(5)[:5])
        row[26:29] = list(seq)
        row[29:34] = list(fix.ljust(5)[:5])
        return "".join(row)

    def test_sid_header_fields(self):
        rec = parse_procedure_record(self.fixture("D", fix="PONAE"), 42)
        self.assertEqual(rec["procedureType"], "SID")
        self.assertEqual(rec["airportId"], "KJFK")
        self.assertEqual(rec["procedureIdentifier"], "DEEZZ6")
        self.assertEqual(rec["transitionIdentifier"], "W04L")
        self.assertEqual(rec["sequenceNumber"], 10)
        self.assertEqual(rec["legFixIdentifier"], "PONAE")
        self.assertFalse(rec["rawRecordIncluded"])

    def test_star_and_approach_codes(self):
        self.assertEqual(parse_procedure_record(self.fixture("E", proc="CAMRN5", transition="ALL"), 1)["procedureType"], "STAR")
        self.assertEqual(parse_procedure_record(self.fixture("F", proc="I04L  ", transition=""), 2)["procedureType"], "APPROACH")

    def test_non_procedure_records_ignored(self):
        row = self.fixture("C")
        self.assertIsNone(parse_procedure_record(row, 1))
        row = list(self.fixture("D"))
        row[3:5] = list("AE")
        self.assertIsNone(parse_procedure_record("".join(row), 1))

    def test_bad_record_width_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_procedure_record("short", 1)

if __name__ == "__main__":
    unittest.main()
