import gzip
import json
import math
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "scripts"))
import import_ofma_airspace as mod  # noqa: E402
import register_ofma_airspace_manifest as reg  # noqa: E402

XML = b"""<OFMX-Snapshot>
<Ase><AseUid mid="1" region="LF"><codeType>CTR</codeType><codeId>CDG1</codeId></AseUid>
 <txtName>PARIS CDG</txtName><codeClass>D</codeClass>
 <codeDistVerUpper>ALT</codeDistVerUpper><valDistVerUpper>2500</valDistVerUpper><uomDistVerUpper>FT</uomDistVerUpper>
 <codeDistVerLower>HEI</codeDistVerLower><valDistVerLower>0</valDistVerLower><uomDistVerLower>FT</uomDistVerLower></Ase>
<Abd><AbdUid><AseUid mid="1" region="LF"/></AbdUid>
 <Avx><codeType>GRC</codeType><geoLat>490000N</geoLat><geoLong>0020000E</geoLong></Avx>
 <Avx><codeType>GRC</codeType><geoLat>490000N</geoLat><geoLong>0030000E</geoLong></Avx>
 <Avx><codeType>CWA</codeType><geoLat>484000N</geoLat><geoLong>0030000E</geoLong><geoLatArc>485000N</geoLatArc><geoLongArc>0030000E</geoLongArc><valRadiusArc>10</valRadiusArc><uomRadiusArc>NM</uomRadiusArc></Avx>
 <Avx><codeType>GRC</codeType><geoLat>484000N</geoLat><geoLong>0020000E</geoLong></Avx></Abd>
<Ase><AseUid mid="2" region="LF"><codeType>D</codeType><codeId>D1</codeId></AseUid><txtName>ROUND</txtName>
 <codeDistVerUpper>STD</codeDistVerUpper><valDistVerUpper>195</valDistVerUpper><uomDistVerUpper>FL</uomDistVerUpper>
 <codeDistVerLower>ALT</codeDistVerLower><valDistVerLower>1000</valDistVerLower><uomDistVerLower>FT</uomDistVerLower></Ase>
<Abd><AbdUid><AseUid mid="2"/></AbdUid><Circle><geoLatCen>480000N</geoLatCen><geoLongCen>0010000E</geoLongCen><valRadius>5</valRadius><uomRadius>NM</uomRadius></Circle></Abd>
<Ase><AseUid mid="3"><codeType>TMA</codeType><codeId>T1</codeId></AseUid><txtName>BORDER</txtName></Ase>
<Abd><AbdUid><AseUid mid="3"/></AbdUid>
 <Avx><codeType>GRC</codeType><geoLat>470000N</geoLat><geoLong>0010000E</geoLong></Avx>
 <Avx><codeType>FNT</codeType><geoLat>470000N</geoLat><geoLong>0020000E</geoLong></Avx>
 <Avx><codeType>GRC</codeType><geoLat>460000N</geoLat><geoLong>0020000E</geoLong></Avx></Abd>
<Ase><AseUid mid="4"><codeType>FIR</codeType><codeId>LFFF</codeId></AseUid><txtName>PARIS FIR</txtName></Ase>
<Ase><AseUid mid="5"><codeType>R</codeType><codeId>R5</codeId></AseUid><txtName>NO BOUNDARY</txtName></Ase>
</OFMX-Snapshot>"""


class GeometryTests(unittest.TestCase):
    def test_arc_stays_on_radius_and_ends_at_target(self):
        centre = (48.0, 3.0)
        start, end = mod.destination(*centre, 0, 10), mod.destination(*centre, 90, 10)
        pts = mod.arc_points(start, end, centre, 10, clockwise=True)
        self.assertEqual(pts[-1], end)
        for p in pts:
            self.assertAlmostEqual(mod.distance_nm(*centre, *p), 10, delta=0.05)
        self.assertGreaterEqual(len(pts), 30)  # 90 degrees at 3 degree steps

    def test_counter_clockwise_goes_the_long_way(self):
        centre = (48.0, 3.0)
        start, end = mod.destination(*centre, 0, 10), mod.destination(*centre, 90, 10)
        self.assertGreater(len(mod.arc_points(start, end, centre, 10, clockwise=False)), 80)

    def test_circle_ring_is_closed(self):
        ring = mod.circle_ring((48.0, 1.0), 5)
        self.assertEqual(ring[0], ring[-1])
        self.assertEqual(len(ring), 121)


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.features, self.info = mod.parse_airspace(XML, "LF")
        self.by_name = {f["name"]: f for f in self.features}

    def test_expected_features_only(self):
        self.assertEqual(set(self.by_name), {"PARIS CDG", "ROUND", "BORDER"})  # FIR excluded, no-boundary dropped
        self.assertEqual(self.info["stats"]["no_boundary"], 1)
        self.assertNotIn("geometry_failed", self.info["stats"])
        self.assertEqual(self.info["stats"]["excluded_type"], 1)

    def test_vertical_limits(self):
        cdg, rnd = self.by_name["PARIS CDG"], self.by_name["ROUND"]
        self.assertEqual(cdg["upper"], {"ft": 2500, "ref": "MSL"})
        self.assertEqual(cdg["lower"], {"ft": 0, "ref": "AGL"})
        self.assertEqual(rnd["upper"], {"ft": 19500, "ref": "FL"})

    def test_arc_expanded_and_ring_closed(self):
        ring = self.by_name["PARIS CDG"]["rings"][0]
        self.assertEqual(ring[0], ring[-1])
        self.assertGreater(len(ring), 20)

    def test_border_following_is_flagged(self):
        self.assertTrue(self.by_name["BORDER"].get("approx"))
        self.assertNotIn("approx", self.by_name["PARIS CDG"])

    def test_border_segment_follows_published_border_line(self):
        xml = b"""<OFMX-Snapshot>
<Gbr><GbrUid><txtName>A_B</txtName></GbrUid>
 <Gbv><geoLat>50.00N</geoLat><geoLong>005.00E</geoLong></Gbv>
 <Gbv><geoLat>50.10N</geoLat><geoLong>005.10E</geoLong></Gbv>
 <Gbv><geoLat>50.20N</geoLat><geoLong>005.05E</geoLong></Gbv>
 <Gbv><geoLat>50.30N</geoLat><geoLong>005.20E</geoLong></Gbv></Gbr>
<Ase><AseUid mid="9" region="EB"><codeType>CTA</codeType><codeId>X</codeId></AseUid><txtName>B</txtName>
 <codeDistVerUpper>STD</codeDistVerUpper><valDistVerUpper>195</valDistVerUpper><uomDistVerUpper>FL</uomDistVerUpper>
 <codeDistVerLower>ALT</codeDistVerLower><valDistVerLower>2500</valDistVerLower><uomDistVerLower>FT</uomDistVerLower></Ase>
<Abd><AbdUid><AseUid mid="9" region="EB"/></AbdUid>
 <Avx><codeType>GRC</codeType><geoLat>50.00N</geoLat><geoLong>005.00E</geoLong></Avx>
 <Avx><GbrUid><txtName>A_B</txtName></GbrUid><codeType>FNT</codeType><geoLat>50.30N</geoLat><geoLong>005.20E</geoLong></Avx>
 <Avx><codeType>GRC</codeType><geoLat>50.30N</geoLat><geoLong>004.80E</geoLong></Avx>
 <Avx><codeType>GRC</codeType><geoLat>50.00N</geoLat><geoLong>004.80E</geoLong></Avx></Abd>
</OFMX-Snapshot>"""
        feats, info = mod.parse_airspace(xml, "EB")
        self.assertEqual(len(feats), 1)
        self.assertFalse(feats[0].get("approx"))
        self.assertEqual(info["stats"]["border_segments_resolved"], 1)
        ring = feats[0]["rings"][0] if "rings" in feats[0] else feats[0]["geometry"][0]
        self.assertIn([50.1, 5.1], [list(p) for p in ring])

    def test_unresolved_border_is_not_counted_as_failure(self):
        xml = b"""<OFMX-Snapshot>
<Ase><AseUid mid="9" region="EB"><codeType>CTA</codeType><codeId>X</codeId></AseUid><txtName>B</txtName></Ase>
<Abd><AbdUid><AseUid mid="9" region="EB"/></AbdUid>
 <Avx><codeType>GRC</codeType><geoLat>50.00N</geoLat><geoLong>005.00E</geoLong></Avx>
 <Avx><GbrUid><txtName>NOPE</txtName></GbrUid><codeType>FNT</codeType><geoLat>50.30N</geoLat><geoLong>005.20E</geoLong></Avx>
 <Avx><codeType>GRC</codeType><geoLat>50.00N</geoLat><geoLong>005.00E</geoLong></Avx></Abd>
</OFMX-Snapshot>"""
        feats, info = mod.parse_airspace(xml, "EB")
        self.assertEqual(feats, [])
        self.assertEqual(info["stats"]["unresolved_border"], 1)
        self.assertEqual(info["stats"].get("considered", 0), 0)
        self.assertEqual(info["stats"].get("geometry_failed", 0), 0)

    def test_point_only_airspace_is_not_a_failure(self):
        xml = b"""<OFMX-Snapshot>
<Ase><AseUid mid="7" region="EB"><codeType>D-OTHER</codeType><codeId>P1</codeId></AseUid><txtName>P</txtName></Ase>
<Abd><AbdUid><AseUid mid="7" region="EB"/></AbdUid>
 <Avx><codeType>GRC</codeType><geoLat>48.5N</geoLat><geoLong>000.5E</geoLong></Avx></Abd>
</OFMX-Snapshot>"""
        feats, info = mod.parse_airspace(xml, "EB")
        self.assertEqual(feats, [])
        self.assertEqual(info["stats"]["point_only"], 1)
        self.assertEqual(info["stats"].get("geometry_failed", 0), 0)

    def test_ids_are_stable(self):
        again, _ = mod.parse_airspace(XML, "LF")
        self.assertEqual([f["id"] for f in again], [f["id"] for f in self.features])

    def test_arc_that_opens_the_boundary_starts_at_the_closing_vertex(self):
        xml = b"""<OFMX-Snapshot>
<Ase><AseUid mid="9"><codeType>ATZ</codeType><codeId>A9</codeId></AseUid><txtName>ARC FIRST</txtName></Ase>
<Abd><AbdUid><AseUid mid="9"/></AbdUid>
 <Avx><codeType>CWA</codeType><geoLat>490000N</geoLat><geoLong>0030000E</geoLong><geoLatArc>490000N</geoLatArc><geoLongArc>0020000E</geoLongArc><valRadiusArc>30</valRadiusArc><uomRadiusArc>NM</uomRadiusArc></Avx>
 <Avx><codeType>GRC</codeType><geoLat>480000N</geoLat><geoLong>0030000E</geoLong></Avx>
 <Avx><codeType>GRC</codeType><geoLat>480000N</geoLat><geoLong>0020000E</geoLong></Avx>
 <Avx><codeType>GRC</codeType><geoLat>490000N</geoLat><geoLong>0021000E</geoLong></Avx></Abd>
<Ase><AseUid mid="10"><codeType>R</codeType><codeId>A10</codeId></AseUid><txtName>FULL CIRCLE BY ARC</txtName></Ase>
<Abd><AbdUid><AseUid mid="10"/></AbdUid>
 <Avx><codeType>CWA</codeType><geoLat>490000N</geoLat><geoLong>0030000E</geoLong><geoLatArc>490000N</geoLatArc><geoLongArc>0020000E</geoLongArc><valRadiusArc>30</valRadiusArc><uomRadiusArc>NM</uomRadiusArc></Avx></Abd>
</OFMX-Snapshot>"""
        features, info = mod.parse_airspace(xml, "LF")
        by = {f["name"]: f for f in features}
        self.assertEqual(set(by), {"ARC FIRST", "FULL CIRCLE BY ARC"})
        self.assertGreater(len(by["FULL CIRCLE BY ARC"]["rings"][0]), 100)
        self.assertNotIn("geometry_failed", info["stats"])

    def test_no_ase_fails_closed(self):
        with self.assertRaisesRegex(mod.AirspaceError, "no Ase"):
            mod.parse_airspace(b"<OFMX-Snapshot/>", "LF")


class GuardTests(unittest.TestCase):
    def test_floor_and_geometry_rate(self):
        features, info = mod.parse_airspace(XML, "LF")
        old = mod.MIN_FEATURES
        try:
            mod.MIN_FEATURES = 10
            with self.assertRaisesRegex(mod.AirspaceError, "floor"):
                mod.check_region("LF", features, info)
            mod.MIN_FEATURES = 1
            info["stats"]["considered"] = 100
            with self.assertRaisesRegex(mod.AirspaceError, "geometry resolved"):
                mod.check_region("LF", features, info)
        finally:
            mod.MIN_FEATURES = old


class RunTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.config = self.root / "sources.json"
        self.config.write_text(json.dumps({"regions": [{
            "region": "LF", "regionName": "France", "regionCode": "LF", "regionKey": "lf", "archiveKey": "lf",
            "sourcePage": "https://openflightmaps.org/downloads/lf/", "license": "OFMA_GUL"}]}))
        self.out = self.root / "ofma"
        self.old_min = mod.MIN_FEATURES
        mod.MIN_FEATURES = 1
        mod.MIN_GEOMETRY_SUCCESS, self.old_success = 0.5, mod.MIN_GEOMETRY_SUCCESS

    def tearDown(self):
        mod.MIN_FEATURES = self.old_min
        mod.MIN_GEOMETRY_SUCCESS = self.old_success
        self.td.cleanup()

    def run_it(self, xml=XML):
        return mod.run(self.config, today=date(2026, 11, 23), out_dir=self.out, fetcher=lambda s, a: xml)

    def test_publish_and_idempotence(self):
        self.run_it()
        index = json.loads((self.out / "index.json").read_text())
        self.assertEqual((index["cycle"], index["effectiveDate"], index["expiryDate"]),
                         ("2611", "2026-10-29", "2026-11-25"))
        pack = json.loads(gzip.decompress((self.out / "LF.json.gz").read_bytes()))
        self.assertEqual(len(pack["features"]), 3)
        self.assertIn("open flightmaps", pack["attribution"])
        before = (self.out / "index.json").read_bytes(), (self.out / "LF.json.gz").read_bytes()
        self.run_it()
        self.assertEqual(before, ((self.out / "index.json").read_bytes(), (self.out / "LF.json.gz").read_bytes()))

    def test_skips_when_cycle_already_published(self):
        self.run_it()
        calls = []
        mod.run(self.config, today=date(2026, 11, 23), out_dir=self.out, fetcher=lambda s, a: calls.append(1) or XML)
        self.assertEqual(calls, [])

    def test_failure_keeps_previous_pack(self):
        self.run_it()
        before = (self.out / "LF.json.gz").read_bytes()
        with self.assertRaises(mod.AirspaceError):
            mod.run(self.config, today=date(2026, 11, 23), out_dir=self.out, fetcher=lambda s, a: b"<OFMX-Snapshot/>", force=True)
        self.assertEqual(before, (self.out / "LF.json.gz").read_bytes())

    def test_registration_marks_availability_by_cycle_and_verifies_hashes(self):
        self.run_it()
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({"datasets": [], "capabilities": {}}))
        entry = reg.register(date(2026, 11, 23), self.out, manifest)
        self.assertTrue(entry["available"])
        self.assertIn("downloadUrl", entry)
        entry = reg.register(date(2026, 11, 26), self.out, manifest)
        self.assertFalse(entry["available"])
        self.assertNotIn("downloadUrl", entry)
        (self.out / "LF.json.gz").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "does not match"):
            reg.register(date(2026, 11, 23), self.out, manifest)


if __name__ == "__main__":
    unittest.main()
