import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import register_terrain_world_manifest as reg  # noqa: E402

META = {"format": "FTTR", "cellsPerDegree": 400, "cellSizeArcSeconds": 9.0, "heightUnit": "metre",
        "rowOrder": "north_to_south", "elevationMeaning": "m", "source": "s", "license": "l",
        "attribution": "a", "disclaimer": "d", "modificationNotice": "mod", "notice": "n"}


def block(i, n=2):
    return {"id": i, "bbox": [0, 0, 10, 10], "file": f"terrain-{i}.zip", "url": "u", "tileCount": n,
            "sizeBytes": 100, "sha256": "0" * 64, "tiles": ["N00E000"] * n}


class Tests(unittest.TestCase):
    def setup(self, t, confirmed):
        t = Path(t)
        (t / "meta.json").write_text(json.dumps(META))
        (t / "conf.json").write_text(json.dumps({"commercialUseConfirmed": confirmed,
                                                 "confirmedBy": "x" if confirmed else None, "licenceUrl": "http://l"}))
        (t / "manifest.json").write_text(json.dumps({"datasets": []}))
        return t

    def test_merge_keeps_other_blocks_and_replaces_same_id(self):
        with tempfile.TemporaryDirectory() as t:
            t = self.setup(t, False)
            reg.merge_index([block("N00E000", 1), block("N10E000", 1)], t / "w.json", t / "meta.json")
            idx = reg.merge_index([block("N00E000", 5)], t / "w.json", t / "meta.json")
            self.assertEqual({b["id"]: b["tileCount"] for b in idx["blocks"]}, {"N00E000": 5, "N10E000": 1})

    def test_unconfirmed_is_blocked_confirmed_is_available(self):
        for confirmed in (False, True):
            with tempfile.TemporaryDirectory() as t:
                t = self.setup(t, confirmed)
                reg.merge_index([block("N00E000", 3)], t / "w.json", t / "meta.json")
                e = reg.register(t / "w.json", t / "conf.json", t / "manifest.json")
                self.assertEqual(e["available"], confirmed)
                self.assertEqual(e["recordCount"], 3)
                m = json.loads((t / "manifest.json").read_text())
                self.assertEqual(m["capabilities"]["terrainWorld"], confirmed)
                self.assertEqual("commercialUseAllowed" in e, confirmed)


if __name__ == "__main__":
    unittest.main()
