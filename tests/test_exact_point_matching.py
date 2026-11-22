import unittest

from scripts.exact_point_matching import exact_point_matches, point_key


class ExactPointMatchingTests(unittest.TestCase):
    def test_matches_same_name_and_exact_decimal_coordinates(self):
        ifr = [{"name": "  Mont   Blanc ", "latitude": "45.8326", "longitude": "6.8652"}]
        vfr = [{"name": "mont blanc", "lat": "45.832600", "lon": "6.865200"}]
        self.assertEqual(
            exact_point_matches(
                ifr, vfr,
                vfr_latitude_field="lat",
                vfr_longitude_field="lon",
            ),
            [(ifr[0], vfr[0])],
        )

    def test_rejects_same_name_with_even_a_small_coordinate_difference(self):
        ifr = [{"name": "ALPHA", "latitude": "51.200000", "longitude": "4.500000"}]
        vfr = [{"name": "alpha", "latitude": "51.200001", "longitude": "4.500000"}]
        self.assertEqual(exact_point_matches(ifr, vfr), [])

    def test_rejects_same_coordinates_with_a_different_name(self):
        ifr = [{"name": "ALPHA", "latitude": "51.2", "longitude": "4.5"}]
        vfr = [{"name": "ALPHA 1", "latitude": "51.2", "longitude": "4.5"}]
        self.assertEqual(exact_point_matches(ifr, vfr), [])

    def test_rejects_ident_only_and_invalid_coordinate_records(self):
        ifr = [{"ident": "ALPHA", "latitude": "", "longitude": ""}]
        vfr = [{"name": "ALPHA", "lat": "51.2", "lon": "4.5"}]
        self.assertEqual(exact_point_matches(
            ifr,
            vfr,
            ifr_name_field="ident",
            vfr_latitude_field="lat",
            vfr_longitude_field="lon",
        ), [])

    def test_rejects_out_of_range_coordinates(self):
        self.assertIsNone(point_key({
            "name": "ALPHA", "latitude": "91", "longitude": "4.5",
        }))


if __name__ == "__main__":
    unittest.main()
