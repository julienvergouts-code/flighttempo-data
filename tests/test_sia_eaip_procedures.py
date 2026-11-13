import unittest

from scripts.import_sia_eaip_procedures import (
    parse_aip_date,
    parse_doc_identity,
    parse_table_rows,
)


class SiaProcedureImporterTests(unittest.TestCase):
    def setUp(self):
        self.sid_header = [
            "RMK Procedure Identification",
            "Path Terminator",
            "Waypoint Identification",
            "Fly Over",
            "Direction MAG (°)",
            "Direction True (°)",
            "Distance (NM)",
            "Turn direction",
            "MNM Altitude (FL or AMSL ft)",
            "MAX Altitude (FL or AMSL ft)",
            "MAX IAS (kt)",
            "Navigation Accuracy (NM)",
        ]

    def test_sid_table_preserves_procedure_groups_and_published_fields(self):
        table = [
            self.sid_header,
            ["BAXIR 7B", "", "", "", "", "", "", "", "", "", "", ""],
            ["RWY26L", "CF", "PG263", "-", "267", "268.4", "-", "-", "-", "-", "-", "1.0"],
            ["RWY26R", "CF", "PG263", "-", "264", "265.3", "-", "-", "-", "-", "-", "1.0"],
            ["-", "TF", "PG264", "Y", "264", "265.2", "4.7", "-", "-", "-", "-", "1.0"],
            ["-", "TF", "BAXIR", "-", "094", "095.6", "12.8", "-", "-", "-", "", "1.0"],
        ]
        fixes = {"PG263": [("49.0000", "2.0000")], "PG264": [("49.0100", "2.0100")]}
        rows = parse_table_rows(
            table,
            airport_icao="LFPG",
            procedure_type="SID",
            source_file="AD_2_LFPG_DATA_SID_RWY26L-26R_RNAV_CODE_02.pdf",
            source_url="https://example.invalid/source.pdf",
            source_document_date="2026-10-01",
            airac_effective_date="2026-10-29",
            source_sha256="abc123",
            fix_index=fixes,
        )
        self.assertEqual(len(rows), 4)
        self.assertEqual({row["procedure_identifier"] for row in rows}, {"BAXIR 7B"})
        self.assertEqual(rows[0]["procedure_selector"], "RWY26L")
        self.assertEqual(rows[1]["procedure_selector"], "RWY26R")
        self.assertEqual(rows[2]["procedure_selector"], "")
        self.assertEqual(rows[2]["fly_over"], "Y")
        self.assertEqual(rows[2]["distance_nm"], "4.7")
        self.assertEqual(rows[0]["fix_resolution"], "unique_source_fix")
        self.assertEqual(rows[0]["fix_latitude"], "49.0000")
        self.assertEqual(rows[3]["fix_resolution"], "not_linked")
        self.assertEqual(rows[3]["maximum_ias_kt"], "")

    def test_approach_table_keeps_leg_sequence_and_vertical_angle(self):
        header = [
            "RMK", "Leg sequence", "Path Terminator",
            "Waypoint Identification", "Fly Over", "Direction MAG (°)",
            "Direction True (°)", "Distance (NM)", "Turn direction",
            "MIN Altitude (FL or AMSL ft)", "MAX Altitude (FL or AMSL ft)",
            "MAX IAS (kt)", "Vertical angle (°) / TCH (ft)",
            "Navigation Accuracy (NM)",
        ]
        table = [
            header,
            ["", "APCH", "TF", "PG650", "-", "-", "-", "-", "-", "5000", "-", "-", "-", "1.0"],
            ["", "APCH", "TF", "RW27R", "Y", "264", "265.7", "3.6", "-", "5000", "5000", "-", "-3.0 / 49", "0.3"],
        ]
        rows = parse_table_rows(
            table,
            airport_icao="LFPG",
            procedure_type="APPROACH",
            source_file="AD_2_LFPG_DATA_RWY27R_RNP_CODE.pdf",
            source_url="",
            source_document_date="2026-10-01",
            airac_effective_date="2026-10-29",
            source_sha256="def456",
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["leg_sequence_label"], "APCH")
        self.assertEqual(rows[1]["waypoint_ident"], "RW27R")
        self.assertEqual(rows[1]["minimum_altitude_raw"], "5000")
        self.assertEqual(rows[1]["vertical_angle_tch_raw"], "-3.0 / 49")

    def test_fix_ident_ambiguity_is_not_resolved_by_guessing(self):
        table = [
            self.sid_header,
            ["TEST 1A", "", "", "", "", "", "", "", "", "", "", ""],
            ["RWY09", "TF", "DUP", "-", "090", "091.0", "5.0", "-", "3000", "-", "210", "1.0"],
        ]
        rows = parse_table_rows(
            table,
            airport_icao="LFXX",
            procedure_type="SID",
            source_file="AD_2_LFXX_DATA_SID_TEST.pdf",
            source_url="",
            source_document_date="",
            airac_effective_date="2026-10-29",
            source_sha256="x",
            fix_index={"DUP": [("50.0", "3.0"), ("51.0", "4.0")]},
        )
        self.assertEqual(rows[0]["fix_resolution"], "ambiguous_source_fix")
        self.assertEqual(rows[0]["fix_latitude"], "")

    def test_filename_discovery_excludes_final_segment_and_chart_files(self):
        self.assertEqual(
            parse_doc_identity("AD_2_LFPG_DATA_SID_RWY26L-26R_RNAV_CODE_02.pdf"),
            ("LFPG", "SID"),
        )
        self.assertEqual(
            parse_doc_identity("AD_2_LFPG_DATA_STAR_RWY26L_RNAV_CODE_02.pdf"),
            ("LFPG", "STAR"),
        )
        self.assertEqual(
            parse_doc_identity("AD_2_LFPG_DATA_RWY27R_RNP_CODE.pdf"),
            ("LFPG", "APPROACH"),
        )
        self.assertIsNone(parse_doc_identity("AD_2_LFPG_DATA_RWY27R_FNA_RNP_CODE.pdf"))
        self.assertIsNone(parse_doc_identity("AD_2_LFPG_IAC_RWY27R_RNP.pdf"))

    def test_aip_date_parser(self):
        self.assertEqual(parse_aip_date("AIP FRANCE 01 OCT 2026"), "2026-10-01")
        self.assertEqual(parse_aip_date("no date"), "")


if __name__ == "__main__":
    unittest.main()
