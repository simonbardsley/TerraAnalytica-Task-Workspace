import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("validate_package", SCRIPTS / "validate_package.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class ReleasePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "ta_tasks"
        self.source.mkdir()
        for name in ("__init__.py", "LICENSE", "HELP.md", "SECURITY.md", "RELEASE_CHECKLIST.md"):
            (self.source / name).write_text("Release fixture", encoding="utf-8")
        (self.source / "metadata.txt").write_text(
            "[general]\nversion=0.8.2\nauthor=TerraAnalytica\nexperimental=True\n", encoding="utf-8"
        )
        self.archive = self.root / "ta_tasks-0.8.2.zip"

    def tearDown(self):
        self.temp.cleanup()

    def build(self, extra=None):
        with ZipFile(self.archive, "w") as archive:
            for file in self.source.iterdir():
                archive.write(file, f"ta_tasks/{file.name}")
            if extra:
                archive.writestr(extra, "Unexpected data")

    def validate(self):
        with patch.object(validator, "PLUGIN", self.source):
            return validator.validate_package(self.archive)

    def test_valid_archive_has_sha256(self):
        self.build()
        self.assertEqual(len(self.validate()), 64)

    def test_macos_metadata_is_rejected(self):
        self.build("__MACOSX/ta_tasks/._metadata.txt")
        with self.assertRaises(ValueError):
            self.validate()

    def test_source_mismatch_is_rejected(self):
        self.build()
        (self.source / "HELP.md").write_text("Changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.validate()

    def test_private_key_file_is_rejected(self):
        (self.source / "private.pem").write_text("Fixture key", encoding="utf-8")
        self.build()
        with self.assertRaises(ValueError):
            self.validate()

    def test_author_slashes_are_rejected(self):
        metadata = self.source / "metadata.txt"
        metadata.write_text(metadata.read_text().replace("author=TerraAnalytica",
                            "author=TerraAnalytica / NZSpatial"), encoding="utf-8")
        self.build()
        with self.assertRaisesRegex(ValueError, "Author"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
