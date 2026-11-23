import csv
import io
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1] / "pipeline"
sys.path.insert(0, str(PIPELINE))
import fetch_faa_nasr_ifr as mod  # noqa: E402


def csv_text(header, rows):
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def zip_file(path, members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


FIX_HEADER = ["EFF_DATE", "FIX_ID", "STATE_CODE", "ICAO_REGION_CODE", "LAT_DECIMAL", "LONG_DECIMAL", "FIX_USE_CODE"]
NAV_HEADER = ["EFF_DATE", "NAV_ID", "NAV_TYPE", "STATE_CODE", "COUNTRY_CODE", "NAME", "NAV_STATUS",
              "LAT_DECIMAL", "LONG_DECIMAL", "ELEV", "FREQ"]
AWY_HEADER = ["AWY_LOCATION", "AWY_ID", "POINT_SEQ", "FROM_POINT", "FROM_PT_TYPE", "STATE_CODE",
              "ICAO_REGION_CODE", "TO_POINT", "MAG_COURSE", "AWY_SEG_GAP_FLAG", "MIN_ENROUTE_ALT"]


def sample_fixes():
    return [
        ["2026/11/26", "ABCDE", "VA", "K6", "38.5", "-77.5", "WP"],
        ["2026/11/26", "FGHIJ", "MD", "K6", "39.0", "-76.5", "WP"],
        ["2026/11/26", "KLMNO", "PA", "K6", "40.0", "-76.0", "WP"],
        ["2026/11/26", "DUPFX", "VA", "K6", "37.0", "-78.0", "WP"],
        ["2026/11/26", "DUPFX", "NC", "K7", "35.0", "-80.0", "WP"],
        ["2026/11/26", "VPABC", "VA", "K6", "38.8", "-77.0", "VFR"],      # VFR point: skipped
        ["2026/11/26", "BADFX", "VA", "K6", "0", "0", "WP"],               # null island: rejected
    ]


def sample_navaids():
    return [
        ["2026/11/26", "ABC", "VORTAC", "VA", "US", "ALPHA", "OPERATIONAL IFR", "38.0", "-77.0", "250", "113.1"],
        ["2026/11/26", "XYZ", "NDB", "MD", "US", "ZULU", "OPERATIONAL IFR", "39.5", "-76.9", "100", "329"],
    ]


class CycleTests(unittest.TestCase):
    def test_cycle_on_effective_day_and_before(self):
        self.assertEqual(mod.cycle_effective_on_or_before(date(2026, 11, 26)), date(2026, 11, 26))
        self.assertEqual(mod.cycle_effective_on_or_before(date(2026, 11, 25)), date(2026, 10, 29))
        self.assertEqual(mod.cycle_effective_on_or_before(date(2026, 12, 23)), date(2026, 11, 26))
        self.assertEqual(mod.cycle_effective_on_or_before(date(2026, 12, 24)), date(2026, 12, 24))

    def test_known_published_cycles_match_the_series(self):
        for known in ("2026-09-03", "2026-10-01", "2026-10-29"):
            d = date.fromisoformat(known)
            self.assertEqual(mod.cycle_effective_on_or_before(d), d)

    def test_expiry_matches_existing_manifest_convention(self):
        self.assertEqual(mod.cycle_expiry(date(2026, 10, 29)), date(2026, 11, 25))

    def test_archive_links_found_case_insensitively(self):
        html = ('<a href="/x/FIX_CSV.zip">a</a><a href="nav_csv.ZIP">b</a>'
                '<a href="https://e.com/AWY_CSV.zip">c</a><a href="/x/other.zip">d</a>')
        links = mod.find_archive_links(html, "https://www.faa.gov/p/2026-11-26")
        self.assertEqual(set(links), {"fix", "nav", "awy"})
        self.assertTrue(links["nav"].startswith("https://www.faa.gov/p/"))


class ReadingTests(unittest.TestCase):
    def test_reads_member_directly_in_archive(self):
        with tempfile.TemporaryDirectory() as td:
            z = zip_file(Path(td) / "f.zip", {"FIX_BASE.csv": csv_text(FIX_HEADER, sample_fixes())})
            self.assertEqual(len(mod.read_group_rows(z, "fix")), 7)

    def test_reads_member_inside_nested_archive(self):
        with tempfile.TemporaryDirectory() as td:
            inner = Path(td) / "inner.zip"
            zip_file(inner, {"NAV_BASE.csv": csv_text(NAV_HEADER, sample_navaids())})
            outer = zip_file(Path(td) / "outer.zip", {"README.txt": "x", "NAV_CSV.zip": inner.read_bytes()})
            self.assertEqual(len(mod.read_group_rows(outer, "nav")), 2)

    def test_missing_columns_error_lists_headers_seen(self):
        with tempfile.TemporaryDirectory() as td:
            z = zip_file(Path(td) / "f.zip", {"FIX_BASE.csv": "FOO,BAR\n1,2\n"})
            with self.assertRaises(mod.NasrError) as ctx:
                mod.read_group_rows(z, "fix")
            self.assertIn("FOO", str(ctx.exception))

    def test_airway_member_prefers_file_with_required_columns(self):
        with tempfile.TemporaryDirectory() as td:
            z = zip_file(Path(td) / "a.zip", {
                "AWY_BASE.csv": "AWY_ID,SOMETHING\nV1,x\n",
                "AWY_SEG_ALT.csv": csv_text(AWY_HEADER, [["C", "V1", "1", "ABCDE", "WAYPOINT", "VA", "K6", "", "", "", ""]]),
            })
            rows = mod.read_group_rows(z, "awy")
            self.assertEqual(rows[0]["FROM_POINT"], "ABCDE")


class ParsingTests(unittest.TestCase):
    def test_fixes_skip_vfr_points_and_reject_null_island(self):
        rows = [mod.norm_row(dict(zip(FIX_HEADER, r))) for r in sample_fixes()]
        fixes, stats = mod.parse_fixes(rows, "2026-11-26")
        idents = [f["ident"] for f in fixes]
        self.assertNotIn("VPABC", idents)
        self.assertNotIn("BADFX", idents)
        self.assertEqual(stats["vfr_reporting_points_skipped"], 1)
        self.assertEqual(stats["rejected"], 1)
        self.assertEqual(idents.count("DUPFX"), 2)

    def test_navaid_fields(self):
        rows = [mod.norm_row(dict(zip(NAV_HEADER, r))) for r in sample_navaids()]
        navaids, _ = mod.parse_navaids(rows, "2026-11-26")
        self.assertEqual(navaids[0]["ident"], "ABC")
        self.assertEqual(navaids[0]["elevation_ft"], "250")
        self.assertEqual(navaids[0]["cycle_effective"], "2026-11-26")


class AirwayTests(unittest.TestCase):
    def setUp(self):
        fixes, _ = mod.parse_fixes([mod.norm_row(dict(zip(FIX_HEADER, r))) for r in sample_fixes()], "2026-11-26")
        navaids, _ = mod.parse_navaids([mod.norm_row(dict(zip(NAV_HEADER, r))) for r in sample_navaids()], "2026-11-26")
        self.index = mod.build_index(fixes, navaids)

    def awy(self, rows):
        return [mod.norm_row(dict(zip(AWY_HEADER, r))) for r in rows]

    def test_builds_ordered_segments_with_navaid_and_fix_endpoints(self):
        rows = self.awy([
            ["C", "V16", "20", "FGHIJ", "WAYPOINT", "MD", "K6", "", "", "", ""],
            ["C", "V16", "10", "ABC", "VORTAC", "VA", "", "", "", "", "3000"],
            ["C", "V16", "30", "KLMNO", "REPORTING POINT", "PA", "K6", "", "", "", ""],
        ])
        segments, stats = mod.build_segments(rows, self.index, "2026-11-26")
        self.assertEqual([(s["from_ident"], s["to_ident"]) for s in segments], [("ABC", "FGHIJ"), ("FGHIJ", "KLMNO")])
        self.assertEqual(segments[0]["from_kind"], "NAV")
        self.assertEqual(segments[0]["to_kind"], "FIX")
        self.assertEqual(segments[0]["min_enroute_alt_ft"], "3000")
        self.assertEqual(segments[0]["airway_family"], "V")
        self.assertGreater(segments[0]["distance_nm"], 20)
        self.assertEqual(stats["unresolved"], 0)

    def test_final_point_is_taken_from_to_point_of_last_row(self):
        rows = self.awy([
            ["C", "J5", "1", "ABCDE", "WAYPOINT", "VA", "K6", "FGHIJ", "", "", ""],
            ["C", "J5", "2", "FGHIJ", "WAYPOINT", "MD", "K6", "KLMNO", "", "", ""],
        ])
        segments, stats = mod.build_segments(rows, self.index, "2026-11-26")
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[-1]["to_ident"], "KLMNO")
        self.assertEqual(stats["sequence_mismatches"], 0)

    def test_gap_flag_breaks_airway_without_a_segment(self):
        rows = self.awy([
            ["C", "V1", "1", "ABCDE", "WAYPOINT", "VA", "K6", "", "", "Y", ""],
            ["C", "V1", "2", "FGHIJ", "WAYPOINT", "MD", "K6", "", "", "", ""],
            ["C", "V1", "3", "KLMNO", "WAYPOINT", "PA", "K6", "", "", "", ""],
        ])
        segments, stats = mod.build_segments(rows, self.index, "2026-11-26")
        self.assertEqual([(s["from_ident"], s["to_ident"]) for s in segments], [("FGHIJ", "KLMNO")])
        self.assertEqual(stats["gap_breaks"], 1)

    def test_ambiguous_identifier_is_rejected_not_guessed(self):
        rows = self.awy([
            ["C", "V2", "1", "ABCDE", "WAYPOINT", "VA", "K6", "", "", "", ""],
            ["C", "V2", "2", "DUPFX", "WAYPOINT", "", "", "", "", "", ""],  # two coordinates, no state/region
        ])
        segments, stats = mod.build_segments(rows, self.index, "2026-11-26")
        self.assertEqual(segments, [])
        self.assertEqual(stats["unresolved"], 1)

    def test_state_and_region_disambiguate_duplicates(self):
        rows = self.awy([
            ["C", "V3", "1", "ABCDE", "WAYPOINT", "VA", "K6", "", "", "", ""],
            ["C", "V3", "2", "DUPFX", "WAYPOINT", "NC", "K7", "", "", "", ""],
        ])
        segments, _ = mod.build_segments(rows, self.index, "2026-11-26")
        self.assertEqual(len(segments), 1)
        self.assertEqual((segments[0]["to_latitude"], segments[0]["to_longitude"]), (35.0, -80.0))

    def test_unknown_identifier_is_unresolved(self):
        rows = self.awy([
            ["C", "V4", "1", "ABCDE", "WAYPOINT", "VA", "K6", "", "", "", ""],
            ["C", "V4", "2", "NOPE1", "WAYPOINT", "VA", "K6", "", "", "", ""],
        ])
        segments, stats = mod.build_segments(rows, self.index, "2026-11-26")
        self.assertEqual(segments, [])
        self.assertIn("V4:ABCDE->NOPE1", stats["unresolved_examples"])

    def test_sequence_mismatch_is_counted(self):
        rows = self.awy([
            ["C", "V5", "1", "ABCDE", "WAYPOINT", "VA", "K6", "KLMNO", "", "", ""],
            ["C", "V5", "2", "FGHIJ", "WAYPOINT", "MD", "K6", "", "", "", ""],
        ])
        _, stats = mod.build_segments(rows, self.index, "2026-11-26")
        self.assertEqual(stats["sequence_mismatches"], 1)


class GuardTests(unittest.TestCase):
    def stats(self, **kw):
        base = {"candidate_segments": 100, "unresolved": 0, "sequence_checks": 100,
                "sequence_mismatches": 0, "unresolved_examples": []}
        base.update(kw)
        return base

    def test_small_downloads_are_refused(self):
        with self.assertRaises(mod.NasrError):
            mod.check_guards([{}] * 3, [{}] * 3, [{}] * 3, self.stats())

    def test_high_unresolved_rate_is_refused(self):
        with self.assertRaises(mod.NasrError):
            mod.check_guards([{}] * mod.MIN_FIXES, [{}] * mod.MIN_NAVAIDS, [{}] * mod.MIN_SEGMENTS,
                             self.stats(unresolved=40))

    def test_layout_drift_is_refused(self):
        with self.assertRaises(mod.NasrError):
            mod.check_guards([{}] * mod.MIN_FIXES, [{}] * mod.MIN_NAVAIDS, [{}] * mod.MIN_SEGMENTS,
                             self.stats(sequence_mismatches=50))

    def test_healthy_import_passes(self):
        mod.check_guards([{}] * mod.MIN_FIXES, [{}] * mod.MIN_NAVAIDS, [{}] * mod.MIN_SEGMENTS, self.stats(unresolved=2))


def build_sample_zips(td):
    td = Path(td)
    zips = {
        "fix": zip_file(td / "FIX_CSV.zip", {"FIX_BASE.csv": csv_text(FIX_HEADER, sample_fixes())}),
        "nav": zip_file(td / "NAV_CSV.zip", {"NAV_BASE.csv": csv_text(NAV_HEADER, sample_navaids())}),
        "awy": zip_file(td / "AWY_CSV.zip", {"AWY_SEG_ALT.csv": csv_text(AWY_HEADER, [
            ["C", "V16", "1", "ABC", "VORTAC", "VA", "", "FGHIJ", "", "", ""],
            ["C", "V16", "2", "FGHIJ", "WAYPOINT", "MD", "K6", "KLMNO", "", "", ""],
        ])}),
    }
    archives = {k: {"url": "local", "sha256": mod.sha256_file(p), "sizeBytes": p.stat().st_size} for k, p in zips.items()}
    return zips, archives


class EndToEndTests(unittest.TestCase):
    def build_zips(self, td):
        return build_sample_zips(td)

    def setUp(self):
        self._floors = (mod.MIN_FIXES, mod.MIN_NAVAIDS, mod.MIN_SEGMENTS)
        mod.MIN_FIXES, mod.MIN_NAVAIDS, mod.MIN_SEGMENTS = 1, 1, 1

    def tearDown(self):
        mod.MIN_FIXES, mod.MIN_NAVAIDS, mod.MIN_SEGMENTS = self._floors

    def test_full_run_writes_csvs_and_meta_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as out:
            zips, archives = self.build_zips(td)
            self.assertTrue(mod.run(date(2026, 11, 26), zips, archives, Path(out)))
            meta = json.loads((Path(out) / "meta.json").read_text())
            self.assertEqual(meta["effectiveDate"], "2026-11-26")
            self.assertEqual(meta["expiryDate"], "2026-12-23")
            self.assertEqual(meta["licenseStatus"], "public_domain")
            self.assertEqual(meta["files"]["airway_segments.csv"]["recordCount"], 2)
            header = (Path(out) / "airway_segments.csv").read_text().splitlines()[0].split(",")
            self.assertEqual(header, mod.SEGMENT_COLUMNS)
            before = (Path(out) / "meta.json").read_text()
            self.assertFalse(mod.run(date(2026, 11, 26), zips, archives, Path(out)))
            self.assertEqual((Path(out) / "meta.json").read_text(), before)

    def test_failed_guard_writes_nothing(self):
        mod.MIN_SEGMENTS = 50
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as out:
            zips, archives = self.build_zips(td)
            with self.assertRaises(mod.NasrError):
                mod.run(date(2026, 11, 26), zips, archives, Path(out))
            self.assertEqual(list(Path(out).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
