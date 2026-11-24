import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import commercial_rights as cr  # noqa: E402
import register_adsb_observed_manifest as r  # noqa: E402


class T(unittest.TestCase):
    def setup(self, d, scope):
        d = Path(d)
        (d / "i.json").write_text(json.dumps({"routeCount": 4, "airportPairs": 3, "flightsCounted": 9, "sizeBytes": 10,
            "sha256": "ab", "file": "observed_routes.json.gz", "sourceUrl": "u", "licenseUrl": "l", "attribution": "a"}))
        (d / "m.json").write_text(json.dumps({"datasets": [], "capabilities": {}}))
        (d / "s.json").write_text(json.dumps(scope))
        return d

    def test_personal_passes_gate_and_is_never_commercial(self):
        with tempfile.TemporaryDirectory() as t:
            d = self.setup(t, {"scope": "personal", "confirmedBy": "me"})
            e = r.register(d / "i.json", d / "m.json", d / "s.json")
            self.assertTrue(e["available"])
            self.assertFalse(e["commercialUseAllowed"])
            self.assertIsNone(cr.redistribution_block_reason(e, True))
            self.assertIsNotNone(cr.redistribution_block_reason(e, False))
            self.assertTrue(json.loads((d / "m.json").read_text())["capabilities"]["adsbObservedRoutes"])

    def test_other_scope_unavailable(self):
        with tempfile.TemporaryDirectory() as t:
            d = self.setup(t, {"scope": "commercial"})
            e = r.register(d / "i.json", d / "m.json", d / "s.json")
            self.assertFalse(e["available"])
            self.assertNotIn("downloadUrl", e)

    def test_missing_index_unregisters(self):
        with tempfile.TemporaryDirectory() as t:
            d = self.setup(t, {"scope": "personal", "confirmedBy": "me"})
            r.register(d / "i.json", d / "m.json", d / "s.json")
            (d / "i.json").unlink()
            self.assertIsNone(r.register(d / "i.json", d / "m.json", d / "s.json"))
            m = json.loads((d / "m.json").read_text())
            self.assertEqual(m["datasets"], [])
            self.assertFalse(m["capabilities"]["adsbObservedRoutes"])


if __name__ == "__main__":
    unittest.main()
