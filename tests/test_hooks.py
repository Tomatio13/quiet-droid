import json
import os
import stat
import sys
import tempfile
import unittest

from quiet_droid.hooks import HookManager
from quiet_droid.tools.agents import SubAgentTool
from quiet_droid.tools.registry import PermissionMgr


class DummyConfig:
    def __init__(self, root):
        self.cwd = root
        self.config_dir = os.path.join(root, "config")
        self.sessions_dir = os.path.join(root, "sessions")
        self.permissions_file = os.path.join(self.config_dir, "permissions.json")
        self.yes_mode = False
        self.context_window = 256
        self.model = "test-model"
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.sessions_dir, exist_ok=True)


def write_executable(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = self.tmpdir.name
        self.config = DummyConfig(self.root)
        self.log_path = os.path.join(self.root, "hook-log.jsonl")
        self.script_path = os.path.join(self.root, "hook.py")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_hooks(self, hooks):
        with open(os.path.join(self.config.config_dir, "hooks.json"), "w", encoding="utf-8") as f:
            json.dump({"hooks": hooks}, f)

    def test_pre_tool_use_deny_is_returned(self):
        write_executable(
            self.script_path,
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import json, sys",
                    "payload = json.load(sys.stdin)",
                    "json.dump({",
                    '  "hookSpecificOutput": {',
                    '    "hookEventName": "PreToolUse",',
                    '    "permissionDecision": "deny",',
                    '    "permissionDecisionReason": "blocked by test",',
                    '    "updatedInput": {"command": "echo patched"}',
                    "  }",
                    "}, sys.stdout)",
                ]
            ),
        )
        self._write_hooks(
            {
                "PreToolUse": [
                    {
                        "type": "command",
                        "matcher": "Bash",
                        "command": f"{sys.executable} {self.script_path}",
                    }
                ]
            }
        )
        hooks = HookManager(self.config)
        decision = hooks.evaluate_pre_tool_use("Bash", {"command": "rm -rf /tmp/x"})
        self.assertEqual(decision.decision, "deny")
        self.assertEqual(decision.reason, "blocked by test")
        self.assertEqual(decision.updated_input, {"command": "echo patched"})

    def test_permission_denied_hook_fires(self):
        write_executable(
            self.script_path,
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import json, pathlib, sys",
                    "payload = json.load(sys.stdin)",
                    f'pathlib.Path(r"{self.log_path}").write_text(json.dumps(payload) + "\\n", encoding="utf-8")',
                ]
            ),
        )
        self._write_hooks(
            {
                "PermissionDenied": [
                    {
                        "type": "command",
                        "matcher": "Write",
                        "command": f"{sys.executable} {self.script_path}",
                    }
                ]
            }
        )
        with open(self.config.permissions_file, "w", encoding="utf-8") as f:
            json.dump({"Write": "deny"}, f)
        hooks = HookManager(self.config)
        permissions = PermissionMgr(self.config, hooks=hooks)
        allowed = permissions.check("Write", {"file_path": "/tmp/demo.txt"}, tui=None)
        self.assertFalse(allowed)
        with open(self.log_path, encoding="utf-8") as f:
            payload = json.loads(f.readline())
        self.assertEqual(payload["hook_event_name"], "PermissionDenied")
        self.assertEqual(payload["tool_name"], "Write")

    def test_subagent_start_and_stop_hooks_fire(self):
        write_executable(
            self.script_path,
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import json, pathlib, sys",
                    "payload = json.load(sys.stdin)",
                    f'with pathlib.Path(r"{self.log_path}").open("a", encoding="utf-8") as f:',
                    '    f.write(json.dumps(payload) + "\\n")',
                ]
            ),
        )
        self._write_hooks(
            {
                "SubagentStart": [{"type": "command", "command": f"{sys.executable} {self.script_path}"}],
                "SubagentStop": [{"type": "command", "command": f"{sys.executable} {self.script_path}"}],
            }
        )
        hooks = HookManager(self.config)

        class FakeClient:
            def chat_sync(self, model, messages, tools=None):
                return {"choices": [{"message": {"content": "done"}}]}

        class DummyRegistry:
            def get_schemas(self):
                return []

            def get(self, name):
                return None

        tool = SubAgentTool(self.config, FakeClient(), DummyRegistry(), permissions=None, hooks=hooks)
        result = tool.execute({"prompt": "say done"})
        self.assertEqual(result, "done")
        with open(self.log_path, encoding="utf-8") as f:
            events = [json.loads(line)["hook_event_name"] for line in f if line.strip()]
        self.assertEqual(events, ["SubagentStart", "SubagentStop"])


if __name__ == "__main__":
    unittest.main()
