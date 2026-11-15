#!/usr/bin/env python3
"""Regression checks for EASA Russia/Minsk advisory scope and manifest integrity."""

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

    def test_russia_czib_uses_only_the_five_easa_fir_codes(self):
        expected = {"UUWV", "URRV", "ULLL", "USSV", "UWWW"}
        source = next(x for x in self.czibs["records"] if x["sourceId"] == "141480")
        mapped = next(x for x in self.filter_data["activeAdvisories"] if x["sourceId"] == "141480")
        active = {
            x["firCode"] for x in self.filter_data["activeFirs"]
            if x.get("sourceAdvisoryId") == "141480"
        }
        self.assertEqual(set(source["explicitFirCodes"]), expected)
        self.assertEqual(set(mapped["explicitFirCodes"]), expected)
        self.assertEqual(active, expected)
        self.assertNotIn("UMKK", active)
        self.assertNotIn("UKFV", active)

    def test_missing_russian_and_minsk_geometry_is_explicit(self):
        missing = {
            x["firCode"] for x in self.filter_data["missingFIRGeometry"]
        }
        self.assertTrue({"UUWV", "ULLL", "USSV", "UMMV"}.issubset(missing))
        self.assertTrue(self.filter_data["policy"]["missingGeometryHandling"].startswith("unknown_not_clear"))
        self.assertIn("UWWW", {x["firCode"] for x in self.filter_data["geometryReviewRequired"]})

    def test_minsk_is_a_separate_safety_directive_not_a_czib(self):
        directive = next(x for x in self.directives["records"] if x["sourceId"] == "SD-2021-02")
        self.assertEqual(directive["instrumentType"], "EASA Safety Directive")
        self.assertEqual(directive["affectedFirs"][0]["firCode"], "UMMV")
        self.assertFalse(directive["affectedFirs"][0]["geometryAvailable"])
        self.assertEqual(len(self.directives["records"]), 2)
        direct_easa = next(x for x in self.directives["records"] if x["sourceId"] == "SD-2021-03")
        self.assertIn("EASA has issued the AOC", direct_easa["applicability"][0])
        self.assertIn("direct_easa_competent_authority", direct_easa["routePreviewTreatment"])
        self.assertFalse(any(x.get("sourceId") in {"SD-2021-02", "SD-2021-03"} for x in self.filter_data["activeAdvisories"]))

    def test_app_manifest_exposes_directive_as_reference_only(self):
        dataset = next(x for x in self.manifest["datasets"] if x["id"] == "easa_safety_directives")
        path = ROOT / dataset["path"]
        self.assertTrue(dataset["available"])
        self.assertFalse(dataset["operationallyAvailable"])
        self.assertEqual(dataset["recordCount"], 2)
        self.assertEqual(dataset["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_airspace_filter_checksum_matches_app_manifest(self):
        dataset = next(x for x in self.manifest["datasets"] if x["id"] == "airspace_filter")
        path = ROOT / dataset["path"]
        self.assertEqual(dataset["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
