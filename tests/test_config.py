import os
import tempfile
import unittest
from unittest.mock import patch

from quiet_droid.config import Config


class ConfigTests(unittest.TestCase):
    def test_model_stays_empty_when_not_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            with tempfile.TemporaryDirectory() as tmpdir:
                config = Config()
                config.config_dir = tmpdir
                config.state_dir = tmpdir
                config._refresh_paths()
                config.load([])

                self.assertEqual(config.model, "")

    def test_env_openai_model_is_used_when_quiet_droid_model_is_absent(self):
        with patch.dict(os.environ, {"OPENAI_MODEL": "gpt-4.1-mini"}, clear=True):
            config = Config()
            config._load_env()
            self.assertEqual(config.model, "gpt-4.1-mini")

    def test_env_quiet_droid_model_takes_precedence_over_openai_model(self):
        with patch.dict(
            os.environ,
            {"OPENAI_MODEL": "gpt-4.1-mini", "QUIET_DROID_MODEL": "qwen3-coder:30b"},
            clear=True,
        ):
            config = Config()
            config._load_env()
            self.assertEqual(config.model, "qwen3-coder:30b")

    def test_config_file_accepts_openai_model_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config()
            config.config_dir = tmpdir
            config.state_dir = tmpdir
            config._refresh_paths()
            with open(config.config_file, "w", encoding="utf-8") as f:
                f.write("OPENAI_MODEL=gpt-4.1-mini\n")

            config._load_config_file()

            self.assertEqual(config.model, "gpt-4.1-mini")

    def test_resume_flags_are_loaded_from_cli(self):
        config = Config()
        config._load_cli_args(["--resume"])

        self.assertTrue(config.resume)
        self.assertIsNone(config.session_id)

    def test_session_id_enables_resume(self):
        config = Config()
        config._load_cli_args(["--session-id", "demo"])

        self.assertTrue(config.resume)
        self.assertEqual(config.session_id, "demo")

    def test_list_sessions_flag_is_loaded_from_cli(self):
        config = Config()
        config._load_cli_args(["--list-sessions"])

        self.assertTrue(config.list_sessions)


if __name__ == "__main__":
    unittest.main()
