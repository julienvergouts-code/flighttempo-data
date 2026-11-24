import json, sys, tempfile, unittest, zipfile
from pathlib import Path
try:
    import numpy as np
except ImportError:  # generic regression runs have no numpy; the terrain workflows install it
    raise unittest.SkipTest("numpy not installed")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import build_world_viewer_data as v
import terrain_tiles as tt


class T(unittest.TestCase):
    def test_height_roundtrip(self):
        for m in (0, 100, 1000, 4000, 8848):
            p = v.encode_height(np.array([m]))[0]
            self.assertLess(abs(v.decode_height(float(p)) - m), 120)

    def test_png_signature_and_size(self):
        png = v.png_gray(np.zeros((4, 6), dtype=np.uint8))
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")

    def test_overview_places_tile(self):
        g = np.zeros((tt.CELLS, tt.CELLS), dtype=np.int16)
        g[0, 0] = 3000
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            with zipfile.ZipFile(d / "b.zip", "w") as z:
                z.writestr("N47E011.fttr", tt.encode_tile(47, 11, g))
            h, n = v.build_overview(d)
        self.assertEqual(n, 1)
        row = (v.LAT_TOP - 48) * v.CPD
        col = (11 + 180) * v.CPD
        self.assertEqual(int(h[row, col]), 3000)
        self.assertEqual(int(h.max()), 3000)

    def test_great_circle_and_profile(self):
        pts = v.gc_points((50.9, 4.5), (25.25, 55.36), 10)
        self.assertAlmostEqual(pts[0][0], 50.9, 1)
        total = sum(v.dist_nm(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        self.assertTrue(2400 < total < 2800)  # BRU-DXB about 2,650 NM
        h = np.zeros(((v.LAT_TOP - v.LAT_BOTTOM) * v.CPD, 360 * v.CPD), dtype=np.int16)
        r, c = int((v.LAT_TOP - pts[5][0]) * v.CPD), int((pts[5][1] + 180) * v.CPD)
        h[r, c] = 2000
        prof = v.profile(h, pts, 20)
        self.assertEqual(max(p["m"] for p in prof), 2000)

    def test_feature_near(self):
        line = [(50.0, 4.0 + i * 0.05) for i in range(21)]
        f = {"bbox": [49.9, 4.4, 50.1, 4.6], "rings": [[[49.9, 4.4], [49.9, 4.6], [50.1, 4.6], [50.1, 4.4], [49.9, 4.4]]]}
        far = {"bbox": [10, 10, 11, 11], "rings": [[[10, 10], [10, 11], [11, 11], [11, 10], [10, 10]]]}
        self.assertTrue(v.feature_near(f, [line], 10))
        self.assertFalse(v.feature_near(far, [line], 10))


class AirportTests(unittest.TestCase):
    def test_window_and_png(self):
        g = np.zeros((tt.CELLS, tt.CELLS), dtype=np.int16)
        g[200, 100] = 1234
        tiles = {(50, 4): g, (50, 3): g * 0, (49, 4): g * 0, (49, 3): g * 0}
        ids = v.airport_tile_ids(50.5, 4.0)
        self.assertEqual(ids, {(50, 3), (50, 4), (49, 3), (49, 4)} - {(49, 3), (49, 4)} | {(50, 3), (50, 4)})
        w = v.airport_window(tiles, 50.5, 4.0)
        self.assertEqual(w.shape, (tt.CELLS, tt.CELLS))
        self.assertEqual(int(w.max()), 1234)
        png = v.png_rgb16(w)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIsNone(v.airport_window({}, 50.5, 4.0))

    def test_rgb16_roundtrip(self):
        import zlib
        a = np.array([[0, 1234], [-20, 4800]], dtype=np.int16)
        png = v.png_rgb16(a)
        i = png.index(b"IDAT")
        n = int.from_bytes(png[i - 4:i], "big")
        raw = zlib.decompress(png[i + 4:i + 4 + n])
        rows = [raw[k * 7 + 1:(k + 1) * 7] for k in range(2)]
        vals = [(r[c * 3] * 256 + r[c * 3 + 1]) - v.HEIGHT_OFFSET for r in rows for c in range(2)]
        self.assertEqual(vals, [0, 1234, -20, 4800])


if __name__ == "__main__":
    unittest.main()
