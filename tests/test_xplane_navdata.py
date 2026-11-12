import unittest
from collections import defaultdict
from import_xplane_navdata import parse_airways, parse_fixes, parse_navaids, resolve_endpoint


def source(lines, name):
    return {"file_name": name, "records": [(i + 3, line, line.split()) for i, line in enumerate(lines)]}


class XPlaneNavdataTests(unittest.TestCase):
    def test_fix_parser_uses_actual_xpfix_field_layout(self):
        fixes, rejected = parse_fixes(source([
            "50.10000000 4.20000000 ABCDE ENRT EB",
            "50.20000000 4.30000000 TERM1 EBBR EB",
        ], "earth_fix.dat"))
        self.assertEqual(rejected, 0)
        self.assertEqual(len(fixes), 2)
        self.assertEqual(fixes[0]["scope"], "enroute")
        self.assertEqual(fixes[0]["entity_type"], "FIX")
        self.assertEqual(fixes[0]["region_code"], "EB")
        self.assertEqual(fixes[1]["scope"], "terminal")

    def test_navaid_parser_preserves_navaid_types_and_procedure_facilities(self):
        navaids, rejected = parse_navaids(source([
            "2 50.10000000 4.20000000 300 350 50 0.0 NDB1 ENRT EB TEST NDB",
            "3 50.30000000 4.40000000 350 11340 130 2.5 VOR1 ENRT EB TEST VORTAC",
            "4 50.50000000 4.60000000 200 11030 25 180.0 IABC EBBR EB 25 ILS-cat-I",
        ], "earth_nav.dat"))
        self.assertEqual(rejected, 0)
        self.assertEqual([n["facility_type"] for n in navaids],
                         ["NDB", "VHF_NAVAID", "ILS_LOCALIZER"])
        self.assertEqual(navaids[0]["frequency_unit"], "kHz")
        self.assertEqual(navaids[1]["facility_subtype"], "VORTAC")
        self.assertEqual(navaids[2]["scope"], "terminal")
        self.assertEqual(navaids[2]["runway_ident"], "25")

    def test_airway_type_direction_level_altitude_and_coordinates(self):
        fixes, _ = parse_fixes(source([
            "50.10000000 4.20000000 FIX01 ENRT EB",
        ], "earth_fix.dat"))
        navaids, _ = parse_navaids(source([
            "3 50.30000000 4.40000000 350 11340 130 2.5 VOR1 ENRT EB TEST VOR",
        ], "earth_nav.dat"))
        airways, rejected, unresolved, ambiguous = parse_airways(source([
            "FIX01 EB 11 VOR1 EB 3 F 2 180 450 UQ1",
        ], "earth_awy.dat"), fixes, navaids)
        self.assertEqual((rejected, unresolved, ambiguous), (0, 0, 0))
        row = airways[0]
        self.assertEqual(row["from_type"], "FIX")
        self.assertEqual(row["to_type"], "VHF_NAVAID")
        self.assertEqual(row["direction_restriction"], "F")
        self.assertEqual(row["level_classification"], "high")
        self.assertEqual(row["minimum_altitude_ft"], 18000)
        self.assertEqual(row["maximum_altitude_ft"], 45000)
        self.assertEqual(row["to_resolution"], "resolved")
        self.assertEqual(row["to_latitude"], "50.30000000")

    def test_duplicate_fix_identifiers_are_ambiguous_not_guessed(self):
        duplicates = [
            {"ident": "DUP", "region_code": "EB", "latitude": "50.0", "longitude": "4.0"},
            {"ident": "DUP", "region_code": "EB", "latitude": "51.0", "longitude": "5.0"},
        ]
        result = resolve_endpoint("DUP", "EB", "11", {("DUP", "EB"): duplicates}, {})
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["latitude"], "")

    def test_vhf_endpoint_does_not_resolve_against_fix_identifier(self):
        fixes_index = {("SAME", "EB"): [{"latitude": "50", "longitude": "4"}]}
        result = resolve_endpoint("SAME", "EB", "3", fixes_index, {})
        self.assertEqual(result["status"], "unresolved")

    def test_unknown_endpoint_types_remain_explicit(self):
        result = resolve_endpoint("ABC", "EB", "99", {}, {})
        self.assertEqual(result["status"], "unsupported_type")


if __name__ == "__main__":
    unittest.main()
