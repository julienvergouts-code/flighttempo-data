import gzip
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "pipeline"))

import import_sia_france_enr as imp  # noqa: E402
import register_sia_france_manifest as reg  # noqa: E402
import sia_enr_parse as p  # noqa: E402


def table(*rows):
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<html><body><table>{body}</table></body></html>"


FIXES = table(
    ["Nom", "Coordonnées", "Routes"],
    ["ABENO", "49°10'20\"N 002°30'10\"E", "UN10"],
    ["ABENO", "49°10'20\"N 002°30'10\"E", "UN10"],
    ["TOO LONG NAME", "49°10'20\"N 002°30'10\"E"],
    ["LUMAV", "43°00'00.5\"S 005°00'00\"W", ""],
)
NAVAIDS = table(
    ["Nom", "Type", "Ident", "Fréq", "Horaires", "49°00'00\"N 002°00'00\"E", "300 ft"],
    ["PARIS", "VOR-DME", "PGS", "113.00", "H24", "49°00'00\"N 002°00'00\"E", "300 ft"],
    ["BAD", "XXX", "BAD", "1", "H24", "49°00'00\"N 002°00'00\"E"],
)
ROUTES = table(
    ["A2"],
    ["▲", "ABC (ABC)", "49°00'00\"N 002°00'00\"E"],
    ["RNAV 5", "090"],
    ["FL 195"],
    ["FL 95"],
    ["▲", "DEF (DEF)", "49°00'00\"N 003°00'00\"E"],
    ["RNAV 5", "090"],
    ["FL 195"],
    ["FL 95"],
    ["▲", "GHI (GHI)", "49°00'00\"N 004°00'00\"E"],
)
SQUARE = "45°00'00\"N , 003°00'00\"E - 45°00'00\"N , 004°00'00\"E - 46°00'00\"N , 004°00'00\"E - 46°00'00\"N , 003°00'00\"E"
AIRSPACE = table(
    ["TMA TESTVILLE 1"],
    ["D", SQUARE, "FL 195 ------------ 3300ft AMSL"],
    ["CTR NOWHERE", "bad geometry", "FL 100 ------------ SFC"],
)


class ParserTests(unittest.TestCase):
    def test_coordinates(self):
        self.assertEqual(p.find_coords("49°10'20\"N 002°30'10\"E"), [(49.172222, 2.502778)])
        self.assertEqual(p.find_coords("43°00'00.5\"S 005°00'00\"W")[0][0] < 0, True)

    def test_limits(self):
        lower, upper = p.split_limits("FL 195 ------------ 3300ft AMSL")
        self.assertEqual((lower["ft"], upper["ft"]), (3300, 19500))
        self.assertEqual(p.split_limits("FL 100 ----- SFC")[0]["ft"], 0)
        self.assertIsNone(p.split_limits("garbage ----- SFC"))

    def test_fixes_dedupe_and_requires_one_coordinate(self):
        fixes = p.parse_fixes(p.iter_rows(FIXES))
        self.assertEqual([f["ident"] for f in fixes], ["ABENO", "LUMAV"])

    def test_navaids(self):
        navaids = p.parse_navaids(p.iter_rows(NAVAIDS))
        self.assertEqual(len(navaids), 1)
        self.assertEqual(navaids[0]["ident"], "PGS")
        self.assertEqual(navaids[0]["elevation_ft"], "300")

    def test_route_segments(self):
        segs = p.route_segments(p.parse_routes(p.iter_rows(ROUTES)))
        self.assertEqual(len(segs), 2)
        self.assertEqual((segs[0]["from_ident"], segs[0]["to_ident"], segs[0]["segment_seq"]), ("ABC", "DEF", 1))
        self.assertEqual(segs[0]["upper_limit_ft"], 19500)
        self.assertEqual(segs[0]["min_enroute_alt_ft"], 9500)
        self.assertEqual(segs[0]["mag_course"], 90)
        self.assertAlmostEqual(segs[0]["distance_nm"], 38.0, delta=1.5)
        self.assertEqual(segs[1]["segment_seq"], 2)

    def test_airspace(self):
        feats, stats = p.parse_airspace(p.iter_rows(AIRSPACE), "enr2")
        self.assertEqual(len(feats), 1)
        self.assertEqual(feats[0]["type"], "TMA")
        self.assertEqual(feats[0]["lower"]["ft"], 3300)
        self.assertEqual(feats[0]["rings"][0][0], feats[0]["rings"][0][-1])
        self.assertEqual(stats["considered"], 1)

    def test_restricted_zone_section(self):
        rows = [["LF R 12 A"], ["", SQUARE, "FL 100 ------------ SFC"]]
        feats, _ = p.parse_airspace(rows, "enr5")
        self.assertEqual((len(feats), feats[0]["type"]), (1, "R"))

    def test_arc_and_circle_and_border(self):
        centre = "45°30'00\"N , 003°30'00\"E"
        text = ("45°00'00\"N , 003°00'00\"E - arc horaire de 30 NM de rayon centré sur " + centre +
                " - 45°00'00\"N , 004°00'00\"E - Frontière franco-espagnole - 46°00'00\"N , 004°00'00\"E")
        ring, stats = p.parse_geometry(text)
        self.assertIsNotNone(ring)
        self.assertEqual((stats["arcs"], stats["border_segments"]), (1, 1))
        circle, _ = p.parse_geometry("cercle de 5 km de rayon centré sur " + centre)
        self.assertEqual(len(circle), 49)
        self.assertAlmostEqual(p.haversine_nm((45.5, 3.5), tuple(circle[0])), 5 / 1.852, delta=0.1)


class ImportAndRegisterTests(unittest.TestCase):
    def fake(self, pages):
        catalog = ("ZIP eAIP complet AIRAC 12/26 0,00 € en vigueur du 26/11/2026 au 23/12/2026 "
                   "ZIP eAIP complet AIRAC 11/26 0,00 € en vigueur du 29/10/2026 au 25/11/2026")
        licence = ("tous les produits des sous rubriques Licence Ouverte commerciales ou non redistribuer "
                   "produit ou application date de derniere mise a jour zones geographiques UAS")

        def getter(url):
            if url.endswith("eaip.html"):
                return catalog
            if "produits-numeriques-en-libre-disposition.html" in url:
                return licence
            return pages.get(url.rsplit("/", 1)[-1])
        return getter

    def test_unreachable_skips_cleanly(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(imp.run(Path(d) / "n", Path(d) / "a", getter=lambda url: None), 0)
            self.assertFalse((Path(d) / "n").exists())

    def test_small_pages_fail_guard_and_publish_nothing(self):
        pages = {"FR-ENR-4.4-fr-FR.html": FIXES}
        with tempfile.TemporaryDirectory() as d:
            code = imp.run(Path(d) / "n", Path(d) / "a", getter=self.fake(pages), today=date(2026, 11, 24))
            self.assertEqual(code, 1)
            self.assertFalse((Path(d) / "n" / "fixes.csv").exists())

    def test_end_to_end_with_lowered_minimums(self):
        pages = {"FR-ENR-4.4-fr-FR.html": FIXES, "FR-ENR-4.1-fr-FR.html": NAVAIDS,
                 "FR-ENR-3.2-fr-FR.html": ROUTES, "FR-ENR-2.1-fr-FR.html": AIRSPACE}
        saved = dict(imp.MIN_COUNTS)
        imp.MIN_COUNTS.update({k: 1 for k in saved})
        try:
            with tempfile.TemporaryDirectory() as d:
                nav, air = Path(d) / "n", Path(d) / "a"
                self.assertEqual(imp.run(nav, air, getter=self.fake(pages), today=date(2026, 11, 24)), 0)
                meta = json.loads((nav / "meta.json").read_text())
                self.assertEqual(meta["effectiveDate"], "2026-10-29")
                self.assertEqual(meta["files"]["fixes.csv"]["recordCount"], 2)
                pack = json.loads(gzip.decompress((air / "FR.json.gz").read_bytes()))
                self.assertEqual(len(pack["features"]), 1)
                manifest = Path(d) / "manifest.json"
                manifest.write_text(json.dumps({"datasets": [], "capabilities": {}}))
                inside = reg.register(date(2026, 11, 24), nav, air / "index.json", manifest)
                self.assertEqual({e["id"] for e in inside}, {"sia_france_fixes", "sia_france_navaids",
                                                              "sia_france_airway_segments", "sia_france_airspace"})
                self.assertTrue(all(e["available"] for e in inside))
                after = reg.register(date(2026, 11, 26), nav, air / "index.json", manifest)
                self.assertFalse(any(e["available"] for e in after))
                self.assertFalse(any("downloadUrl" in e for e in after))
        finally:
            imp.MIN_COUNTS.update(saved)

    def test_register_without_files_unregisters(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = Path(d) / "manifest.json"
            manifest.write_text(json.dumps({"datasets": [{"id": "sia_france_fixes"}], "capabilities": {}}))
            reg.register(date(2026, 11, 24), Path(d) / "none", Path(d) / "none.json", manifest)
            self.assertEqual(json.loads(manifest.read_text())["datasets"], [])


if __name__ == "__main__":
    unittest.main()
