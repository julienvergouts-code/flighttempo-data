import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_navigation_csvs import (
    parse_csv_bytes,
    validate_dataset,
    validate_manifest,
)


class ParseCsvBytesTests(unittest.TestCase):
    def test_plain_comma_csv(self):
        header, count = parse_csv_bytes(b"id,name\n1,Alpha\n2,Beta\n")
        self.assertEqual(header, ["id", "name"])
        self.assertEqual(count, 2)

    def test_simulator_metadata_and_columns_directive(self):
        raw = (
            b"#version 1101\n#columns,latitude,longitude,ident,area,region,type\n"
            b"50.0,4.0,TEST,ENRT,EB,11\n"
        )
        header, count = parse_csv_bytes(raw)
        self.assertEqual(header, ["latitude", "longitude", "ident", "area", "region", "type"])
        self.assertEqual(count, 1)

    def test_semicolon_delimited_airline_csv(self):
        header, count = parse_csv_bytes(
            b"code;displayName;signOnMins\nABC;Example Airline;45\n"
        )
        self.assertEqual(header, ["code", "displayName", "signOnMins"])
        self.assertEqual(count, 1)

    def test_quoted_multiline_field_is_preserved(self):
        raw = b'id,name\\n1,"Alpha\\nAirport"\\n2,Beta\\n'
        header, count = parse_csv_bytes(raw)
        self.assertEqual(header, ["id", "name"])
        self.assertEqual(count, 2)

    def test_rejects_duplicate_headers(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_csv_bytes(b"id,name,id\n1,A,2\n")

    def test_rejects_malformed_row_width(self):
        with self.assertRaisesRegex(ValueError, "expected 2"):
            parse_csv_bytes(b"id,name\n1,A\n2\n")


class ManifestValidationTests(unittest.TestCase):
    def test_validates_file_hash_size_and_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = b"id,name\n1,Alpha\n2,Beta\n"
            (root / "sample.csv").write_bytes(raw)
            dataset = {
                "id": "sample",
                "path": "sample.csv",
                "available": True,
                "sizeBytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "recordCount": 2,
            }
            result = validate_dataset(root, dataset)
            self.assertEqual(result["recordCount"], 2)

    def test_rejects_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sample.csv").write_text("id\n1\n", encoding="utf-8")
            dataset = {
                "id": "sample", "path": "sample.csv",
                "sha256": "0" * 64, "recordCount": 1,
            }
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                validate_dataset(root, dataset)

    def test_manifest_skips_unavailable_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = b"id\n1\n"
            (root / "sample.csv").write_bytes(raw)
            manifest = {
                "datasets": [{
                    "id": "sample", "path": "sample.csv", "available": False
                }]
            }
            (root / "navigation_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "No available CSV"):
                validate_manifest(root, root / "navigation_manifest.json")


if __name__ == "__main__":
    unittest.main()
