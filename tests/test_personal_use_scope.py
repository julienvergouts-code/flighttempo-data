import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import commercial_rights as cr  # noqa: E402

PERSONAL = {"id": "x", "license": "Some free licence", "licenseStatus": "free_personal_use_only_commercial_unverified",
            "status": "personal_use_only", "personalUseOnly": True, "commercialUseAllowed": False}


class ScopeTests(unittest.TestCase):
    def scope(self, t, data):
        p = Path(t) / "scope.json"
        if data is not None:
            p.write_text(json.dumps(data))
        return p

    def test_scope_needs_personal_and_a_named_owner(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertTrue(cr.personal_scope_active(self.scope(t, {"scope": "personal", "confirmedBy": "me"})))
            self.assertFalse(cr.personal_scope_active(self.scope(t, {"scope": "personal"})))
            self.assertFalse(cr.personal_scope_active(self.scope(t, {"scope": "commercial", "confirmedBy": "me"})))
            self.assertFalse(cr.personal_scope_active(Path(t) / "missing.json"))

    def test_marked_dataset_passes_only_in_personal_scope(self):
        self.assertIsNone(cr.redistribution_block_reason(PERSONAL, personal_scope=True))
        self.assertEqual(cr.redistribution_block_reason(PERSONAL, personal_scope=False), "commercial_reuse_not_confirmed")

    def test_unmarked_or_commercial_blocked_dataset_is_not_rescued(self):
        plain = {"id": "y", "licenseStatus": "unknown"}
        self.assertEqual(cr.redistribution_block_reason(plain, personal_scope=True), "commercial_reuse_not_confirmed")
        nc = dict(PERSONAL, license="CC BY-NC 4.0")
        self.assertEqual(cr.redistribution_block_reason(nc, personal_scope=True), "cc by-nc")

    def test_real_repo_scope_file_names_the_owner(self):
        data = json.loads((ROOT / "data" / "usage_scope.json").read_text(encoding="utf-8"))
        self.assertEqual(data["scope"], "personal")
        self.assertTrue(data["confirmedBy"])


if __name__ == "__main__":
    unittest.main()
