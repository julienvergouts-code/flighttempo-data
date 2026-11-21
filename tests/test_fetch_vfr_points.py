import csv
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path
import unittest

PIPELINE = Path(__file__).resolve().parents[1] / "pipeline"
sys.path.insert(0, str(PIPELINE))
import fetch_vfr_points as mod


class Response:
    def __init__(self, text="", content=b"", status=200):
        self.text, self.content, self.status_code = text, content, status
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
    def iter_content(self, chunk_size=65536):
        stream = io.BytesIO(self.content)
        while chunk := stream.read(chunk_size):
            yield chunk
    def __enter__(self): return self
    def __exit__(self, *args): return False


def make_csv(rows):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=["FIX_ID", "LAT_DECIMAL", "LONG_DECIMAL"])
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


def zip_bytes(members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return out.getvalue()


class VfrReportingPointPipelineTests(unittest.TestCase):
    def test_fix_link_case_insensitive_and_cycle_date(self):
        html = '<a href="/extra/26_Nov_2026_fix_csv.zip">FIX</a>'
        self.assertEqual(mod.extract_fix_links(html, "https://example.com/index/"), [
            ("https://example.com/extra/26_Nov_2026_fix_csv.zip", "2026-11-26")
        ])

    def test_cycle_pages_and_dates(self):
        html = '<a href="cycle_26_Nov_2026.html">Cycle</a><a href="2026-09-03">Current cycle</a>'
        self.assertEqual(mod.extract_cycle_pages(html, "https://faa.gov/sub/"), [
            ("https://faa.gov/sub/cycle_26_Nov_2026.html", "2026-11-26"),
            ("https://faa.gov/sub/2026-09-03", "2026-09-03"),
        ])

    def test_nested_zip_parser_extracts_only_vp_points(self):
        inner = zip_bytes({"FIX_BASE.csv": make_csv([
            {"FIX_ID": "VPABC", "LAT_DECIMAL": "34.123456", "LONG_DECIMAL": "-118.123456"},
            {"FIX_ID": "KLAX", "LAT_DECIMAL": "33.9", "LONG_DECIMAL": "-118.4"},
        ])})
        outer = zip_bytes({"sub/fix.zip": inner})
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "faa.zip"
            archive.write_bytes(outer)
            rows = mod.parse_faa_records(mod.iter_fix_base_lines(archive), "2026-11-26")
        self.assertEqual(rows, [{
            "icao": "", "code": "VPABC", "name": "VPABC", "lat": "34.123456",
            "lon": "-118.123456", "role": "VRP", "source": "FAA", "updated_date": "2026-11-26",
        }])

    def test_fallback_to_previous_archive(self):
        index = '<a href="26_Nov_2026_FIX_CSV.zip">latest</a><a href="29_Oct_2026_FIX_CSV.zip">prior</a>'
        archive = zip_bytes({"FIX_BASE.csv": make_csv([{"FIX_ID": "VPABC", "LAT_DECIMAL": "40", "LONG_DECIMAL": "-70"}])})
        def fake_get(url, **kwargs):
            if url == mod.INDEX_URL: return Response(text=index)
            if "26_Nov_2026" in url: return Response(status=404)
            if "29_Oct_2026" in url: return Response(content=archive)
            raise AssertionError(url)
        mod.FAA_FIX_URL = ""
        original_get = mod.get
        mod.get = fake_get
        try:
            self.assertEqual(mod.fetch_faa()[0]["updated_date"], "2026-10-29")
        finally:
            mod.get = original_get

    def test_bad_coordinates_rejected(self):
        for lat, lon in [(0, 0), (91, 0), (0, 181), (-91, 20)]:
            row = {"icao": "", "code": "VP001", "name": "test", "lat": lat, "lon": lon,
                   "role": "VRP", "source": "FAA", "updated_date": "2026-11-26"}
            with self.subTest(lat=lat, lon=lon), self.assertRaises(ValueError):
                mod.validate_record(row)

    def test_rejection_rate_guard(self):
        bad = [{"icao": "", "code": "VP1", "name": "x", "lat": 0, "lon": 0, "role": "VRP",
                "source": "FAA", "updated_date": "2026-11-26"}] * 4
        with self.assertRaisesRegex(RuntimeError, "Rejection rate"):
            mod.validate_records(bad, guard=True)

    def test_retention_when_source_failure_and_partial(self):
        with tempfile.TemporaryDirectory() as td:
            csvpath, metapath = Path(td) / "data.csv", Path(td) / "meta.json"
            old = [{"icao": "", "code": "VPOLD", "name": "VPOLD", "lat": 40, "lon": -70,
                    "role": "VRP", "source": "FAA", "updated_date": "2026-10-01"}]
            mod.write_csv(csvpath, old, "2026-10-01T00:00:00Z")
            orig_csv, orig_meta, orig_fetch = mod.CSV_PATH, mod.META_PATH, mod.fetch_faa
            mod.CSV_PATH, mod.META_PATH = csvpath, metapath
            mod.fetch_faa = lambda: (_ for _ in ()).throw(RuntimeError("bad archive"))
            try:
                self.assertEqual(mod.main(["--allow-partial"]), 0)
                self.assertEqual([r["code"] for r in mod.read_existing(csvpath)], ["VPOLD"])
                self.assertEqual(json.loads(metapath.read_text())["source_status"]["FAA"], "failed")
            finally:
                mod.CSV_PATH, mod.META_PATH, mod.fetch_faa = orig_csv, orig_meta, orig_fetch

    def test_drop_guard_refuses_large_decrease(self):
        with tempfile.TemporaryDirectory() as td:
            path, meta = Path(td) / "points.csv", Path(td) / "meta.json"
            previous = [{"icao": "", "code": f"VP{i:03}", "name": "x", "lat": 40+i/100, "lon": -70,
                         "role": "VRP", "source": "FAA", "updated_date": "2026-10-01"} for i in range(10)]
            mod.write_csv(path, previous, "old")
            orig_csv, orig_meta, orig_fetch = mod.CSV_PATH, mod.META_PATH, mod.fetch_faa
            mod.CSV_PATH, mod.META_PATH = path, meta
            mod.fetch_faa = lambda: previous[:6]
            try:
                self.assertEqual(mod.main([]), 1)
                self.assertEqual(len(mod.read_existing(path)), 10)
            finally:
                mod.CSV_PATH, mod.META_PATH, mod.fetch_faa = orig_csv, orig_meta, orig_fetch

    def test_dry_run_does_not_touch_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            path, meta = Path(td) / "points.csv", Path(td) / "meta.json"
            records = [{"icao": "", "code": "VP001", "name": "VP001", "lat": 40, "lon": -70,
                        "role": "VRP", "source": "FAA", "updated_date": "2026-11-26"}]
            orig_csv, orig_meta, orig_fetch = mod.CSV_PATH, mod.META_PATH, mod.fetch_faa
            mod.CSV_PATH, mod.META_PATH, mod.fetch_faa = path, meta, lambda: records
            try:
                self.assertEqual(mod.main(["--dry-run"]), 0)
                self.assertFalse(path.exists())
                self.assertFalse(meta.exists())
            finally:
                mod.CSV_PATH, mod.META_PATH, mod.fetch_faa = orig_csv, orig_meta, orig_fetch

    def test_publish_pair_rolls_back_if_second_replace_fails(self):
        with tempfile.TemporaryDirectory() as td:
            csvpath, metapath = Path(td) / "points.csv", Path(td) / "meta.json"
            csvpath.write_text("old-csv")
            metapath.write_text("old-meta")
            records = [{"icao": "", "code": "VP001", "name": "VP001", "lat": 40, "lon": -70,
                        "role": "VRP", "source": "FAA", "updated_date": "2026-11-26"}]
            real_replace, count = mod.os.replace, 0
            def fail_second(src, dst):
                nonlocal count
                count += 1
                if count == 2: raise OSError("simulated replace failure")
                return real_replace(src, dst)
            mod.os.replace = fail_second
            try:
                with self.assertRaises(OSError):
                    mod.publish_pair(csvpath, metapath, records, "now", "ok")
            finally:
                mod.os.replace = real_replace
            self.assertEqual(csvpath.read_text(), "old-csv")
            self.assertEqual(metapath.read_text(), "old-meta")

    def test_disabled_ofma_rows_retained_and_faa_wins_duplicate(self):
        faa = {"icao": "", "code": "VP001", "name": "FAA point", "lat": 40, "lon": -70,
               "role": "VRP", "source": "FAA", "updated_date": "2026-11-26"}
        ofma = {"icao": "", "code": "VP001", "name": "OFMA point", "lat": 41, "lon": -71,
                "role": "VRP", "source": "OFMA", "updated_date": "2026-11-20"}
        retained = {"icao": "LFPG", "code": "P1", "name": "P1", "lat": 49, "lon": 2.5,
                    "role": "ENTRY", "source": "OFMA", "updated_date": "2026-11-20"}
        merged = mod.dedupe_sort([ofma, faa, retained])
        self.assertEqual(len(merged), 2)
        self.assertEqual(next(row for row in merged if row["code"] == "VP001")["source"], "FAA")
        self.assertEqual(next(row for row in merged if row["code"] == "P1")["source"], "OFMA")



    def test_unchanged_dataset_does_not_rewrite_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            csvpath, metapath = Path(td) / "points.csv", Path(td) / "meta.json"
            records = [{"icao": "", "code": "VP001", "name": "VP001", "lat": 40, "lon": -70,
                        "role": "VRP", "source": "FAA", "updated_date": "2026-11-26"}]
            mod.write_csv(csvpath, records, "old-generated")
            mod.write_meta(metapath, records, "old-generated", "ok")
            orig_csv, orig_meta, orig_fetch = mod.CSV_PATH, mod.META_PATH, mod.fetch_faa
            mod.CSV_PATH, mod.META_PATH, mod.fetch_faa = csvpath, metapath, lambda: records
            try:
                self.assertEqual(mod.main([]), 0)
                self.assertEqual(json.loads(metapath.read_text())["generated_utc"], "old-generated")
            finally:
                mod.CSV_PATH, mod.META_PATH, mod.fetch_faa = orig_csv, orig_meta, orig_fetch

if __name__ == "__main__":
    unittest.main()
