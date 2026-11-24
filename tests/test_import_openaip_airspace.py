import gzip, json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import import_openaip_airspace as m


def feat(name="X CTR", t=4, cls=3, lower=None, upper=None, coords=None, _id="a1"):
    coords = coords or [[[5, 50], [6, 50], [6, 51], [5, 51], [5, 50]]]
    return {"type": "Feature", "properties": {
        "_id": _id, "name": name, "type": t, "icaoClass": cls,
        "lowerLimit": lower or {"value": 0, "unit": 1, "referenceDatum": 0},
        "upperLimit": upper or {"value": 65, "unit": 6, "referenceDatum": 2}},
        "geometry": {"type": "Polygon", "coordinates": coords}}


def fc(*f):
    return json.dumps({"type": "FeatureCollection", "features": list(f)}).encode()


class T(unittest.TestCase):
    def test_vertical(self):
        self.assertEqual(m.vertical_limit({"value": 0, "unit": 1, "referenceDatum": 0}), {"ft": 0, "ref": "GND"})
        self.assertEqual(m.vertical_limit({"value": 65, "unit": 6, "referenceDatum": 2}), {"ft": 6500, "ref": "FL"})
        self.assertEqual(m.vertical_limit({"value": 3000, "unit": 1, "referenceDatum": 1}), {"ft": 3000, "ref": "MSL"})
        self.assertEqual(m.vertical_limit({"value": 1, "unit": 9, "referenceDatum": 1})["ref"], "UNKNOWN")
        self.assertEqual(m.vertical_limit(None)["ft"], None)

    def test_parse_basic_and_skip(self):
        fs, info = m.parse_country(fc(feat(), feat(t=10, _id="fir")), "BE")
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0]["type"], "CTR")
        self.assertEqual(fs[0]["class"], "D")
        self.assertEqual(fs[0]["rings"][0][0], fs[0]["rings"][0][-1])
        self.assertEqual(fs[0]["bbox"], [50, 5, 51, 6])
        self.assertEqual(info["stats"]["skipped_FIR"], 1)

    def test_bad_geometry_and_unknown_type(self):
        bad = feat(_id="b", coords=[[[5, 50], [5, 50], [5, 50]]])
        fs, info = m.parse_country(fc(feat(), bad, feat(t=99, _id="u")), "BE")
        self.assertEqual(info["stats"]["geometry_failed"], 1)
        self.assertEqual(info["stats"]["unknown_type"], 1)
        self.assertEqual(sorted(f["type"] for f in fs), ["CTR", "UNKNOWN"])

    def test_out_of_range_and_span(self):
        fs, info = m.parse_country(fc(feat(_id="o", coords=[[[5, 95], [6, 95], [6, 96], [5, 96], [5, 95]]]),
                                      feat(_id="w", coords=[[[0, 0], [60, 0], [60, 10], [0, 10], [0, 0]]])), "XX")
        self.assertEqual(fs, [])
        self.assertEqual(info["stats"]["geometry_failed"], 2)

    def test_guards(self):
        with self.assertRaises(m.OpenAipError):
            m.check_country("BE", [], {"stats": {"considered": 3}}, None)
        m.check_country("IN", [], {"stats": {"skipped_FIR": 4}}, None)  # FIR-only is not an error
        fs, info = m.parse_country(fc(*[feat(t=99, _id=str(i), name=str(i)) for i in range(5)]), "BE")
        with self.assertRaises(m.OpenAipError):
            m.check_country("BE", fs, info, None)
        fs1, info1 = m.parse_country(fc(feat(t=99)), "CA")
        m.check_country("CA", fs1, info1, None)  # one odd item is too small a sample to judge
        fs, info = m.parse_country(fc(*[feat(_id=str(i), name=str(i)) for i in range(5)]), "BE")
        with self.assertRaises(m.OpenAipError):
            m.check_country("BE", fs, info, 100)
        m.check_country("BE", fs, info, 6)

    def test_pack_deterministic(self):
        fs, _ = m.parse_country(fc(feat()), "BE")
        a, b = m.pack_bytes("BE", fs), m.pack_bytes("BE", fs)
        self.assertEqual(a, b)
        body = json.loads(gzip.decompress(a))
        self.assertTrue(body["personalUseOnly"])
        self.assertEqual(body["usage"], "non-commercial")

    def test_run_skip_without_access(self):
        with tempfile.TemporaryDirectory() as d:
            rc = m.run(Path(d), ["US"], getter=lambda url, h=None: None)
            self.assertEqual(rc, 0)
            self.assertFalse((Path(d) / "index.json").exists())

    def test_run_writes_and_skips_covered(self):
        calls = []
        def getter(url, h=None):
            calls.append(url)
            return fc(*[feat(_id=str(i), name=str(i)) for i in range(6)])
        with tempfile.TemporaryDirectory() as d:
            rc = m.run(Path(d), ["US", "BE"], getter=getter)
            self.assertEqual(rc, 0)
            self.assertEqual(len(calls), 1)  # BE covered by OFMA
            idx = json.loads((Path(d) / "index.json").read_text())
            self.assertEqual([r["region"] for r in idx["regions"]], ["US"])
            self.assertFalse(idx["commercialUseAllowed"])
            self.assertTrue((Path(d) / "US.json.gz").is_file())

    def test_run_error_keeps_good_country(self):
        def getter(url, h=None):
            if "/us_" in url:
                return fc(*[feat(_id=str(i), name=str(i)) for i in range(6)])
            return fc(*[feat(t=99, _id=str(i), name=str(i)) for i in range(5)])
        with tempfile.TemporaryDirectory() as d:
            rc = m.run(Path(d), ["US", "CA"], getter=getter)
            self.assertEqual(rc, 1)
            self.assertTrue((Path(d) / "US.json.gz").is_file())
            self.assertFalse((Path(d) / "CA.json.gz").exists())

    def test_api_fallback_needs_key(self):
        def getter(url, h=None):
            if "storage.openaip" in url:
                return None
            self.assertEqual(h["x-openaip-api-key"], "k")
            return json.dumps({"items": [feat()["properties"] | {"geometry": feat()["geometry"]}], "totalPages": 1}).encode()
        self.assertIsNone(m.fetch_country("US", None, getter))
        got = m.fetch_country("US", "k", getter)
        self.assertEqual(len(got["items"]), 1)


if __name__ == "__main__":
    unittest.main()
