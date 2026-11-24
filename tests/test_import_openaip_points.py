import csv, json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline")); sys.path.insert(0, str(ROOT / "scripts"))
import import_openaip_points as m
import import_openaip_airspace as asp
import register_openaip_points_manifest as reg
import commercial_rights as cr


def nav(t=7, ident="AFI", lon=4.0, lat=50.0, **kw):
    return {"type": "Feature", "properties": {"_id": ident, "identifier": ident, "name": "AFFLIGEM", "type": t, "channel": "96X",
            "frequency": {"value": "114.900", "unit": 2}, "elevation": {"value": 68, "unit": 0, "referenceDatum": 1}, **kw},
            "geometry": {"type": "Point", "coordinates": [lon, lat]}}


def rpp(name="KONTI", **kw):
    return {"type": "Feature", "properties": {"name": name, "compulsory": True, "elevation": {"value": 19, "unit": 0}, **kw},
            "geometry": {"type": "Point", "coordinates": [4.1, 50.9]}}


def fc(*f):
    return json.dumps({"type": "FeatureCollection", "features": list(f)}).encode()


class T(unittest.TestCase):
    def test_navaids(self):
        rows, st = m.parse_navaids(fc(nav(), nav(t=99, ident="X"), {"type": "Feature", "properties": {}, "geometry": None}), "BE")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["type"], "DVOR-DME")
        self.assertEqual(rows[0]["frequency"], "114.900 MHz")
        self.assertEqual(rows[0]["elevation_ft"], "223")
        self.assertEqual((st["bad_geometry"], st["unknown_type"]), (1, 1))

    def test_reporting_points(self):
        rows, st = m.parse_reporting_points(fc(rpp(), rpp(name="")), "BE")
        self.assertEqual([r["name"] for r in rows], ["KONTI"])
        self.assertEqual(rows[0]["compulsory"], "true")
        self.assertEqual(st["bad_geometry"], 1)

    def test_guards(self):
        with self.assertRaises(asp.OpenAipError):
            m.check("BE", "nav", [], {"considered": 3, "unknown_type": 0})
        rows, st = m.parse_navaids(fc(*[nav(t=99, ident=str(i)) for i in range(6)]), "BE")
        with self.assertRaises(asp.OpenAipError):
            m.check("BE", "nav", rows, st)

    def test_run_skips_covered_and_unreachable(self):
        calls = []

        def getter(url, h=None):
            calls.append(url)
            return fc(nav()) if "_nav" in url else fc(rpp())
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            rc = m.run(d / "n.csv", d / "r.csv", ["US", "FR", "BE", "GB"], getter=getter)
            self.assertEqual(rc, 0)
            nav_rows = list(csv.DictReader((d / "n.csv").open()))
            rpp_rows = list(csv.DictReader((d / "r.csv").open()))
            self.assertEqual({r["country_code"] for r in nav_rows}, {"BE", "GB"})  # US and FR covered
            self.assertEqual({r["country_code"] for r in rpp_rows}, {"GB"})        # BE (OFMA), FR, US covered
            self.assertEqual(m.run(d / "n2.csv", d / "r2.csv", ["GB"], getter=lambda u, h=None: None), 0)
            self.assertFalse((d / "n2.csv").exists())

    def test_register_personal_only(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "navigation/openaip").mkdir(parents=True); (d / "data").mkdir()
            (d / "navigation/openaip/navaids.csv").write_text("ident,type\nAFI,VOR\n")
            (d / "data/openaip_reporting_points.csv").write_text("name\nKONTI\n")
            (d / "m.json").write_text(json.dumps({"datasets": [], "capabilities": {}}))
            (d / "s.json").write_text(json.dumps({"scope": "personal", "confirmedBy": "me"}))
            out = reg.register(d, d / "m.json", d / "s.json")
            self.assertEqual(len(out), 2)
            for e in out:
                self.assertTrue(e["available"])
                self.assertIsNone(cr.redistribution_block_reason(e, True))
                self.assertIsNotNone(cr.redistribution_block_reason(e, False))
            (d / "s.json").write_text(json.dumps({"scope": "commercial"}))
            out = reg.register(d, d / "m.json", d / "s.json")
            self.assertTrue(all(not e["available"] for e in out))


if __name__ == "__main__":
    unittest.main()
