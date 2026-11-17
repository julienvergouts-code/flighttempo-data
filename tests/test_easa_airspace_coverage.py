#!/usr/bin/env python3
"""Repository-level regression tests for EASA Russia/Minsk advisory publication."""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EasaAirspaceCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.czibs = json.loads((ROOT / "airspace/advisories/easa_czibs.json").read_text(encoding="utf-8"))
        cls.filter_data = json.loads((ROOT / "airspace/airspace_filter.json").read_text(encoding="utf-8"))
        cls.directives = json.loads((ROOT / "airspace/advisories/easa_safety_directives.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads((ROOT / "navigation_manifest.json").read_text(encoding="utf-8"))

    def test_russia_czib_has_exact_five_explicit_firs(self):
        expected = {"UUWV", "URRV", "ULLL", "USSV", "UWWW"}
        source = next(x for x in self.czibs["records"] if x["sourceId"] == "141480")
        mapped = next(x for x in self.filter_data["activeAdvisories"] if x["sourceId"] == "141480")
        self.assertEqual(set(source["explicitFirCodes"]), expected)
        self.assertEqual(set(mapped["affectedFirs"][i]["firCode"] for i in range(len(mapped["affectedFirs"]))), expected)
        self.assertNotIn("UMKK", expected)
        self.assertNotIn("UKFV", expected)

    def test_incomplete_russia_geometry_is_not_activated_for_route_avoidance(self):
        mapped = next(x for x in self.filter_data["activeAdvisories"] if x["sourceId"] == "141480")
        self.assertFalse(mapped["routeAvoidanceReady"])
        active = [x for x in self.filter_data["activeFirs"] if x.get("sourceAdvisoryId") == "141480"]
        self.assertTrue(all(not x.get("geometryAvailable", False) for x in active))
        self.assertTrue(all(x.get("geometryFeatureId") is None for x in active))

    def test_minsk_safety_directives_are_separate_operator_scope_records(self):
        records = self.directives["records"]
        self.assertEqual({x["sourceId"] for x in records}, {"SD-2021-02", "SD-2021-03"})
        for record in records:
            self.assertEqual(record["instrumentType"], "EASA Safety Directive")
            self.assertEqual(record["affectedFirs"][0]["firCode"], "UMMV")
            self.assertFalse(record["affectedFirs"][0]["geometryAvailable"])
            self.assertIn("unforeseen circumstances", record["exception"])

    def test_safety_directives_are_downloadable_as_reference_only(self):
        item = next(x for x in self.manifest["datasets"] if x["id"] == "easa_safety_directives")
        path = ROOT / item["path"]
        self.assertTrue(item["available"])
        self.assertFalse(item["operationallyAvailable"])
        self.assertEqual(item["recordCount"], 2)
        self.assertEqual(item["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_mixed_openaip_airspace_filter_is_not_in_app_download_manifest(self):
        item = next(x for x in self.manifest["datasets"] if x["id"] == "airspace_filter")
        self.assertFalse(item["available"])
        self.assertNotIn("downloadUrl", item)


if __name__ == "__main__":
    unittest.main()
