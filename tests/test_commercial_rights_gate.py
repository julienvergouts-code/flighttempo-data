import json
import tempfile
import unittest
from pathlib import Path

from scripts.enforce_app_manifest_rights import enforce, rights_block_reason
from scripts.validate_navigation_csvs import redistribution_block_reason


class CommercialRightsGateTests(unittest.TestCase):
    def test_mixed_airport_provenance_is_blocked(self):
        dataset = {
            "id": "airport_reference",
            "available": True,
            "licenseStatus": "mixed_source_review_required",
        }
        self.assertEqual(rights_block_reason(dataset), "mixed_source_review_required")
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "navigation_manifest.json"
            manifest_path.write_text(json.dumps({
                "datasets": [
                    {**dataset, "path": "airports/airports.csv", "downloadUrl": "https://example.test/data.csv"},
                    {"id": "ourairports_airports", "available": True, "licenseStatus": "public_domain"},
                ]
            }), encoding="utf-8")
            blocked = enforce(manifest_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn("airport_reference", blocked)
        restricted = next(item for item in manifest["datasets"] if item["id"] == "airport_reference")
        self.assertFalse(restricted["available"])
        self.assertNotIn("downloadUrl", restricted)
        self.assertTrue(next(item for item in manifest["datasets"] if item["id"] == "ourairports_airports")["available"])

    def test_unconfirmed_procedure_reuse_is_blocked_by_validator(self):
        self.assertEqual(
            redistribution_block_reason({"licenseStatus": "public_redistribution_not_confirmed"}),
            "public_redistribution_not_confirmed",
        )
        self.assertEqual(
            redistribution_block_reason({"licenseStatus": "declared_redistributable_check_required"}),
            "declared_redistributable_check_required",
        )

    def test_commercial_open_licences_are_not_mistaken_for_blocked_rights(self):
        self.assertIsNone(rights_block_reason({
            "license": "Licence Ouverte / Open Licence",
            "licenseStatus": "verified_open_license_commercial_reuse",
        }))
        self.assertIsNone(rights_block_reason({
            "license": "OFMA General Users License",
            "licenseStatus": "commercial_use_permitted_subject_to_OFMA_GUL",
        }))


if __name__ == "__main__":
    unittest.main()
