import json
import os
import re

from .bash import BashTool
from .filesystem import EditTool, GlobTool, GrepTool, ReadTool, WriteTool


class ToolRegistry:
    def __init__(self):
        self._tools = {}
        self._cached_schemas = None

    def register(self, tool):
        self._tools[tool.name] = tool
        self._cached_schemas = None

    def get(self, name):
        return self._tools.get(name)

    def names(self):
        return list(self._tools.keys())

    def get_schemas(self):
        if self._cached_schemas is None:
            self._cached_schemas = [tool.get_schema() for tool in self._tools.values()]
        return self._cached_schemas

    def register_defaults(self):
        for cls in [BashTool, ReadTool, WriteTool, EditTool, GlobTool, GrepTool]:
            self.register(cls())
        return self


class PermissionMgr:
    SAFE_TOOLS = {"Read", "Glob", "Grep"}
    ASK_TOOLS = {"Bash", "Write", "Edit", "SubAgent", "ParallelAgents"}
    _ALWAYS_CONFIRM_PATTERNS = [r"\brm\s+-rf\s+/", r"\bsudo\b", r"\bmkfs\b", r"\bdd\b.*\bof=/dev/"]

    def __init__(self, config):
        self.yes_mode = config.yes_mode
        self.rules = {}
        self._session_allows = set()
        self._session_denies = set()
        self._load_rules(config.permissions_file)

    def _load_rules(self, path):
        if not os.path.isfile(path) or os.path.islink(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            for key, value in data.items():
                if isinstance(key, str) and value in {"allow", "deny"}:
                    if key == "Bash" and value == "allow":
                        continue
                    self.rules[key] = value
        except (OSError, json.JSONDecodeError):
            pass

    def check(self, tool_name, params, tui=None):
        if tool_name in self._session_denies:
            return False

        if tool_name == "Bash" and self.yes_mode:
            command = params.get("command", "")
            for pattern in self._ALWAYS_CONFIRM_PATTERNS:
                if re.search(pattern, command, re.IGNORECASE):
                    if not tui:
                        return False
                    result = tui.ask_permission(tool_name, params)
                    if result == "yes_mode":
                        self.yes_mode = True
                        return True
                    if result == "allow_all":
                        return True
                    if result == "deny_all":
                        self._session_denies.add(tool_name)
                        return False
                    return result
        if self.yes_mode:
            return True
        if tool_name in self.SAFE_TOOLS:
            return True
        if self.rules.get(tool_name) == "allow":
            return True
        if self.rules.get(tool_name) == "deny":
            return False
        if tool_name in self._session_allows:
            return True
        if tool_name not in self.SAFE_TOOLS and tool_name not in self.ASK_TOOLS:
            return False if not tui else False
        if tui:
            result = tui.ask_permission(tool_name, params)
            if result == "yes_mode":
                self.yes_mode = True
                return True
            if result == "allow_all":
                self._session_allows.add(tool_name)
                return True
            if result == "deny_all":
                self._session_denies.add(tool_name)
                return False
            return result
        return False
