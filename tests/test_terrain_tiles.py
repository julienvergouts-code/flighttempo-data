import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import terrain_tiles as tt  # noqa: E402
import build_terrain_tiles as bt  # noqa: E402


class PoolTests(unittest.TestCase):
    def test_peak_survives_pooling_where_averaging_would_lose_it(self):
        src = np.full((1200, 1200), 300, dtype=np.float32)
        src[601, 733] = 4806.4
        pooled = tt.max_pool(src)
        self.assertEqual(int(tt.to_int16_metres(pooled).max()), 4807)  # rounded UP
        mean = src.reshape(400, 3, 400, 3).mean(axis=(1, 3))
        self.assertLess(mean.max(), 1000)  # the naive method would have hidden the peak

    def test_never_lower_than_any_source_sample_even_when_not_divisible(self):
        rng = np.random.default_rng(7)
        for shape in ((1200, 1200), (800, 800), (600, 600), (240, 240), (120, 120), (1200, 600)):
            src = rng.integers(0, 4000, shape).astype(np.float32)
            pooled = tt.max_pool(src)
            rows, cols = shape
            for r, c in [(0, 0), (rows - 1, cols - 1), (rows // 2, cols // 3), (rows - 1, 0)]:
                i, j = min(399, int(r * 400 / rows)), min(399, int(c * 400 / cols))
                self.assertGreaterEqual(pooled[i, j], src[r, c], (shape, r, c))
            self.assertEqual(pooled.max(), src.max())

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            tt.max_pool(np.zeros((0, 5)))


class CodecTests(unittest.TestCase):
    def grid(self):
        rng = np.random.default_rng(3)
        g = np.cumsum(rng.integers(-5, 6, (400, 400)), axis=1) + 500
        return np.clip(g, -400, 8800).astype(np.int16)

    def test_round_trip_and_naming(self):
        g = self.grid()
        la, lo, out = tt.decode_tile(tt.encode_tile(-18, -150, g))
        self.assertEqual((la, lo), (-18, -150))
        self.assertTrue((out == g).all())
        self.assertEqual(tt.tile_name(-18, -150), "S18W150")
        self.assertEqual(tt.tile_relpath(45, 6), "tiles/N45/N45E006.fttr")

    def test_corruption_is_detected(self):
        data = bytearray(tt.encode_tile(45, 6, self.grid()))
        data[0:4] = b"XXXX"
        with self.assertRaises(ValueError):
            tt.decode_tile(bytes(data))
        data = tt.encode_tile(45, 6, self.grid())
        with self.assertRaises(Exception):
            tt.decode_tile(data[:-50])


def fake_reader_factory(peak_lat=45.5, peak_lon=6.5, peak=4806.0):
    def reader(raw):
        arr = np.full((1200, 1200), 100.0, dtype=np.float32)
        if raw == b"peak":
            r, c = int((1 - (peak_lat - math.floor(peak_lat))) * 1200), int((peak_lon - math.floor(peak_lon)) * 1200)
            arr[r, c] = peak
        return arr
    return reader


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.cfg_path = self.root / "cfg.json"
        self.cfg = {
            "source": {"bucket": "https://x", "urlPattern": "{bucket}/{ns}{lat:02d}{ew}{lon:03d}"},
            "regions": [{"id": "alps", "name": "Alps", "south": 45, "west": 6, "north": 47, "east": 7}],
            "canaries": [{"name": "Peak", "lat": 45.5, "lon": 6.5, "minM": 4700, "maxM": 4900}],
        }
        self.cfg_path.write_text(json.dumps(self.cfg))
        self.out = self.root / "out"

    def tearDown(self):
        self.td.cleanup()

    def downloader(self, url):
        if url.endswith("N45E006"):
            return b"peak"
        if url.endswith("N46E006"):
            return None  # open water / missing tile
        raise AssertionError(url)

    def test_end_to_end_index_and_idempotence(self):
        calls = []
        def dl(url):
            calls.append(url)
            return self.downloader(url)
        bt.run(self.cfg_path, self.out, None, workers=2, downloader=dl, reader=fake_reader_factory())
        index = json.loads((self.out / "index.json").read_text())
        region = index["regions"][0]
        self.assertEqual([t["id"] for t in region["tiles"]], ["N45E006"])
        self.assertEqual(region["tiles"][0]["maxM"], 4806)
        self.assertIn("Copernicus", index["attribution"])
        self.assertIn("Produced using Copernicus WorldDEM-90", index["attribution"])
        self.assertTrue(index["modificationNotice"])
        first = (self.out / "tiles/N45/N45E006.fttr").read_bytes()
        calls.clear()
        bt.run(self.cfg_path, self.out, None, workers=2, downloader=dl, reader=fake_reader_factory())
        self.assertEqual((self.out / "tiles/N45/N45E006.fttr").read_bytes(), first)
        self.assertEqual(len(calls), 1)  # only the missing (absent) tile is retried

    def test_canary_failure_blocks_the_index(self):
        with self.assertRaisesRegex(bt.TerrainError, "canary"):
            bt.run(self.cfg_path, self.out, None, workers=1, downloader=self.downloader,
                   reader=fake_reader_factory(peak=2000.0))
        self.assertFalse((self.out / "index.json").exists())

    def test_route_query_reports_the_peak_and_missing_tiles(self):
        bt.run(self.cfg_path, self.out, None, workers=1, downloader=self.downloader, reader=fake_reader_factory())
        over = tt.max_elevation_along(self.out, [(45.5, 6.2), (45.5, 6.8)])
        self.assertGreaterEqual(over["maxM"], 4806)
        self.assertEqual(over["maxFt"], round(4806 * 3.280839895))
        beside = tt.max_elevation_along(self.out, [(45.9, 6.2), (45.9, 6.8)])
        self.assertLess(beside["maxM"], 200)
        # a one-NM corridor from a parallel track still sees the peak
        near = tt.max_elevation_along(self.out, [(45.52, 6.2), (45.52, 6.8)], corridor_nm=3)
        self.assertGreaterEqual(near["maxM"], 4806)
        gap = tt.max_elevation_along(self.out, [(46.5, 6.2), (46.5, 6.8)])
        self.assertIsNone(gap["maxM"])
        self.assertEqual(gap["missingTiles"], ["N46E006"])


class ConfigTests(unittest.TestCase):
    def test_real_config_is_sane(self):
        cfg = json.loads((ROOT / "data/terrain_regions.json").read_text())
        url = bt.source_url(cfg, -18, -150)
        self.assertTrue(url.endswith("Copernicus_DSM_COG_30_S18_00_W150_00_DEM/Copernicus_DSM_COG_30_S18_00_W150_00_DEM.tif"))
        for r in cfg["regions"]:
            self.assertLess(r["south"], r["north"])
            self.assertLess(r["west"], r["east"])
        self.assertGreaterEqual(len(cfg["canaries"]), 3)


if __name__ == "__main__":
    unittest.main()
