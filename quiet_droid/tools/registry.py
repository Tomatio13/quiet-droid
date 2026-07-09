import json
import os
import re

from .bash import BashTool
from .filesystem import EditTool, GlobTool, GrepTool, ReadTool, WriteTool
from .interaction import AskUserQuestionTool


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
        for cls in [BashTool, ReadTool, WriteTool, EditTool, GlobTool, GrepTool, AskUserQuestionTool]:
            self.register(cls())
        return self


class PermissionMgr:
    SAFE_TOOLS = {"Read", "Glob", "Grep", "AskUserQuestion", "update_goal"}
    ASK_TOOLS = {"Bash", "Write", "Edit", "SubAgent", "ParallelAgents"}
    _ALWAYS_CONFIRM_PATTERNS = [r"\brm\s+-rf\s+/", r"\bsudo\b", r"\bmkfs\b", r"\bdd\b.*\bof=/dev/"]

    def __init__(self, config, hooks=None):
        self.yes_mode = config.yes_mode
        self._hooks = hooks
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

    def _emit_permission_denied(self, tool_name, params):
        if self._hooks:
            self._hooks.emit("PermissionDenied", {"tool_name": tool_name, "tool_input": dict(params)}, matcher=tool_name)

    def check(self, tool_name, params, tui=None, force_ask=False, ask_reason=""):
        if tool_name in self._session_denies:
            self._emit_permission_denied(tool_name, params)
            return False

        if tool_name == "Bash" and self.yes_mode and not force_ask:
            command = params.get("command", "")
            for pattern in self._ALWAYS_CONFIRM_PATTERNS:
                if re.search(pattern, command, re.IGNORECASE):
                    if not tui:
                        self._emit_permission_denied(tool_name, params)
                        return False
                    if self._hooks:
                        self._hooks.emit("PermissionRequest", {"tool_name": tool_name, "tool_input": dict(params)}, matcher=tool_name)
                    result = tui.ask_permission(tool_name, params, reason=ask_reason)
                    if result == "yes_mode":
                        self.yes_mode = True
                        return True
                    if result == "allow_all":
                        return True
                    if result == "deny_all":
                        self._session_denies.add(tool_name)
                        self._emit_permission_denied(tool_name, params)
                        return False
                    if result is False:
                        self._emit_permission_denied(tool_name, params)
                    return result
        if self.yes_mode and not force_ask:
            return True
        if tool_name in self.SAFE_TOOLS:
            return True
        if self.rules.get(tool_name) == "allow":
            return True
        if self.rules.get(tool_name) == "deny":
            self._emit_permission_denied(tool_name, params)
            return False
        if tool_name in self._session_allows:
            return True
        if tool_name not in self.SAFE_TOOLS and tool_name not in self.ASK_TOOLS:
            self._emit_permission_denied(tool_name, params)
            return False if not tui else False
        if tui:
            if self._hooks:
                self._hooks.emit("PermissionRequest", {"tool_name": tool_name, "tool_input": dict(params)}, matcher=tool_name)
            result = tui.ask_permission(tool_name, params, reason=ask_reason)
            if result == "yes_mode":
                self.yes_mode = True
                return True
            if result == "allow_all":
                self._session_allows.add(tool_name)
                return True
            if result == "deny_all":
                self._session_denies.add(tool_name)
                self._emit_permission_denied(tool_name, params)
                return False
            if result is False:
                self._emit_permission_denied(tool_name, params)
            return result
        self._emit_permission_denied(tool_name, params)
        return False
