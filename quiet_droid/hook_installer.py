import json
import os
import shlex
import stat
import sys


HOOK_WRAPPER = """#!/usr/bin/env python3
from quiet_droid.smart_truncate_hook import main

if __name__ == "__main__":
    main()
"""


def _build_hooks_config(script_path):
    command = f"{shlex.quote(sys.executable)} {shlex.quote(script_path)}"
    return {
        "hooks": {
            "PostToolUse": [{"type": "command", "command": command}],
            "PostToolUseFailure": [{"type": "command", "command": command}],
        }
    }


def install_hooks(config, force=False):
    hook_dir = os.path.join(config.config_dir, "hooks")
    script_path = os.path.join(hook_dir, "smart_truncate.py")
    hooks_path = os.path.join(config.config_dir, "hooks.json")
    os.makedirs(hook_dir, mode=0o700, exist_ok=True)
    if os.path.exists(hooks_path) and not force:
        return {
            "installed": False,
            "reason": "exists",
            "hooks_path": hooks_path,
            "script_path": script_path,
        }
    with open(script_path, "w", encoding="utf-8") as handle:
        handle.write(HOOK_WRAPPER)
    os.chmod(script_path, os.stat(script_path).st_mode | stat.S_IXUSR)
    with open(hooks_path, "w", encoding="utf-8") as handle:
        json.dump(_build_hooks_config(script_path), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return {
        "installed": True,
        "reason": "forced" if force else "created",
        "hooks_path": hooks_path,
        "script_path": script_path,
    }
