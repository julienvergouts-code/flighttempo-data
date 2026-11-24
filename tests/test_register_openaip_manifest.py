import json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import register_openaip_manifest as r
import commercial_rights as cr


class T(unittest.TestCase):
    def setup(self, t, scope):
        t = Path(t)
        (t / "i.json").write_text(json.dumps({"licenseUrl": "u", "attribution": "a", "alterations": ["x"],
            "regions": [{"region": "US", "featureCount": 3, "sizeBytes": 10}]}))
        (t / "m.json").write_text(json.dumps({"datasets": [], "capabilities": {}}))
        (t / "s.json").write_text(json.dumps(scope))
        return t

    def test_personal_available_and_passes_gate(self):
        with tempfile.TemporaryDirectory() as d:
            t = self.setup(d, {"scope": "personal", "confirmedBy": "me"})
            e = r.register(t / "i.json", t / "m.json", t / "s.json")
            self.assertTrue(e["available"])
            self.assertIsNone(cr.redistribution_block_reason(e, True))
            self.assertIsNotNone(cr.redistribution_block_reason(e, False))
            self.assertFalse(e["commercialUseAllowed"])
            self.assertTrue(json.loads((t / "m.json").read_text())["capabilities"]["openaipAirspace"])

    def test_not_personal_unavailable(self):
        with tempfile.TemporaryDirectory() as d:
            t = self.setup(d, {"scope": "commercial"})
            e = r.register(t / "i.json", t / "m.json", t / "s.json")
            self.assertFalse(e["available"])
            self.assertNotIn("downloadUrl", e)

    def test_missing_index_removes_dataset(self):
        with tempfile.TemporaryDirectory() as d:
            t = self.setup(d, {"scope": "personal", "confirmedBy": "me"})
            r.register(t / "i.json", t / "m.json", t / "s.json")
            (t / "i.json").unlink()
            self.assertIsNone(r.register(t / "i.json", t / "m.json", t / "s.json"))
            m = json.loads((t / "m.json").read_text())
            self.assertEqual(m["datasets"], [])
            self.assertFalse(m["capabilities"]["openaipAirspace"])


if __name__ == "__main__":
    unittest.main()
