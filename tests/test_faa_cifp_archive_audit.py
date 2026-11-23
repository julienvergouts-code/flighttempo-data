import tempfile, unittest, zipfile
from pathlib import Path
from scripts.audit_faa_cifp_archive import audit_archive

class FaaCifpArchiveAuditTests(unittest.TestCase):
    def make_zip(self, content=b"SAMPLE CIFP RECORD\n"):
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        tmp.close()
        with zipfile.ZipFile(tmp.name, "w") as zf:
            zf.writestr("CIFP_SAMPLE.txt", content)
        return Path(tmp.name)

    def test_audit_is_report_only_and_hashes_text_member(self):
        path = self.make_zip(b"SAMPLE RECORD\n" * 4)
        try:
            report = audit_archive(path)
            self.assertEqual(report["zipIntegrity"], "passed")
            self.assertFalse(report["conversionEnabled"])
            self.assertFalse(report["publicationEnabled"])
            self.assertEqual(report["asciiTextMemberCount"], 1)
            self.assertEqual(report["members"][0]["lineCount"], 4)
        finally:
            path.unlink(missing_ok=True)

    def test_rejects_empty_archive(self):
        path = self.make_zip(b"")
        try:
            with self.assertRaises(ValueError):
                audit_archive(path)
        finally:
            path.unlink(missing_ok=True)

    def test_rejects_unsafe_member_paths(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        tmp.close()
        with zipfile.ZipFile(tmp.name, "w") as zf:
            zf.writestr("../evil.txt", "bad")
            zf.writestr("safe.txt", "ok")
        path = Path(tmp.name)
        try:
            with self.assertRaises(ValueError):
                audit_archive(path)
        finally:
            path.unlink(missing_ok=True)

if __name__ == "__main__":
    unittest.main()
