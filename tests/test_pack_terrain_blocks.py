import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import pack_terrain_blocks as pk  # noqa: E402


class PackTests(unittest.TestCase):
    def make(self, root: Path, names):
        for n in names:
            d = root / n[:3]
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{n}.fttr").write_bytes(b"FTTR" + n.encode())

    def test_block_ids_and_negative_coordinates(self):
        self.assertEqual(pk.block_origin(47, 11), (40, 10))
        self.assertEqual(pk.block_origin(-18, -150), (-20, -150))
        self.assertEqual(pk.block_origin(-1, -1), (-10, -10))
        self.assertEqual(pk.block_id(-20, -150), "S20W150")
        self.assertEqual(pk.tile_coords("S18W150.fttr"), (-18, -150))

    def test_pack_groups_tiles_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            self.make(t / "tiles", ["N47E011", "N47E012", "N45E006", "S18W150"])
            a = pk.pack(t / "tiles", t / "a", "https://x/y")
            b = pk.pack(t / "tiles", t / "b", "https://x/y")
            self.assertEqual([e["sha256"] for e in a], [e["sha256"] for e in b])
            ids = {e["id"]: e for e in a}
            self.assertEqual(set(ids), {"N40E010", "N40E000", "S20W150"})
            self.assertEqual(ids["N40E010"]["tiles"], ["N47E011", "N47E012"])
            self.assertEqual(ids["N40E010"]["url"], "https://x/y/terrain-N40E010.zip")
            with zipfile.ZipFile(t / "a" / "terrain-N40E010.zip") as z:
                self.assertEqual(sorted(z.namelist()), ["N47E011.fttr", "N47E012.fttr"])

    def test_empty_fails(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):
                pk.pack(Path(t), Path(t) / "o", "u")


if __name__ == "__main__":
    unittest.main()
