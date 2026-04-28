import os
import tempfile
import unittest
from unittest.mock import patch

from quiet_droid import prompts


class DummyConfig:
    def __init__(self, root):
        self.cwd = root
        self.config_dir = root


class PromptTests(unittest.TestCase):
    def test_system_prompt_includes_current_datetime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(prompts, "_current_datetime", return_value="2026-04-29T12:34:56+09:00 (JST)"):
                prompt = prompts.build_system_prompt(DummyConfig(tmpdir))

        self.assertIn("- Current datetime: 2026-04-29T12:34:56+09:00 (JST)", prompt)

    def test_project_instructions_still_load_after_datetime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "AGENTS.md"), "w", encoding="utf-8") as f:
                f.write("project rule")
            prompt = prompts.build_system_prompt(DummyConfig(tmpdir))

        self.assertIn("# Environment", prompt)
        self.assertIn("# Project Instructions (from ./AGENTS.md)", prompt)
        self.assertIn("project rule", prompt)


if __name__ == "__main__":
    unittest.main()
