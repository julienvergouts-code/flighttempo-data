import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import enforce_app_manifest_rights as mod


class AppManifestRightsTests(unittest.TestCase):
    def test_mixed_source_airport_reference_is_blocked_but_cc0_source_stays_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "navigation_manifest.json"
            path.write_text(json.dumps({
                "datasets": [
                    {
                        "id": "airport_reference",
                        "available": True,
                        "downloadUrl": "https://example.test/legacy-airports.csv",
                        "licenseStatus": "mixed_source_review_required",
                    },
                    {
                        "id": "ourairports_airports",
                        "available": True,
                        "downloadUrl": "https://example.test/ourairports.csv",
                        "licenseStatus": "public_domain",
                    },
                ],
                "statistics": {
                    "airports": 29747,
                    "ourairportsAirports": 86377,
                    "airportReferenceRecords": 29747,
                },
                "airportReferenceEnrichment": {"recordCount": 29747},
            }), encoding="utf-8")

            with patch.object(mod, "MANIFEST", path):
                blocked = mod.enforce()

            manifest = json.loads(path.read_text(encoding="utf-8"))
            legacy, clean = manifest["datasets"]
            self.assertEqual(blocked, ["airport_reference"])
            self.assertFalse(legacy["available"])
            self.assertNotIn("downloadUrl", legacy)
            self.assertIn("provenance", legacy["downloadBlockReason"])
            self.assertEqual(legacy["status"], "not_published_redistribution_rights_unconfirmed_or_non_commercial_only")
            self.assertTrue(clean["available"])
            self.assertEqual(manifest["statistics"]["airports"], 86377)
            self.assertNotIn("airportReferenceRecords", manifest["statistics"])
            self.assertEqual(manifest["developmentOnlyStatistics"]["airportReferenceRecords"], 29747)
            self.assertFalse(manifest["airportReferenceEnrichment"]["appDownloadable"])

    def test_stale_global_navdata_and_derived_graph_are_not_app_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "navigation_manifest.json"
            ids = ["flightgear_fixes", "flightgear_navaids", "flightgear_airway_segments", "world_corridor_graph"]
            path.write_text(json.dumps({
                "datasets": [
                    {"id": dataset_id, "available": True, "downloadUrl": "https://example.test/data"}
                    for dataset_id in ids
                ],
                "capabilities": {
                    "independentWaypoints": True,
                    "publishedAirways": True,
                    "legacyGlobalFixes": True,
                    "legacyGlobalNavaids": True,
                    "legacyGlobalAirways": True,
                    "legacyGlobalIlsFacilities": True,
                    "flightgearNavaids": True,
                    "worldCorridorGraph": True,
                },
                "statistics": {
                    "ifrWaypoints": 113356,
                    "flightgearNavaids": 26599,
                    "airwaySegments": 70291,
                    "lowAirwaySegments": 37195,
                    "highAirwaySegments": 33096,
                    "airports": 86377,
                },
            }), encoding="utf-8")

            with patch.object(mod, "MANIFEST", path):
                blocked = mod.enforce()

            manifest = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(blocked), set(ids))
            for dataset in manifest["datasets"]:
                self.assertFalse(dataset["available"])
                self.assertFalse(dataset["operationallyAvailable"])
                self.assertNotIn("downloadUrl", dataset)
                self.assertIn("2012.08", dataset["downloadBlockReason"])
            self.assertFalse(any(manifest["capabilities"][key] for key in (
                "independentWaypoints", "publishedAirways", "legacyGlobalFixes",
                "legacyGlobalNavaids", "legacyGlobalAirways", "legacyGlobalIlsFacilities", "flightgearNavaids",
                "worldCorridorGraph",
            )))
            self.assertEqual(manifest["statistics"]["airports"], 86377)
            self.assertNotIn("ifrWaypoints", manifest["statistics"])
            self.assertEqual(manifest["developmentOnlyStatistics"]["airwaySegments"], 70291)


if __name__ == "__main__":
    unittest.main()
