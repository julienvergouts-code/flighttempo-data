import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "pipeline"))
import register_terrain_manifest as reg  # noqa: E402
import commercial_rights  # noqa: E402

INDEX = {"cellsPerDegree": 400, "format": "FTTR", "license": "Copernicus DEM free licence (GLO-30)",
         "attribution": "© DLR ... Produced using Copernicus WorldDEM-30.", "disclaimer": "no liability",
         "modificationNotice": "max pooled",
         "regions": [{"id": "alps", "name": "Alps", "bbox": [45, 6, 47, 7], "tileCount": 2, "sizeBytes": 1000, "tiles": []}]}


class RegisterTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        r = Path(self.td.name)
        self.dir_path = r
        self.index, self.conf, self.manifest = r / "index.json", r / "conf.json", r / "m.json"
        self.index.write_text(json.dumps(INDEX))
        self.manifest.write_text(json.dumps({"datasets": [], "capabilities": {}}))

    def tearDown(self):
        self.td.cleanup()

    def conf_write(self, confirmed, by=None):
        self.conf.write_text(json.dumps({"commercialUseConfirmed": confirmed, "confirmedBy": by,
                                         "licenceUrl": "https://example.org/licence.pdf"}))

    def test_blocked_until_owner_confirms(self):
        self.conf_write(False)
        entry = reg.register(self.index, self.conf, self.manifest, scope_path=self.dir_path / 'none.json')
        self.assertFalse(entry["available"])
        self.assertNotIn("downloadUrl", entry)
        self.assertIsNotNone(commercial_rights.redistribution_block_reason(entry))

    def test_flag_without_a_name_does_not_count(self):
        self.conf_write(True, None)
        self.assertFalse(reg.register(self.index, self.conf, self.manifest, scope_path=self.dir_path / 'none.json')["available"])

    def test_confirmed_is_available_with_attribution(self):
        self.conf_write(True, "Julien Vergouts")
        entry = reg.register(self.index, self.conf, self.manifest, scope_path=self.dir_path / 'none.json')
        self.assertTrue(entry["available"])
        self.assertIsNone(commercial_rights.redistribution_block_reason(entry))
        self.assertIn("WorldDEM-30", entry["attribution"])
        again = reg.register(self.index, self.conf, self.manifest, scope_path=self.dir_path / 'none.json')
        self.assertEqual(len(json.loads(self.manifest.read_text())["datasets"]), 1)

    def test_real_confirmation_file_is_unconfirmed_by_default(self):
        data = json.loads((ROOT / "data/terrain_rights_confirmation.json").read_text())
        self.assertFalse(data["commercialUseConfirmed"])

    def test_personal_scope_opens_it_as_non_commercial_only(self):
        self.conf_write(False)
        scope = self.dir_path / "scope.json"
        scope.write_text(json.dumps({"scope": "personal", "confirmedBy": "owner"}))
        entry = reg.register(self.index, self.conf, self.manifest, scope_path=scope)
        self.assertTrue(entry["available"])
        self.assertIs(entry["personalUseOnly"], True)
        self.assertIs(entry["commercialUseAllowed"], False)
        self.assertEqual(entry["status"], "personal_use_only")

    def test_personal_scope_needs_a_named_owner(self):
        self.conf_write(False)
        scope = self.dir_path / "scope.json"
        scope.write_text(json.dumps({"scope": "personal"}))
        self.assertFalse(reg.register(self.index, self.conf, self.manifest, scope_path=scope)["available"])


if __name__ == "__main__":
    unittest.main()
