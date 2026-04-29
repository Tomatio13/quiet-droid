import os
import platform
import re
import signal
import subprocess
import threading
import time

from .base import Tool


_bg_tasks = {}
_bg_task_counter = [0]
_bg_tasks_lock = threading.Lock()
MAX_BG_TASKS = 50
INLINE_OUTPUT_LIMIT = 120000
INLINE_OUTPUT_SLICE = INLINE_OUTPUT_LIMIT // 2


class BashTool(Tool):
    name = "Bash"
    description = "Execute a bash command."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The bash command to execute"},
            "timeout": {"type": "number", "description": "Timeout in milliseconds"},
            "run_in_background": {"type": "boolean", "description": "Run command in background"},
        },
        "required": ["command"],
    }

    def _build_clean_env(self):
        always_allow = {
            "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "LANG", "LC_ALL",
            "TMPDIR", "TMP", "TEMP", "DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR",
            "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "SSH_AUTH_SOCK",
            "EDITOR", "VISUAL", "PAGER", "HOSTNAME", "PWD", "OLDPWD", "SHLVL",
            "COLORTERM", "TERM_PROGRAM", "COLUMNS", "LINES", "NO_COLOR", "FORCE_COLOR",
            "CC", "CXX", "CFLAGS", "LDFLAGS", "PKG_CONFIG_PATH", "GOPATH", "GOROOT",
            "CARGO_HOME", "RUSTUP_HOME", "JAVA_HOME", "NVM_DIR", "PYENV_ROOT",
            "VIRTUAL_ENV", "CONDA_DEFAULT_ENV", "OLLAMA_HOST", "OPENAI_BASE_URL", "OPENAI_API_KEY",
            "PYTHONPATH", "NODE_PATH",
        }
        sensitive_prefixes = ("OPENAI", "AWS_SECRET", "AWS_SESSION", "GITHUB_TOKEN", "GH_TOKEN", "AZURE_")
        sensitive_substrings = ("_SECRET", "_TOKEN", "_KEY", "_PASSWORD", "_API_KEY", "DATABASE_URL", "PRIVATE_KEY")
        clean = {}
        for key, value in os.environ.items():
            upper = key.upper()
            if key in always_allow:
                clean[key] = value
            elif upper.startswith(sensitive_prefixes):
                continue
            elif any(token in upper for token in sensitive_substrings):
                continue
            else:
                clean[key] = value
        if "PATH" not in clean:
            clean["PATH"] = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
        if os.name != "nt":
            clean.setdefault("LANG", "en_US.UTF-8")
        return clean

    def execute(self, params):
        command = params.get("command", "")
        if not command:
            return "Error: no command provided"
        try:
            timeout_ms = max(float(params.get("timeout", 120000)), 1000)
        except (ValueError, TypeError):
            timeout_ms = 120000
        timeout_s = min(timeout_ms / 1000, 600)

        now = time.time()
        with _bg_tasks_lock:
            stale = [k for k, v in _bg_tasks.items() if v.get("result") is not None and now - v.get("start", 0) > 3600]
            for key in stale:
                del _bg_tasks[key]

        bg_match = re.match(r"^bg_status\s+(bg_\d+)$", command.strip())
        if bg_match:
            task_id = bg_match.group(1)
            with _bg_tasks_lock:
                entry = _bg_tasks.get(task_id)
            if not entry:
                return f"Error: unknown background task '{task_id}'"
            if entry["result"] is None:
                elapsed = int(time.time() - entry["start"])
                return f"Task {task_id} still running ({elapsed}s elapsed). Command: {entry['command']}"
            result = entry["result"]
            with _bg_tasks_lock:
                _bg_tasks.pop(task_id, None)
            return f"Task {task_id} completed:\n{result}"

        background_patterns = [
            r"&\s*$", r"&\s*\)", r"&\s*;", r"\bnohup\b", r"\bsetsid\b", r"\bdisown\b",
            r"\bscreen\s+-[dDm]", r"\btmux\b.*\b(new|send)", r"\bat\s+now\b",
            r"bash\s+-c\s+['\"].*&", r"sh\s+-c\s+['\"].*&",
        ]
        for pattern in background_patterns:
            if re.search(pattern, command):
                return "Error: background/async commands are not supported in this environment."

        dangerous_patterns = [
            r"\bcurl\b.*\|\s*\bsh\b", r"\bwget\b.*\|\s*\bsh\b", r"\brm\s+-rf\s+/",
            r"\bmkfs\b", r"\bdd\b.*\bof=/dev/", r">\s*/etc/", r"\beval\b.*\bbase64\b",
        ]
        for pattern in dangerous_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return "Error: this command pattern is blocked for safety."

        protected_names = {"permissions.json", ".quiet-droid.json", "config.json"}
        write_indicators = (">", ">>", "tee ", "mv ", "cp ", "echo ", "cat ", "sed ", "dd ", "install ", "printf ", "perl ", "python", "ruby ", "bash -c", "sh -c", "ln ")
        command_lower = command.lower()
        for protected in protected_names:
            if protected in command_lower and any(token in command_lower for token in write_indicators):
                return f"Error: writing to {protected} via shell is blocked for security."

        if params.get("run_in_background", False):
            with _bg_tasks_lock:
                _bg_task_counter[0] += 1
                task_id = f"bg_{_bg_task_counter[0]}"
                if len(_bg_tasks) >= MAX_BG_TASKS:
                    return f"Error: too many background tasks ({MAX_BG_TASKS})."
                _bg_tasks[task_id] = {"thread": None, "result": None, "command": command, "start": time.time()}

            def run_bg():
                try:
                    proc = subprocess.Popen(
                        command,
                        shell=True,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        cwd=os.getcwd(),
                        env=self._build_clean_env(),
                        start_new_session=platform.system() != "Windows",
                    )
                    stdout, stderr = proc.communicate(timeout=timeout_s)
                    output = (stdout or "") + ("\n" + stderr if stderr else "")
                    if proc.returncode != 0:
                        output += f"\n(exit code: {proc.returncode})"
                except subprocess.TimeoutExpired:
                    try:
                        if hasattr(os, "killpg"):
                            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        pass
                    proc.kill()
                    output = f"Error: background command timed out after {int(timeout_s)}s"
                except Exception as exc:
                    output = f"Error: {exc}"
                with _bg_tasks_lock:
                    _bg_tasks[task_id]["result"] = (output.strip() or "(no output)")

            thread = threading.Thread(target=run_bg, daemon=True)
            with _bg_tasks_lock:
                _bg_tasks[task_id]["thread"] = thread
            thread.start()
            return f"Background task started: {task_id}\nUse Bash(command='bg_status {task_id}') to check result."

        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=os.getcwd(),
                env=self._build_clean_env(),
                start_new_session=platform.system() != "Windows",
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                try:
                    if hasattr(os, "killpg"):
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
                proc.kill()
                return f"Error: command took too long (over {int(timeout_s)}s) and was stopped."
            output = ""
            if stdout:
                output += stdout
            if stderr:
                output += ("\n" if output else "") + stderr
            if proc.returncode != 0:
                output += f"\n(exit code: {proc.returncode})"
            if not output.strip():
                output = "(no output)"
            if len(output) > INLINE_OUTPUT_LIMIT:
                output = output[:INLINE_OUTPUT_SLICE] + "\n\n... (truncated) ...\n\n" + output[-INLINE_OUTPUT_SLICE:]
            return output.strip()
        except Exception as exc:
            return f"Error: {exc}"
