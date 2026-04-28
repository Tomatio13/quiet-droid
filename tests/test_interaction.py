import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from quiet_droid.tools.interaction import AskUserQuestionTool
from quiet_droid.tools.registry import PermissionMgr, ToolRegistry


class DummyConfig:
    def __init__(self, root):
        self.permissions_file = os.path.join(root, "permissions.json")
        self.yes_mode = False


class AskUserQuestionTests(unittest.TestCase):
    def test_requires_question(self):
        result = AskUserQuestionTool().execute({})

        self.assertEqual(result, "Error: question is required")

    def test_returns_selected_option(self):
        output = io.StringIO()
        with patch("builtins.input", return_value="2"), redirect_stdout(output):
            result = AskUserQuestionTool().execute(
                {
                    "question": "Choose an approach",
                    "options": ["Minimal", "Refactor"],
                }
            )

        self.assertEqual(result, "User chose: Refactor")
        self.assertIn("Question:", output.getvalue())
        self.assertIn("Choose an approach", output.getvalue())
        self.assertIn("2.", output.getvalue())

    def test_returns_custom_answer(self):
        with patch("builtins.input", return_value="something else"), redirect_stdout(io.StringIO()):
            result = AskUserQuestionTool().execute({"question": "What now?", "options": ["A", "B"]})

        self.assertEqual(result, "User answered: something else")

    def test_registry_includes_ask_user_question(self):
        registry = ToolRegistry().register_defaults()

        self.assertIn("AskUserQuestion", registry.names())

    def test_permission_manager_treats_as_safe_tool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            permissions = PermissionMgr(DummyConfig(tmpdir))

            self.assertTrue(permissions.check("AskUserQuestion", {"question": "Continue?"}, tui=None))


if __name__ == "__main__":
    unittest.main()
