import json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import enforce_app_manifest_rights as e
import commercial_rights as cr


class T(unittest.TestCase):
    def cfg(self, d, enabled=True):
        p = Path(d) / "c.json"
        p.write_text(json.dumps({"enabled": enabled, "datasets": {"flightgear_fixes": ["legacyGlobalFixes"]},
                                 "cycleLabel": "2012.08", "preferNewerSources": ["faa_nasr_fixes"]}))
        return p

    def test_off_outside_personal_scope_or_when_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(e.legacy_fallback_config(False, self.cfg(d)), {})
            self.assertEqual(e.legacy_fallback_config(True, self.cfg(d, False)), {})
            self.assertEqual(e.legacy_fallback_config(True, Path(d) / "missing.json"), {})

    def test_labelled_and_passes_personal_gate_only(self):
        with tempfile.TemporaryDirectory() as d:
            conf = e.legacy_fallback_config(True, self.cfg(d))
            ds = {"id": "flightgear_fixes", "license": "GPL-3.0", "licenseStatus": "declared_redistributable_check_required"}
            self.assertEqual(cr.redistribution_block_reason(ds, True), "declared_redistributable_check_required")
            e.apply_legacy_fallback(ds, conf)
            self.assertIsNone(cr.redistribution_block_reason(ds, True))
            self.assertIsNotNone(cr.redistribution_block_reason(ds, False))
            self.assertEqual(ds["dataCycle"], "2012.08")
            self.assertFalse(ds["commercialUseAllowed"])
            self.assertTrue(ds["legacyFallback"])
            self.assertIn("faa_nasr_fixes", ds["preferNewerSources"])

    def test_enforce_publishes_legacy_dataset_in_personal_scope_and_blocks_otherwise(self):
        from unittest import mock
        from datetime import date
        with tempfile.TemporaryDirectory() as d:
            conf = e.legacy_fallback_config(True, self.cfg(d))
            m = Path(d) / "m.json"
            body = {"datasets": [{"id": "flightgear_fixes", "path": "navigation/waypoints/flightgear_fixes.csv", "license": "GPL-3.0",
                                  "licenseStatus": "declared_redistributable_check_required", "status": "x"}],
                    "capabilities": {"legacyGlobalFixes": False}, "statistics": {}}
            m.write_text(json.dumps(body))
            with mock.patch.object(e, "legacy_fallback_config", return_value=conf), mock.patch.object(e, "personal_scope_active", return_value=True):
                blocked = e.enforce(m, today=date(2026, 11, 24))
            out = json.loads(m.read_text())
            self.assertNotIn("flightgear_fixes", blocked)
            self.assertTrue(out["datasets"][0]["available"])
            self.assertTrue(out["capabilities"]["legacyGlobalFixes"])
            m.write_text(json.dumps(body))
            with mock.patch.object(e, "legacy_fallback_config", return_value={}):
                blocked = e.enforce(m, today=date(2026, 11, 24))
            self.assertIn("flightgear_fixes", blocked)

    def test_real_config_covers_the_four_2012_datasets(self):
        data = json.loads((ROOT / "data" / "legacy_fallback.json").read_text())
        self.assertEqual(set(data["datasets"]), {"flightgear_fixes", "flightgear_navaids", "flightgear_airway_segments", "world_corridor_graph"})


if __name__ == "__main__":
    unittest.main()
