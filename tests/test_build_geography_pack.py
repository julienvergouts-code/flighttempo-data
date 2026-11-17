import gzip
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_geography_pack.py"
SPEC = importlib.util.spec_from_file_location("build_geography_pack", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def point_feature(name, lon, lat, **properties):
    return {
        "type": "Feature",
        "properties": {"name": name, **properties},
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


class GeographyPackTests(unittest.TestCase):
    def test_all_populated_places_are_kept_without_population_cutoff(self):
        sources = {
            "populated_places": {"features": [
                point_feature("Small Remote Town", 10.0, 20.0, pop_max=100, scalerank=10),
                point_feature("Large City", 11.0, 21.0, pop_max=1000000, scalerank=1),
            ]},
            "elevation_points": {"features": []},
            "geography_points": {"features": []},
        }
        records = MODULE.build_landmarks(sources)
        names = {item["name"] for item in records}
        self.assertIn("Small Remote Town", names)
        self.assertIn("Large City", names)

    def test_same_named_places_in_different_locations_are_preserved(self):
        sources = {
            "populated_places": {"features": [
                point_feature("Springfield", 10.0, 20.0, iso_a2="AA"),
                point_feature("Springfield", 30.0, 40.0, iso_a2="BB"),
            ]},
            "elevation_points": {"features": []},
            "geography_points": {"features": []},
        }
        records = MODULE.build_landmarks(sources)
        springfields = [item for item in records if item["name"] == "Springfield"]
        self.assertEqual(len(springfields), 2)

    def test_named_peaks_are_filtered_at_3500_ft(self):
        sources = {
            "populated_places": {"features": []},
            "elevation_points": {"features": [
                point_feature("High Peak", 5.0, 45.0, elevation=1200),
                point_feature("Low Hill", 6.0, 46.0, elevation=900),
            ]},
            "geography_points": {"features": []},
        }
        records = MODULE.build_landmarks(sources)
        peaks = {item["name"] for item in records if item["kind"] == "PEAK"}
        self.assertIn("High Peak", peaks)
        self.assertNotIn("Low Hill", peaks)

    def test_landmark_wire_format_is_array_and_deterministic_gzip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pack.json.gz"
            first_hash, first_size = MODULE.write_deterministic_gzip(path, [{"name": "Test"}])
            first_bytes = path.read_bytes()
            second_hash, second_size = MODULE.write_deterministic_gzip(path, [{"name": "Test"}])
            self.assertEqual(first_hash, second_hash)
            self.assertEqual(first_size, second_size)
            self.assertEqual(first_bytes, path.read_bytes())
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                decoded = json.load(handle)
            self.assertIsInstance(decoded, list)
            self.assertEqual(decoded[0]["name"], "Test")

    def test_hydro_features_keep_geometry_and_compact_properties(self):
        feature = {
            "type": "Feature",
            "properties": {"name": "Test River", "featurecla": "River", "unneeded": "drop"},
            "geometry": {"type": "LineString", "coordinates": [[1.123456, 2.123456], [3.0, 4.0]]},
        }
        compact = MODULE.compact_feature(feature)
        self.assertEqual(compact["properties"]["name"], "Test River")
        self.assertNotIn("unneeded", compact["properties"])
        self.assertEqual(compact["geometry"]["coordinates"][0], [1.1235, 2.1235])


if __name__ == "__main__":
    unittest.main()
