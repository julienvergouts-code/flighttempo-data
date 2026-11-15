import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import import_easa_czibs, import_openaip_firs


class RussiaBelarusAdvisoryMappingTests(unittest.TestCase):
    def _feature(self, feature_id, code, name):
        return {
            "type": "Feature",
            "id": feature_id,
            "geometry": {"type": "Polygon", "coordinates": []},
            "properties": {
                "name": name,
                "country": "RU",
                "flightTempoFirCode": code,
            },
        }

    def test_russia_mapping_uses_exact_five_firs_from_czib(self):
        features = [
            self._feature(2310, "UMKK", "KALININGRAD FIR"),
            self._feature(2448, "UWWW", "SAMARA FIR"),
            self._feature(2450, "UKFV", "SIMFEROPOL FIR"),
            self._feature(2458, "URRV", "ROSTOV-NA-DONU FIR"),
        ]
        mapped = import_openaip_firs.build_russia_advisory_mapping(
            {"sourceId": "141480"}, features
        )
        self.assertEqual(
            [x["firCode"] for x in mapped["affectedFirs"]],
            ["UUWV", "URRV", "ULLL", "USSV", "UWWW"],
        )
        self.assertNotIn("UMKK", [x["firCode"] for x in mapped["affectedFirs"]])
        self.assertNotIn("UKFV", [x["firCode"] for x in mapped["affectedFirs"]])

    def test_partial_or_unverified_russian_geometry_fails_closed(self):
        features = [
            self._feature(2448, "UWWW", "SAMARA FIR"),
            self._feature(2458, "URRV", "ROSTOV-NA-DONU FIR"),
        ]
        mapped = import_openaip_firs.build_russia_advisory_mapping(
            {"sourceId": "141480"}, features
        )
        self.assertFalse(mapped["geometryCoverageComplete"])
        self.assertFalse(mapped["routeAvoidanceReady"])
        self.assertEqual(
            {x["firCode"] for x in mapped["affectedFirs"] if not x["geometryAvailable"]},
            {"UUWV", "ULLL", "USSV"},
        )
        active = import_openaip_firs.build_active_firs([{
            "sourceId": "141480", "country": "Russia", **mapped
        }])
        self.assertEqual(active, [])

    def test_belarus_is_separate_operator_specific_safety_guidance(self):
        directives = import_easa_czibs.BELARUS_OPERATOR_SPECIFIC_ADVISORIES
        self.assertEqual(
            {x["sourceId"] for x in directives},
            {"EASA_SD_2021_02", "EASA_SD_2021_03", "EASA_SIB_2021_10"},
        )
        for directive in directives:
            self.assertEqual(directive["affectedFirs"][0]["firCode"], "UMMV")
            self.assertFalse(directive["routeAvoidanceReady"])
            self.assertIn("unforeseen circumstances", directive["exception"])

    def test_russia_geometry_requires_all_firs_verified_and_clipped(self):
        codes = [("UUWV", "MOSCOW FIR"), ("URRV", "ROSTOV-NA-DONU FIR"),
                 ("ULLL", "SANKT-PETERSBURG FIR"), ("USSV", "YEKATERINBURG FIR"),
                 ("UWWW", "SAMARA FIR")]
        features = []
        for idx, (code, name) in enumerate(codes, start=1):
            feature = self._feature(idx, code, name)
            feature["properties"]["flightTempoVerifiedAgainstStateAip"] = True
            feature["properties"]["flightTempoClippedAt60E"] = code != "UWWW"
            features.append(feature)
        mapped = import_openaip_firs.build_russia_advisory_mapping(
            {"sourceId": "141480"}, features
        )
        self.assertFalse(mapped["routeAvoidanceReady"])
        features[-1]["properties"]["flightTempoClippedAt60E"] = True
        mapped = import_openaip_firs.build_russia_advisory_mapping(
            {"sourceId": "141480"}, features
        )
        self.assertTrue(mapped["geometryCoverageComplete"])
        self.assertTrue(mapped["routeAvoidanceReady"])


if __name__ == "__main__":
    unittest.main()
