import os
import tempfile
import unittest

from quiet_droid.input_expansion import extract_referenced_files, inject_file_context


class InputExpansionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_injects_referenced_file_content(self):
        target = os.path.join(self.root, "notes.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("hello\nworld\n")

        injected = inject_file_context("@notes.txt を見て", self.root)

        self.assertIn("@notes.txt を見て", injected)
        self.assertIn("[Referenced Files]", injected)
        self.assertIn("## File: notes.txt", injected)
        self.assertIn(f"Resolved path: {target}", injected)
        self.assertIn("Status: ok", injected)
        self.assertIn("hello\nworld", injected)

    def test_skips_email_addresses(self):
        injected = inject_file_context("連絡先は user@example.com です", self.root)
        self.assertEqual(injected, "連絡先は user@example.com です")

    def test_rejects_paths_outside_cwd(self):
        outside = os.path.abspath(os.path.join(self.root, "..", "secret.txt"))

        injected = inject_file_context(f"@{outside} を見て", self.root)

        self.assertIn("Status: error", injected)
        self.assertIn("Error: path is outside the current working directory", injected)

    def test_reports_missing_files(self):
        injected = inject_file_context("@missing.txt を見て", self.root)

        self.assertIn("## File: missing.txt", injected)
        self.assertIn("Status: error", injected)
        self.assertIn("Error: file not found", injected)

    def test_trims_trailing_punctuation(self):
        target = os.path.join(self.root, "notes.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("body")

        referenced = extract_referenced_files("@notes.txt, を見て", self.root)

        self.assertEqual(len(referenced), 1)
        self.assertEqual(referenced[0].display_path, "notes.txt")
        self.assertEqual(referenced[0].trailing, ",")

    def test_marks_binary_files(self):
        target = os.path.join(self.root, "data.bin")
        with open(target, "wb") as f:
            f.write(b"\x00\x01\x02")

        injected = inject_file_context("@data.bin", self.root)

        self.assertIn("Status: binary", injected)
        self.assertIn("[binary file skipped]", injected)


if __name__ == "__main__":
    unittest.main()
