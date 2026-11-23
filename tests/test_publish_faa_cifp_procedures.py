import csv
import io
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "scripts"))
import publish_faa_cifp_procedures as mod  # noqa: E402


def leg(airport, proc, rtype, trans, seq, fix, pt, desc="", alt="", spd="", sub="D", cont="0"):
    line = [" "] * 132

    def put(a, b, text):
        line[a:b] = list(text.ljust(b - a)[: b - a])
    put(0, 1, "S"); put(1, 4, "USA"); put(4, 5, "P"); put(6, 10, airport); put(10, 12, "K1")
    put(12, 13, sub); put(13, 19, proc); put(19, 20, rtype); put(20, 25, trans)
    put(26, 29, f"{seq:03d}"); put(29, 34, fix); put(38, 39, cont); put(47, 49, pt)
    put(82, 83, desc); put(84, 89, alt); put(99, 102, spd)
    return "".join(line)


def make_zip(path, lines, member="FAACIFP18"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(member, "\r\n".join(lines) + "\r\n")


def synth_lines(n_airports=30, with_changes=False):
    lines = []
    for i in range(n_airports):
        ap = f"K{i:03d}"
        for kind, sub in (("DEP", "D"), ("ARR", "E")):
            for s in range(1, 9):
                fix = "FIX%02d" % ((i + s) % 40)
                lines.append(leg(ap, f"{kind}{i % 5}", "4", "RW18", s * 10, fix, "TF", "+", "05000", sub=sub))
    lines.append("HEADER" + " " * 126)
    lines.append(leg("K000", "DEP0", "4", "RW18", 10, "", "VA", cont="2"))  # continuation record
    lines.append(leg("K000", "APP", "I", "I18", 10, "FIX01", "TF", sub="F"))  # approach, not published
    return lines


class DecodeTests(unittest.TestCase):
    def test_cycle_arithmetic(self):
        self.assertEqual(mod.cycle_effective_on_or_before(date(2026, 11, 23)), date(2026, 10, 29))
        self.assertEqual(mod.cycle_effective_on_or_before(date(2026, 11, 26)), date(2026, 11, 26))
        self.assertEqual(mod.airac_label(date(2026, 10, 29)), "2611")
        self.assertEqual(mod.airac_label(date(2026, 11, 26)), "2612")
        self.assertEqual(mod.cycle_expiry(date(2026, 10, 29)), date(2026, 11, 25))

    def test_decode_primary_only_and_columns(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "c.zip"
            make_zip(z, synth_lines(2) + [leg("K000", "DEP0", "4", "RW18", 5, "", "VA", "+", "00650")])
            rows, stats = mod.decode_archive(z, "FAA_CIFP_2612")
        self.assertEqual(stats["continuationRecordsSkipped"], 1)
        self.assertEqual(len(rows["sids"]), 17)
        self.assertEqual(len(rows["stars"]), 16)
        first = rows["sids"][0]
        self.assertEqual((first["seq"], first["path_terminator"], first["alt1"], first["alt_desc"]),
                         ("5", "VA", "00650", "+"))
        self.assertEqual(first["source"], "FAA_CIFP_2612")

    def test_wrong_width_fails(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "c.zip"
            make_zip(z, ["S" * 100])
            with self.assertRaises(mod.CifpError):
                mod.decode_archive(z, "x")

    def test_missing_member_and_unsafe_path(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "c.zip"
            make_zip(z, ["x"], member="other.txt")
            with self.assertRaisesRegex(mod.CifpError, "lacks"):
                mod.decode_archive(z, "x")
            make_zip(z, ["x"], member="../evil")
            with self.assertRaisesRegex(mod.CifpError, "Unsafe"):
                mod.decode_archive(z, "x")


class GuardTests(unittest.TestCase):
    def rows(self, n=6000, pt="TF"):
        return [{"airport_icao": f"K{i%50:03d}", "procedure_id": "P1", "route_type": "4", "transition_id": "T",
                 "seq": str(i), "fix_id": "ABCDE", "path_terminator": pt, "alt_desc": "", "alt1": "",
                 "speed_limit_kt": "", "source": "s"} for i in range(n)]

    def test_floor(self):
        with self.assertRaisesRegex(mod.CifpError, "truncated"):
            mod.check_dataset("sids", self.rows(10), [], None, "2612", None)

    def test_bad_path_terminators_fail(self):
        with self.assertRaisesRegex(mod.CifpError, "path terminators"):
            mod.check_dataset("sids", self.rows(pt="ZZ"), [], None, "2612", None)

    def test_equivalence_collapse_fails_and_names_column(self):
        prev = self.rows()
        new = [dict(r, alt1="99999") for r in prev]
        with self.assertRaisesRegex(mod.CifpError, "alt1"):
            mod.check_dataset("sids", new, prev, "2611", "2612", None)

    def test_small_change_passes(self):
        prev = self.rows()
        new = [dict(r) for r in prev]
        for r in new[:100]:
            r["alt1"] = "01000"
        rep = mod.check_dataset("sids", new, prev, "2611", "2612", None)
        self.assertGreater(rep["equivalence"]["identicalShare"], 0.95)

    def test_fix_witness(self):
        with self.assertRaisesRegex(mod.CifpError, "misaligned"):
            mod.check_dataset("sids", self.rows(), [], None, "2612", {"ZZZZZ"})

    def test_row_ratio(self):
        prev = self.rows()
        with self.assertRaisesRegex(mod.CifpError, "row count changed"):
            mod.check_dataset("sids", self.rows(5000), prev, "2611", "2612", None)


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.old = (mod.MIN_ROWS,)
        mod.MIN_ROWS = 100
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        (self.root / "procedures").mkdir()
        (self.root / "navigation_manifest.json").write_text(json.dumps({"datasets": [
            {"id": "sids"}, {"id": "stars"}]}), encoding="utf-8")
        (self.root / "procedures/source-manifest.json").write_text(json.dumps({"datasets": {}}), encoding="utf-8")
        self.zip = self.root / "c.zip"
        make_zip(self.zip, synth_lines())

    def tearDown(self):
        mod.MIN_ROWS = self.old[0]
        self.td.cleanup()

    def test_publish_is_idempotent_and_contract_valid(self):
        eff = date(2026, 11, 26)
        self.assertTrue(mod.publish(self.root, eff, self.zip, mod.archive_url(eff), date(2026, 11, 26)))
        sids = (self.root / "procedures/sids/sids.csv").read_bytes()
        self.assertTrue(sids.startswith(b"#version,2612\r\n"))
        manifest = json.loads((self.root / "navigation_manifest.json").read_text())
        entry = next(d for d in manifest["datasets"] if d["id"] == "sids")
        self.assertTrue(entry["available"])
        self.assertEqual(entry["expiryDate"], "2026-12-23")
        self.assertIn("downloadUrl", entry)
        self.assertFalse(mod.publish(self.root, eff, self.zip, mod.archive_url(eff), date(2026, 11, 26)))
        rows = list(csv.reader(io.StringIO(sids.decode())))
        self.assertEqual(rows[1], mod.COLUMNS)

    def test_not_yet_effective_is_not_downloadable(self):
        eff = date(2026, 11, 26)
        mod.publish(self.root, eff, self.zip, mod.archive_url(eff), date(2026, 11, 20))
        manifest = json.loads((self.root / "navigation_manifest.json").read_text())
        entry = next(d for d in manifest["datasets"] if d["id"] == "stars")
        self.assertFalse(entry["available"])
        self.assertNotIn("downloadUrl", entry)

    def test_failure_writes_nothing(self):
        make_zip(self.zip, synth_lines()[:10])
        with self.assertRaises(mod.CifpError):
            mod.publish(self.root, date(2026, 11, 26), self.zip, "u", date(2026, 11, 26))
        self.assertFalse((self.root / "procedures/sids/sids.csv").exists())


if __name__ == "__main__":
    unittest.main()
