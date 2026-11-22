#!/usr/bin/env python3
"""Repository regression tests for retained, non-operational EASA source records."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EasaAirspaceCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.czibs = json.loads(
            (ROOT / "airspace/advisories/easa_czibs.json").read_text(encoding="utf-8")
        )
        cls.directives = json.loads(
            (ROOT / "airspace/advisories/easa_safety_directives.json").read_text(encoding="utf-8")
        )
        cls.manifest = json.loads(
            (ROOT / "navigation_manifest.json").read_text(encoding="utf-8")
        )

    def test_russia_czib_keeps_exact_five_explicit_firs(self):
        expected = {"UUWV", "URRV", "ULLL", "USSV", "UWWW"}
        source = next(x for x in self.czibs["records"] if x["sourceId"] == "141480")
        self.assertEqual(set(source["explicitFirCodes"]), expected)

    def test_incomplete_russia_geometry_is_not_published(self):
        by_id = {x["id"]: x for x in self.manifest["datasets"]}
        self.assertFalse(by_id["easa_czibs"]["available"])
        self.assertNotIn("downloadUrl", by_id["easa_czibs"])
        self.assertFalse(self.manifest["capabilities"]["conflictZoneAdvisories"])
        self.assertFalse((ROOT / "airspace/airspace_filter.json").exists())

    def test_minsk_safety_directives_remain_separate_operator_scope_records(self):
        records = self.directives["records"]
        self.assertEqual({x["sourceId"] for x in records}, {"SD-2021-02", "SD-2021-03"})
        for record in records:
            self.assertEqual(record["instrumentType"], "EASA Safety Directive")
            self.assertEqual(record["affectedFirs"][0]["firCode"], "UMMV")
            self.assertFalse(record["affectedFirs"][0]["geometryAvailable"])
            self.assertIn("unforeseen circumstances", record["exception"])

    def test_safety_directives_are_not_downloadable_without_commercial_rights_review(self):
        item = next(x for x in self.manifest["datasets"] if x["id"] == "easa_safety_directives")
        self.assertFalse(item["available"])
        self.assertNotIn("downloadUrl", item)
        self.assertFalse(item["operationallyAvailable"])

    def test_noncommercial_openaip_filter_is_absent(self):
        self.assertFalse((ROOT / "navigation/airspace/openaip_fir_boundaries.geojson").exists())
        self.assertFalse((ROOT / "airspace/airspace_filter.json").exists())


if __name__ == "__main__":
    unittest.main()
