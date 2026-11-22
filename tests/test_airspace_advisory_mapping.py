import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AirspaceSourcePublicationTests(unittest.TestCase):
    def test_russia_source_record_keeps_explicit_easa_fir_list(self):
        payload = json.loads(
            (ROOT / "airspace/advisories/easa_czibs.json").read_text(encoding="utf-8")
        )
        record = next(x for x in payload["records"] if x["sourceId"] == "141480")
        self.assertEqual(
            set(record["explicitFirCodes"]), {"UUWV", "URRV", "ULLL", "USSV", "UWWW"}
        )
        self.assertNotIn("UMKK", record["explicitFirCodes"])
        self.assertNotIn("UKFV", record["explicitFirCodes"])

    def test_noncommercial_openaip_export_and_derived_filter_are_absent(self):
        self.assertFalse((ROOT / "navigation/airspace/openaip_fir_boundaries.geojson").exists())
        # The shared file may contain unrelated FAA restriction references.
        # Assert that no OpenAIP-derived content is present in it.
        filter_path = ROOT / "airspace/airspace_filter.json"
        if filter_path.is_file():
            filter_data = json.loads(filter_path.read_text(encoding="utf-8"))
            self.assertNotIn("openaip", json.dumps(filter_data).lower())
            fir_dataset = filter_data.get("firBoundaryDataset") or {}
            self.assertNotEqual(fir_dataset.get("status"), "available_development_reference")
        self.assertFalse((ROOT / "scripts/import_openaip_firs.py").exists())
        manifest = json.loads((ROOT / "navigation_manifest.json").read_text(encoding="utf-8"))
        by_id = {x["id"]: x for x in manifest["datasets"]}
        for dataset_id in ("openaip_fir_boundaries", "airspace_filter"):
            dataset = by_id.get(dataset_id)
            if dataset is not None:
                self.assertFalse(dataset.get("available", False))
                self.assertNotIn("downloadUrl", dataset)
        self.assertFalse(manifest["capabilities"]["firBoundaries"])
        self.assertFalse(manifest["capabilities"]["airspaceFilterAdvisoryOnly"])

    def test_easa_records_are_not_app_downloadable_without_verified_commercial_terms(self):
        manifest = json.loads((ROOT / "navigation_manifest.json").read_text(encoding="utf-8"))
        by_id = {x["id"]: x for x in manifest["datasets"]}
        for dataset_id in ("easa_czibs", "easa_safety_directives"):
            self.assertFalse(by_id[dataset_id]["available"])
            self.assertNotIn("downloadUrl", by_id[dataset_id])


if __name__ == "__main__":
    unittest.main()
