import csv
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import register_sia_designated_points_manifest as mod


class RegisterSiaDesignatedPointsTests(unittest.TestCase):
    def write_fixture(self, root: Path):
        csv_path = root / "points.csv"
        fields = ["ident", "latitude", "longitude", "code_type", "name", "remarks", "airport_icao_association", "datum", "source_provider", "source_file", "source_sha256"]
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow({"ident": "DINOX", "latitude": "46.66666667", "longitude": "6.11972222", "code_type": "OTHER", "datum": "WGS84", "source_provider": "Service de l'Information Aeronautique (SIA France)"})
        meta_path = root / "points-meta.json"
        meta_path.write_text(json.dumps({
            "sourceProvider": "Service de l'Information Aeronautique (SIA France)",
            "sourceUrl": "https://www.sia.aviation-civile.gouv.fr/product.html",
            "sourceFileUrl": "https://data.cquest.org/dgac/aip/archive.zip",
            "license": "Licence Ouverte / Open Licence (Etalab)",
            "effectiveDate": "2026-11-26",
            "expiryDate": "2026-12-23",
            "status": "reference_designated_points_not_operationally_validated",
            "coverage": "France and French overseas AIP designated points (DPN); not classified as VFR reporting points",
            "attribution": "SIA France; cycle effective 2026-11-26",
            "downloadedAtUtc": "2026-11-22T00:00:00Z",
        }), encoding="utf-8")
        manifest_path = root / "navigation_manifest.json"
        manifest_path.write_text(json.dumps({"datasets": [], "statistics": {}, "capabilities": {}, "dataSources": []}), encoding="utf-8")
        return csv_path, meta_path, manifest_path

    def test_registers_points_as_separate_reference_only_package(self):
        with tempfile.TemporaryDirectory() as temp:
            csv_path, meta_path, manifest_path = self.write_fixture(Path(temp))
            dataset = mod.register(csv_path, meta_path, manifest_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(dataset["id"], "fr_sia_designated_points")
        self.assertEqual(dataset["recordCount"], 1)
        self.assertEqual(dataset["downloadPurpose"], "reference_only")
        self.assertFalse(dataset["operationallyAvailable"])
        self.assertIn("not classified as VFR reporting points", dataset["coverage"])
        self.assertEqual(manifest["statistics"]["frSiaDesignatedPoints"], 1)
        self.assertTrue(manifest["capabilities"]["frSiaDesignatedPoints"])

    def test_rejects_unverified_license_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            csv_path, meta_path, manifest_path = self.write_fixture(Path(temp))
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            metadata["license"] = "unknown"
            meta_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "licence metadata"):
                mod.register(csv_path, meta_path, manifest_path)

    def test_rejects_out_of_range_coordinates(self):
        with tempfile.TemporaryDirectory() as temp:
            csv_path, meta_path, manifest_path = self.write_fixture(Path(temp))
            text = csv_path.read_text(encoding="utf-8").replace("46.66666667", "95")
            csv_path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid coordinate"):
                mod.register(csv_path, meta_path, manifest_path)

    def test_expired_snapshot_is_retained_but_not_downloadable(self):
        with tempfile.TemporaryDirectory() as temp:
            csv_path, meta_path, manifest_path = self.write_fixture(Path(temp))
            dataset = mod.register(csv_path, meta_path, manifest_path, today=date(2026, 12, 24))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertFalse(dataset["available"])
        self.assertNotIn("downloadUrl", dataset)
        self.assertFalse(manifest["capabilities"]["frSiaDesignatedPoints"])
        self.assertNotIn("frSiaDesignatedPoints", manifest["statistics"])
        self.assertEqual(manifest["developmentOnlyStatistics"]["frSiaDesignatedPoints"], 1)


if __name__ == "__main__":
    unittest.main()
