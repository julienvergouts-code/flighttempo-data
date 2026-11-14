import csv
import tempfile
import unittest
from pathlib import Path

from scripts import build_aviation_db as builder
from scripts import enrich_airport_reference as enrichment


class OurAirportsFullFieldExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.stage = Path(self.temp.name)
        self.original_minimums = dict(builder.MINIMUM_RECORDS)
        builder.MINIMUM_RECORDS.update({
            "airports": 1,
            "runways": 1,
            "navaids": 1,
        })

    def tearDown(self):
        builder.MINIMUM_RECORDS.update(self.original_minimums)
        self.temp.cleanup()

    def read_export(self, relative):
        with (self.stage / relative).open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_airport_export_retains_all_source_fields(self):
        record = {
            "id": "123",
            "ident": "EGLL",
            "type": "large_airport",
            "name": "London Heathrow",
            "latitude_deg": "51.4700",
            "longitude_deg": "-0.4543",
            "elevation_ft": "83",
            "continent": "EU",
            "iso_country": "GB",
            "iso_region": "GB-ENG",
            "municipality": "London",
            "scheduled_service": "yes",
            "gps_code": "EGLL",
            "iata_code": "LHR",
            "local_code": "",
            "home_link": "https://example.test",
            "wikipedia_link": "https://en.wikipedia.org/wiki/Heathrow",
            "keywords": "Heathrow;London"
        }
        builder.build_airports([record], self.stage)
        row = self.read_export("navigation/airports/ourairports_airports.csv")[0]
        self.assertEqual(row["icao"], "EGLL")
        self.assertEqual(row["source_id"], "123")
        self.assertEqual(row["source_iso_region"], "GB-ENG")
        self.assertEqual(row["source_iata_code"], "LHR")
        self.assertEqual(row["source_keywords"], "Heathrow;London")

    def test_runway_export_retains_both_ends_and_source_details(self):
        record = {
            "id": "456",
            "airport_ref": "123",
            "airport_ident": "EGLL",
            "length_ft": "12802",
            "width_ft": "164",
            "surface": "ASP",
            "lighted": "1",
            "closed": "0",
            "le_ident": "09L",
            "le_latitude_deg": "51.4775",
            "le_longitude_deg": "-0.4890",
            "le_elevation_ft": "79",
            "le_heading_degT": "89.5",
            "le_displaced_threshold_ft": "0",
            "he_ident": "27R",
            "he_latitude_deg": "51.4770",
            "he_longitude_deg": "-0.4350",
            "he_elevation_ft": "82",
            "he_heading_degT": "269.5",
            "he_displaced_threshold_ft": "0"
        }
        builder.build_runways([record], self.stage)
        row = self.read_export("navigation/runways/runways_parsed.csv")[0]
        self.assertEqual(row["length_ft"], "12802")
        self.assertEqual(row["width_ft"], "164")
        self.assertEqual(row["source_le_latitude_deg"], "51.4775")
        self.assertEqual(row["source_he_elevation_ft"], "82")
        self.assertEqual(row["source_he_displaced_threshold_ft"], "0")
        self.assertEqual(row["source_id"], "456")


    def test_airport_reference_lookup_keeps_source_metadata_and_elevation(self):
        source = [{
            "id": "123",
            "ident": "EGLL",
            "icao_code": "",
            "gps_code": "EGLL",
            "type": "large_airport",
            "continent": "EU",
            "iso_country": "GB",
            "iso_region": "GB-ENG",
            "municipality": "London",
            "scheduled_service": "yes",
            "iata_code": "LHR",
            "local_code": "",
            "home_link": "https://example.test",
            "wikipedia_link": "https://en.wikipedia.org/wiki/Heathrow",
            "keywords": "Heathrow",
            "elevation_ft": "83"
        }]
        elevations, metadata = enrichment.build_airport_lookups(source)
        self.assertEqual(elevations["EGLL"], 83)
        self.assertEqual(metadata["EGLL"]["ourairportsId"], "123")
        self.assertEqual(metadata["EGLL"]["isoRegion"], "GB-ENG")
        self.assertEqual(metadata["EGLL"]["scheduledService"], "yes")

    def test_airport_reference_runway_details_keep_both_ends(self):
        source = [{
            "id": "456",
            "airport_ident": "EGLL",
            "closed": "0",
            "le_ident": "09L",
            "he_ident": "27R",
            "length_ft": "12802",
            "width_ft": "164",
            "surface": "ASP",
            "lighted": "1",
            "le_latitude_deg": "51.4775",
            "le_longitude_deg": "-0.4890",
            "le_elevation_ft": "79",
            "le_displaced_threshold_ft": "0",
            "le_heading_degT": "89.5",
            "he_latitude_deg": "51.4770",
            "he_longitude_deg": "-0.4350",
            "he_elevation_ft": "82",
            "he_displaced_threshold_ft": "100",
            "he_heading_degT": "269.5"
        }]
        lookup = enrichment.build_runway_lookup(source)
        item = lookup["EGLL"][0]
        self.assertEqual(item["pair"], "09L/27R")
        self.assertEqual(item["allRunwayWidthsFt"], "164")
        self.assertEqual(item["allRunwayLELatitudes"], "51.4775")
        self.assertEqual(item["allRunwayHEDisplacedThresholdsFt"], "100")
        self.assertEqual(enrichment.pipe_values(lookup["EGLL"], "allRunwayHEElevationsFt"), "82")

    def test_navaid_export_retains_all_source_fields(self):
        record = {
            "id": "789",
            "filename": "earth_nav.dat",
            "ident": "LAM",
            "name": "Lambourne",
            "type": "VOR-DME",
            "frequency_khz": "115500",
            "dme_frequency_khz": "115500",
            "dme_channel": "102X",
            "latitude_deg": "51.655",
            "longitude_deg": "0.152",
            "elevation_ft": "300",
            "dme_latitude_deg": "51.655",
            "dme_longitude_deg": "0.152",
            "dme_elevation_ft": "300",
            "iso_country": "GB",
            "slaved_variation_deg": "1.2",
            "magnetic_variation_deg": "1.1",
            "usageType": "HIGH",
            "power": "HIGH",
            "associated_airport": ""
        }
        builder.build_navaids([record], self.stage)
        row = self.read_export("navigation/navaids/navaids.csv")[0]
        self.assertEqual(row["ident"], "LAM")
        self.assertEqual(row["source_id"], "789")
        self.assertEqual(row["source_filename"], "earth_nav.dat")
        self.assertEqual(row["source_usageType"], "HIGH")


if __name__ == "__main__":
    unittest.main()
