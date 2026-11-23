import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "pipeline"))
import fetch_faa_nasr_ifr as nasr  # noqa: E402
import register_faa_nasr_ifr_manifest as reg  # noqa: E402
from enforce_app_manifest_rights import enforce  # noqa: E402
from tests import test_fetch_faa_nasr_ifr as fixtures  # noqa: E402


class RegisterTests(unittest.TestCase):
    def setUp(self):
        self._floors = (nasr.MIN_FIXES, nasr.MIN_NAVAIDS, nasr.MIN_SEGMENTS)
        nasr.MIN_FIXES, nasr.MIN_NAVAIDS, nasr.MIN_SEGMENTS = 1, 1, 1
        self.tmp = tempfile.mkdtemp()
        zips, archives = fixtures.build_sample_zips(self.tmp)
        self.data = Path(self.tmp) / "faa_nasr"
        nasr.run(date(2026, 11, 26), zips, archives, self.data)
        self.manifest = Path(self.tmp) / "navigation_manifest.json"
        self.manifest.write_text(json.dumps({"datasets": [], "statistics": {}, "capabilities": {}, "dataSources": []}))

    def tearDown(self):
        nasr.MIN_FIXES, nasr.MIN_NAVAIDS, nasr.MIN_SEGMENTS = self._floors
        shutil.rmtree(self.tmp, ignore_errors=True)

    def load(self):
        return json.loads(self.manifest.read_text())

    def test_registers_three_downloadable_public_domain_datasets_in_cycle(self):
        reg.register(today=date(2026, 12, 1), data_dir=self.data, manifest_path=self.manifest)
        m = self.load()
        ids = {d["id"]: d for d in m["datasets"]}
        self.assertEqual(set(ids), {"faa_nasr_fixes", "faa_nasr_navaids", "faa_nasr_airway_segments"})
        for d in ids.values():
            self.assertTrue(d["available"])
            self.assertTrue(d["downloadUrl"].startswith("https://raw.githubusercontent.com/"))
            self.assertEqual(d["licenseStatus"], "public_domain")
            self.assertEqual((d["effectiveDate"], d["expiryDate"]), ("2026-11-26", "2026-12-23"))
            self.assertFalse(d["operationallyAvailable"])
        self.assertTrue(m["capabilities"]["faaNasrAirwaySegments"])
        self.assertEqual(m["statistics"]["faaNasrAirwaySegments"], 2)

    def test_registration_is_idempotent_and_replaces_not_duplicates(self):
        for _ in range(2):
            reg.register(today=date(2026, 12, 1), data_dir=self.data, manifest_path=self.manifest)
        self.assertEqual(len(self.load()["datasets"]), 3)
        self.assertEqual(len(self.load()["dataSources"]), 3)

    def test_expired_cycle_is_not_downloadable(self):
        reg.register(today=date(2027, 1, 5), data_dir=self.data, manifest_path=self.manifest)
        for d in self.load()["datasets"]:
            self.assertFalse(d["available"])
            self.assertNotIn("downloadUrl", d)

    def test_rights_gate_blocks_expired_cycle_and_clears_capability(self):
        reg.register(today=date(2026, 12, 1), data_dir=self.data, manifest_path=self.manifest)
        blocked = enforce(self.manifest, today=date(2027, 1, 5))
        self.assertIn("faa_nasr_airway_segments", blocked)
        m = self.load()
        self.assertFalse(m["capabilities"]["faaNasrAirwaySegments"])
        self.assertTrue(all(not d["available"] for d in m["datasets"]))

    def test_rights_gate_keeps_in_cycle_datasets(self):
        reg.register(today=date(2026, 12, 1), data_dir=self.data, manifest_path=self.manifest)
        blocked = enforce(self.manifest, today=date(2026, 12, 1))
        self.assertNotIn("faa_nasr_fixes", blocked)
        self.assertTrue(all(d["available"] for d in self.load()["datasets"]))

    def test_tampered_csv_is_rejected(self):
        (self.data / "fixes.csv").write_text((self.data / "fixes.csv").read_text() + "X,1,1,,,,x,2026-11-26\n")
        with self.assertRaises(ValueError):
            reg.register(today=date(2026, 12, 1), data_dir=self.data, manifest_path=self.manifest)


if __name__ == "__main__":
    unittest.main()
