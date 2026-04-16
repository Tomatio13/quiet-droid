import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from quiet_droid.tui import SLASH_COMMANDS, TUI


class DummyConfig:
    def __init__(self, root):
        self.history_file = os.path.join(root, "history")
        self.context_window = 1024


class TuiTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.config = DummyConfig(self.tmpdir.name)
        self.original_cwd = os.getcwd()
        os.chdir(self.tmpdir.name)
        self.tui = TUI(self.config)

    def tearDown(self):
        os.chdir(self.original_cwd)
        self.tmpdir.cleanup()

    def test_slash_completion_lists_known_commands(self):
        self.assertEqual(self.tui.get_completion_candidates("/"), SLASH_COMMANDS)

    def test_slash_completion_filters_by_prefix(self):
        self.assertEqual(self.tui.get_completion_candidates("/mo"), ["/model", "/models"])

    def test_skill_completion_lists_loaded_skills(self):
        self.tui.set_skill_names(["plan", "review"])
        self.assertEqual(self.tui.get_completion_candidates("$"), ["$plan", "$review"])

    def test_skill_completion_filters_by_prefix(self):
        self.tui.set_skill_names(["plan", "review"])
        self.assertEqual(self.tui.get_completion_candidates("$pl"), ["$plan"])

    def test_file_completion_lists_cwd_entries(self):
        with open(os.path.join(self.tmpdir.name, "notes.txt"), "w", encoding="utf-8") as f:
            f.write("hello")
        os.makedirs(os.path.join(self.tmpdir.name, "docs"), exist_ok=True)

        self.assertEqual(self.tui.get_completion_candidates("@"), ["@docs/", "@notes.txt"])

    def test_file_completion_filters_by_prefix(self):
        with open(os.path.join(self.tmpdir.name, "notes.txt"), "w", encoding="utf-8") as f:
            f.write("hello")
        with open(os.path.join(self.tmpdir.name, "todo.txt"), "w", encoding="utf-8") as f:
            f.write("world")

        self.assertEqual(self.tui.get_completion_candidates("@no"), ["@notes.txt"])

    def test_show_skill_list_handles_empty_skills(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.tui.show_skill_list()
        self.assertIn("No skills loaded", output.getvalue())


if __name__ == "__main__":
    unittest.main()
