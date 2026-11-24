import json
import tempfile
import unittest
from datetime import date
from unittest import mock
from pathlib import Path

from scripts.commercial_rights import redistribution_block_reason
from scripts.enforce_app_manifest_rights import enforce
import scripts.enforce_app_manifest_rights as enforce_module


class CommercialRightsGateTests(unittest.TestCase):
    def test_mixed_airport_provenance_is_blocked(self):
        dataset = {
            "id": "airport_reference",
            "available": True,
            "licenseStatus": "mixed_source_review_required",
        }
        self.assertEqual(
            redistribution_block_reason(dataset), "mixed_source_review_required"
        )

    def test_unknown_reuse_terms_fail_closed(self):
        self.assertEqual(
            redistribution_block_reason({
                "id": "unreviewed_source",
                "available": True,
                "license": "source acknowledgement",
            }),
            "commercial_reuse_not_confirmed",
        )

    def test_unconfirmed_specific_marker_is_reported_precisely(self):
        self.assertEqual(
            redistribution_block_reason({
                "licenseStatus": "public_redistribution_not_confirmed",
            }),
            "public_redistribution_not_confirmed",
        )

    def test_verified_free_commercial_sources_are_allowed(self):
        for dataset in (
            {"licenseStatus": "public_domain"},
            {"licenseStatus": "CC0_structured_data"},
            {
                "license": "Licence Ouverte / Open Licence",
                "licenseStatus": "verified_exact_eAIP_product_linked_to_open_license",
            },
            {
                "license": "OFMA General Users License",
                "licenseStatus": "commercial_use_permitted_subject_to_OFMA_GUL",
                "commercialUseAllowed": True,
            },
            {"id": "airline_profiles", "licenseStatus": "owner_authored_profile"},
            {"id": "route_policy", "license": "FlightTempo original configuration"},
        ):
            self.assertIsNone(redistribution_block_reason(dataset), dataset)

    def test_gate_blocks_unlicensed_and_stale_datasets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "navigation_manifest.json"
            path.write_text(json.dumps({
                "datasets": [
                    {
                        "id": "airport_reference",
                        "available": True,
                        "licenseStatus": "mixed_source_review_required",
                        "downloadUrl": "https://example.test/airports.csv",
                    },
                    {
                        "id": "flightgear_fixes",
                        "available": True,
                        "licenseStatus": "declared_redistributable_check_required",
                        "dataCycle": "2012.08",
                        "downloadUrl": "https://example.test/fixes.csv",
                    },
                    {
                        "id": "easa_czibs",
                        "available": True,
                        "license": "EASA acknowledgement only",
                        "downloadUrl": "https://example.test/czibs.json",
                    },
                    {
                        "id": "approaches",
                        "available": True,
                        "licenseStatus": "public_domain",
                        "status": "present_unverified_test_only",
                        "downloadUrl": "https://example.test/approaches.csv",
                    },
                    {
                        "id": "ourairports_airports",
                        "available": True,
                        "licenseStatus": "public_domain",
                        "downloadUrl": "https://example.test/airports.csv",
                    },
                ],
                "capabilities": {
                    "independentWaypoints": True,
                    "flightgearNavaids": True,
                    "conflictZoneAdvisories": True,
                },
                "statistics": {"ifrWaypoints": 100},
            }), encoding="utf-8")
            with mock.patch.object(enforce_module, "legacy_fallback_config", return_value={}):
                blocked = enforce(path, today=date(2026, 11, 22))
            manifest = json.loads(path.read_text(encoding="utf-8"))

        self.assertIn("airport_reference", blocked)
        self.assertIn("flightgear_fixes", blocked)
        self.assertIn("easa_czibs", blocked)
        self.assertIn("approaches", blocked)
        by_id = {item["id"]: item for item in manifest["datasets"]}
        for dataset_id in ("airport_reference", "flightgear_fixes", "easa_czibs", "approaches"):
            self.assertFalse(by_id[dataset_id]["available"])
            self.assertNotIn("downloadUrl", by_id[dataset_id])
        self.assertTrue(by_id["ourairports_airports"]["available"])
        self.assertFalse(manifest["capabilities"]["independentWaypoints"])
        self.assertFalse(manifest["capabilities"]["flightgearNavaids"])
        self.assertFalse(manifest["capabilities"]["conflictZoneAdvisories"])
        self.assertNotIn("ifrWaypoints", manifest["statistics"])
        self.assertEqual(manifest["developmentOnlyStatistics"]["ifrWaypoints"], 100)

    def test_unpublished_until_effective_and_after_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "navigation_manifest.json"
            path.write_text(json.dumps({
                "datasets": [
                    {
                        "id": "faa_vfr_reporting_points",
                        "available": True,
                        "licenseStatus": "public_domain",
                        "effectiveDate": "2026-11-26",
                        "expiryDate": "2026-12-23",
                        "downloadUrl": "https://example.test/vfr.csv",
                    },
                    {
                        "id": "sids",
                        "available": True,
                        "licenseStatus": "public_domain",
                        "effectiveDate": "2026-10-29",
                        "expiryDate": "2026-11-25",
                        "downloadUrl": "https://example.test/sids.csv",
                    },
                ],
                "capabilities": {"sids": True},
            }), encoding="utf-8")
            blocked = enforce(path, today=date(2026, 11, 26))
            manifest = json.loads(path.read_text(encoding="utf-8"))

        self.assertIn("sids", blocked)
        self.assertNotIn("faa_vfr_reporting_points", blocked)
        by_id = {item["id"]: item for item in manifest["datasets"]}
        self.assertFalse(by_id["sids"]["available"])
        self.assertNotIn("downloadUrl", by_id["sids"])
        self.assertTrue(by_id["faa_vfr_reporting_points"]["available"])
        self.assertFalse(manifest["capabilities"]["sids"])


if __name__ == "__main__":
    unittest.main()
