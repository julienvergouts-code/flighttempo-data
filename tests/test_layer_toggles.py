import json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import layer_toggles as lt


def ds(i, available=True, **kw):
    return {"id": i, "available": available, "recordCount": 10, **kw}


class T(unittest.TestCase):
    cfg = {"layers": [
        {"id": "a", "label": "A", "group": "g", "datasets": ["x", "y"], "defaultOn": True},
        {"id": "b", "label": "B", "group": "g", "datasets": ["p"], "defaultOn": True},
        {"id": "c", "label": "C", "group": "g", "datasets": ["l"], "defaultOn": True},
        {"id": "d", "label": "D", "group": "g", "datasets": ["gone"], "defaultOn": True},
    ], "priority": {"airspace": ["x"]}}

    def test_layers(self):
        m = {"datasets": [ds("x"), ds("y", False, downloadBlockReason="blocked"), ds("p", personalUseOnly=True),
                          ds("l", legacyFallback=True, personalUseOnly=True)]}
        out = lt.build_layers(m, self.cfg)
        L = {l["id"]: l for l in out["layers"]}
        self.assertTrue(L["a"]["userToggle"])
        self.assertEqual(L["a"]["availableDatasets"], ["x"])
        self.assertEqual(L["a"]["unavailableDatasets"], [{"id": "y", "reason": "blocked"}])
        self.assertEqual(L["a"]["tier"], "commercial_or_public")
        self.assertEqual(L["b"]["tier"], "personal_use_only")
        self.assertEqual(L["c"]["tier"], "legacy_fallback")
        self.assertFalse(L["d"]["userToggle"])
        self.assertFalse(L["d"]["defaultOn"])  # cannot default on when nothing is available
        self.assertEqual(out["masterSwitches"]["personalUseData"]["layers"], ["b", "c"])
        self.assertEqual(out["layerPriority"], {"airspace": ["x"]})

    def test_blocked_dataset_cannot_be_toggled_on(self):
        m = {"datasets": [ds("x", False), ds("y", False), ds("p", False), ds("l", False)]}
        self.assertTrue(all(not l["userToggle"] for l in lt.build_layers(m, self.cfg)["layers"]))

    def test_real_config_refers_to_known_datasets(self):
        manifest = json.loads((ROOT / "navigation_manifest.json").read_text())
        ids = {d["id"] for d in manifest["datasets"]}
        cfg = json.loads((ROOT / "data" / "layer_toggles.json").read_text())
        for layer in cfg["layers"]:
            for i in layer["datasets"]:
                self.assertIn(i, ids, f"{layer['id']} -> {i}")
        seen = [i for layer in cfg["layers"] for i in layer["datasets"]]
        self.assertEqual(len(seen), len(set(seen)), "a dataset belongs to one layer only")


if __name__ == "__main__":
    unittest.main()
