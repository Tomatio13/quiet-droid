import json
import os
import tempfile
import unittest

from quiet_droid.config import Config
from quiet_droid.hook_installer import install_hooks


class HookInstallerTests(unittest.TestCase):
    def test_install_hooks_creates_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config()
            config.config_dir = tmpdir
            config.state_dir = tmpdir
            config._refresh_paths()

            result = install_hooks(config)

            self.assertTrue(result["installed"])
            self.assertTrue(os.path.isfile(result["hooks_path"]))
            self.assertTrue(os.path.isfile(result["script_path"]))
            with open(result["hooks_path"], encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertIn("PostToolUse", data["hooks"])
            self.assertIn("PostToolUseFailure", data["hooks"])

    def test_install_hooks_does_not_overwrite_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config()
            config.config_dir = tmpdir
            config.state_dir = tmpdir
            config._refresh_paths()
            os.makedirs(config.config_dir, exist_ok=True)
            with open(os.path.join(config.config_dir, "hooks.json"), "w", encoding="utf-8") as handle:
                handle.write('{"hooks": {"PreToolUse": []}}\n')

            result = install_hooks(config)

            self.assertFalse(result["installed"])
            with open(os.path.join(config.config_dir, "hooks.json"), encoding="utf-8") as handle:
                self.assertIn("PreToolUse", handle.read())


if __name__ == "__main__":
    unittest.main()
