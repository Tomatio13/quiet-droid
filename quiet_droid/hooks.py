import json
import os
import subprocess


class HookDecision:
    def __init__(self, decision=None, reason="", updated_input=None, additional_context=""):
        self.decision = decision
        self.reason = reason or ""
        self.updated_input = updated_input if isinstance(updated_input, dict) else None
        self.additional_context = additional_context or ""


class HookManager:
    TOOL_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest", "PermissionDenied"}
    DECISION_PRIORITY = {"allow": 1, "ask": 2, "deny": 3}

    def __init__(self, config, session=None):
        self._config = config
        self._session = session
        self._hooks = self._load_hooks()

    def set_session(self, session):
        self._session = session

    def has_hooks(self):
        return any(self._hooks.values())

    def _load_hooks(self):
        merged = {}
        for path in self._candidate_paths():
            data = self._load_file(path)
            hooks = data.get("hooks", data) if isinstance(data, dict) else {}
            if not isinstance(hooks, dict):
                continue
            for event_name, handlers in hooks.items():
                if isinstance(event_name, str) and isinstance(handlers, list):
                    merged.setdefault(event_name, []).extend(handlers)
        return merged

    def _candidate_paths(self):
        return [
            os.path.join(self._config.config_dir, "hooks.json"),
            os.path.join(self._config.cwd, ".quiet-droid", "hooks.json"),
        ]

    @staticmethod
    def _load_file(path):
        if not os.path.isfile(path) or os.path.islink(path):
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _base_payload(self, event_name):
        session_id = ""
        transcript_path = ""
        if self._session is not None:
            session_id = self._session.session_id
            transcript_path = os.path.join(self._config.sessions_dir, f"{session_id}.jsonl")
        return {
            "session_id": session_id,
            "transcript_path": transcript_path,
            "cwd": os.getcwd(),
            "hook_event_name": event_name,
            "permission_mode": "yes_mode" if self._config.yes_mode else "default",
        }

    def _matches(self, handler, event_name, matcher):
        if handler.get("type", "command") != "command":
            return False
        if event_name not in self.TOOL_EVENTS:
            return True
        expected = handler.get("matcher")
        if expected in (None, "", "*"):
            return True
        return expected == matcher

    def _run_handler(self, handler, payload):
        command = handler.get("command", "")
        if not command:
            return None
        try:
            timeout = float(handler.get("timeout", 10))
        except (TypeError, ValueError):
            timeout = 10.0
        timeout = max(0.1, min(timeout, 600.0))
        env = os.environ.copy()
        env["QUIET_DROID_HOOK_EVENT"] = payload["hook_event_name"]
        env["QUIET_DROID_PROJECT_DIR"] = self._config.cwd
        if payload.get("session_id"):
            env["QUIET_DROID_SESSION_ID"] = payload["session_id"]
        try:
            completed = subprocess.run(
                command,
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                shell=True,
                cwd=self._config.cwd,
                env=env,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        stdout = (completed.stdout or "").strip()
        if not stdout:
            return None
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            return None

    def emit(self, event_name, payload=None, matcher=None):
        combined = self._base_payload(event_name)
        if isinstance(payload, dict):
            combined.update(payload)
        outputs = []
        for handler in self._hooks.get(event_name, []):
            if not self._matches(handler, event_name, matcher):
                continue
            output = self._run_handler(handler, combined)
            if output is not None:
                outputs.append(output)
        return outputs

    def evaluate_pre_tool_use(self, tool_name, tool_input):
        outputs = self.emit(
            "PreToolUse",
            payload={"tool_name": tool_name, "tool_input": dict(tool_input)},
            matcher=tool_name,
        )
        best = HookDecision()
        best_rank = 0
        for output in outputs:
            spec = output.get("hookSpecificOutput", {})
            if spec.get("hookEventName") != "PreToolUse":
                continue
            decision = spec.get("permissionDecision")
            rank = self.DECISION_PRIORITY.get(decision, 0)
            if rank < best_rank:
                continue
            best = HookDecision(
                decision=decision,
                reason=spec.get("permissionDecisionReason", ""),
                updated_input=spec.get("updatedInput"),
                additional_context=spec.get("additionalContext", ""),
            )
            best_rank = rank
        return best
