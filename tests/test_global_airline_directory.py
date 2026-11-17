import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_global_airline_directory.py"
SPEC = importlib.util.spec_from_file_location("airline_builder", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GlobalAirlineDirectoryTests(unittest.TestCase):
    def test_normalizes_codes_and_status(self):
        binding = {
            "item": {"value": "http://www.wikidata.org/entity/Q123"},
            "itemLabel": {"value": "Example Air"},
            "iataValues": {"value": "xy|XY|bad"},
            "icaoValues": {"value": "exa|EXA|long"},
            "callsignValues": {"value": "EXAMPLE|Example"},
            "countryValues": {"value": "Exampleland"},
            "inception": {"value": "2001-01-01T00:00:00Z"},
            "dissolved": {"value": ""},
        }
        row = MODULE.normalize_binding(binding)
        self.assertEqual(row["wikidataId"], "Q123")
        self.assertEqual(row["iataCodes"], ["XY"])
        self.assertEqual(row["icaoCodes"], ["EXA"])
        self.assertEqual(row["callsigns"], ["EXAMPLE"])
        self.assertEqual(row["operatingStatus"], "not_verified")

    def test_dissolved_airline_is_not_marked_active(self):
        binding = {
            "item": {"value": "http://www.wikidata.org/entity/Q456"},
            "itemLabel": {"value": "Former Air"},
            "dissolved": {"value": "2010-01-01T00:00:00Z"},
        }
        row = MODULE.normalize_binding(binding)
        self.assertEqual(row["operatingStatus"], "dissolved")

    def test_build_records_deduplicates_entity_ids(self):
        base = {
            "item": {"value": "http://www.wikidata.org/entity/Q789"},
            "itemLabel": {"value": "Merged Air"},
            "iataValues": {"value": "MA"},
        }
        second = dict(base)
        second["icaoValues"] = {"value": "MGA"}
        rows = MODULE.build_records([base, second])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["iataCodes"], ["MA"])
        self.assertEqual(rows[0]["icaoCodes"], ["MGA"])


if __name__ == "__main__":
    unittest.main()
