import gzip
import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

# The implementation lives in scripts/ so add that directory explicitly when
# tests are launched through "python -m unittest discover -s tests".
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_xplane_navdata import (
    import_navdata,
    locate_source_files,
    parse_airways,
    parse_fixes,
    parse_navaids,
    read_source_file,
    resolve_endpoint,
    validate_source_cycles,
)


def source(lines, name, version="1101"):
    return {
        "file_name": name,
        "format_version": version,
        "records": [(i + 3, line, line.split()) for i, line in enumerate(lines)],
    }


class XPlaneNavdataTests(unittest.TestCase):
    def test_airways_are_not_required_or_imported_by_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_dir = root / "source"
            source_dir.mkdir()
            header_fix = "XPFIX 1101 Version - data cycle 2026 build 20261101"
            header_nav = "XPNAV 1100 Version - data cycle 2026 build 20261101"
            (source_dir / "earth_fix.dat").write_text(
                "I\n" + header_fix + "\n"
                + "50.10000000 4.20000000 ABCDE ENRT EB 4530263\n"
                + "99\n",
                encoding="utf-8",
            )
            (source_dir / "earth_nav.dat").write_text(
                "I\n" + header_nav + "\n"
                + "3 50.30000000 4.40000000 350 11340 130 2.5 VOR1 ENRT EB TEST VOR\n"
                + "99\n",
                encoding="utf-8",
            )
            # An airway file may exist in a source bundle, but the MVP must
            # ignore it unless the operator explicitly opts in.
            (source_dir / "earth_awy.dat").write_text(
                "I\nXPAWY 1100 Version - data cycle 2026 build 20261101\n"
                + "FIX01 EB 11 VOR1 EB 3 F 2 180 450 UQ1\n99\n",
                encoding="utf-8",
            )
            (source_dir / "source-manifest.json").write_text(json.dumps({
                "provider": "Unit test only",
                "license": "Test fixture licence",
                "redistributable": True,
            }), encoding="utf-8")

            located, missing = locate_source_files(source_dir)
            self.assertEqual(missing, [])
            self.assertEqual(set(located), {"fixes", "navaids"})

            manifest_path = root / "navigation_manifest.json"
            result = import_navdata(source_dir, root, manifest_path)
            self.assertEqual(result["status"], "imported")
            self.assertFalse(result["airwaysIncluded"])
            self.assertEqual(result["airwaySegments"], 0)
            self.assertTrue((root / "navigation/waypoints/flightgear_fixes.csv").is_file())
            self.assertTrue((root / "navigation/navaids/flightgear_navaids.csv").is_file())
            self.assertFalse((root / "navigation/airways/flightgear_airway_segments.csv").exists())

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["capabilities"]["independentWaypoints"])
            self.assertTrue(manifest["capabilities"]["flightgearNavaids"])
            self.assertFalse(manifest["capabilities"]["publishedAirways"])
            self.assertEqual(manifest["statistics"]["airwaySegments"], 0)

    def test_fix_parser_uses_actual_xpfix_field_layout(self):
        fixes, rejected = parse_fixes(source([
            "50.10000000 4.20000000 ABCDE ENRT EB 4530263",
            "50.20000000 4.30000000 TERM1 EBBR EB 4530263",
        ], "earth_fix.dat"))
        self.assertEqual(rejected, 0)
        self.assertEqual(len(fixes), 2)
        self.assertEqual(fixes[0]["scope"], "enroute")
        self.assertEqual(fixes[0]["entity_type"], "FIX")
        self.assertEqual(fixes[0]["region_code"], "EB")
        self.assertEqual(fixes[0]["waypoint_type_code"], "4530263")
        self.assertEqual(fixes[0]["printed_name"], "ABCDE")
        self.assertEqual(fixes[1]["scope"], "terminal")

    def test_fix_1200_parser_keeps_printed_name_with_spaces(self):
        fixes, rejected = parse_fixes(source([
            "43.740277778 -89.224722222 VPPLK ENRT K5 2105430 PUCKAWAY LAKE",
        ], "earth_fix.dat", version="1200"))
        self.assertEqual(rejected, 0)
        self.assertEqual(fixes[0]["waypoint_type_code"], "2105430")
        self.assertEqual(fixes[0]["printed_name"], "PUCKAWAY LAKE")

    def test_fix_parser_rejects_missing_published_waypoint_type(self):
        fixes, rejected = parse_fixes(source([
            "50.10000000 4.20000000 ABCDE ENRT EB",
        ], "earth_fix.dat", version="1101"))
        self.assertEqual(fixes, [])
        self.assertEqual(rejected, 1)

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
            "50.10000000 4.20000000 FIX01 ENRT EB 4530263",
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

    def test_legacy_fix_600_keeps_unknown_metadata_unknown(self):
        fixes, rejected = parse_fixes(source([
            "50.10000000 4.20000000 FIX01",
        ], "fix.dat", version="600"))
        self.assertEqual(rejected, 0)
        self.assertEqual(len(fixes), 1)
        self.assertEqual(fixes[0]["ident"], "FIX01")
        self.assertEqual(fixes[0]["scope"], "unknown")
        self.assertEqual(fixes[0]["region_code"], "")
        self.assertEqual(fixes[0]["waypoint_type_code"], "")

    def test_legacy_awy_640_preserves_source_coordinates_without_fake_types(self):
        airways, rejected, unresolved, ambiguous = parse_airways(source([
            "FIX01 50.10000000 4.20000000 FIX02 51.10000000 5.20000000 1 045 180 UL9",
        ], "awy.dat", version="640"), [], [])
        self.assertEqual((rejected, unresolved, ambiguous), (0, 0, 0))
        row = airways[0]
        self.assertEqual(row["from_resolution"], "source_coordinates")
        self.assertEqual(row["to_resolution"], "source_coordinates")
        self.assertEqual(row["from_type"], "UNKNOWN")
        self.assertEqual(row["level_classification"], "unknown")
        self.assertEqual(row["minimum_altitude_ft"], 4500)
        self.assertEqual(row["maximum_altitude_ft"], 18000)
        self.assertEqual(row["airway_names"], "UL9")

    def test_gzip_source_is_decoded_and_full_cycle_token_is_preserved(self):
        payload = "\n".join([
            "I",
            "600 Version - data cycle 2016.10, build 20161559",
            "",
            "50.10000000 4.20000000 FIX01",
            "99",
            "",
        ]).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fix.dat.gz"
            path.write_bytes(gzip.compress(payload))
            parsed = read_source_file(path, "fixes")
        self.assertEqual(parsed["format_version"], "600")
        self.assertEqual(parsed["data_cycle"], "2016.10")
        self.assertEqual(parsed["compression"], "gzip")
        self.assertEqual(len(parsed["records"]), 1)
        self.assertEqual(parsed["records"][0][2][2], "FIX01")
        self.assertEqual(parsed["payload_sha256"], hashlib.sha256(payload).hexdigest())

    def test_source_cycle_validation_preserves_full_tokens_and_rejects_mismatch(self):
        coherent = {
            "fixes": {"data_cycle": "2016.10"},
            "navaids": {"data_cycle": "2016.10"},
            "airways": {"data_cycle": "2016.10"},
        }
        self.assertEqual(validate_source_cycles(coherent), "2016.10")

        mismatched = {
            "fixes": {"data_cycle": "201610"},
            "navaids": {"data_cycle": "1611"},
            "airways": {"data_cycle": "2013.10"},
        }
        with self.assertRaisesRegex(ValueError, "Mixed or missing cycles"):
            validate_source_cycles(mismatched)

    def test_source_cycle_validation_rejects_unknown_cycle(self):
        sources = {
            "fixes": {"data_cycle": "2016.10"},
            "navaids": {"data_cycle": "unknown"},
            "airways": {"data_cycle": "2016.10"},
        }
        with self.assertRaisesRegex(ValueError, "Mixed or missing cycles"):
            validate_source_cycles(sources)


if __name__ == "__main__":
    unittest.main()
