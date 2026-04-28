import argparse
import os
import re
import urllib.parse

from . import __version__
from .terminal import C


class Config:
    APP_NAME = "quiet-droid"
    DEFAULT_BASE_URL = "http://localhost:8000/v1"
    DEFAULT_MODEL = ""
    DEFAULT_MAX_TOKENS = 8192
    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_CONTEXT_WINDOW = 32768

    def __init__(self):
        self.base_url = self.DEFAULT_BASE_URL
        self.api_key = ""
        self.model = self.DEFAULT_MODEL
        self.max_tokens = self.DEFAULT_MAX_TOKENS
        self.temperature = self.DEFAULT_TEMPERATURE
        self.context_window = self.DEFAULT_CONTEXT_WINDOW
        self.prompt = None
        self.yes_mode = False
        self.debug = False
        self.resume = False
        self.session_id = None
        self.list_sessions = False
        self.cwd = os.getcwd()

        if os.name == "nt":
            appdata = os.environ.get("LOCALAPPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Local"))
            self.config_dir = os.path.join(appdata, self.APP_NAME)
            self.state_dir = os.path.join(appdata, self.APP_NAME)
        else:
            home = os.path.expanduser("~")
            self.config_dir = os.path.join(home, ".config", self.APP_NAME)
            self.state_dir = os.path.join(home, ".local", "state", self.APP_NAME)

        self._refresh_paths()

    def load(self, argv=None):
        self._load_env()
        self._load_config_file()
        self._load_cli_args(argv)
        self._validate_ollama_host()
        self._ensure_dirs()
        return self

    def _refresh_paths(self):
        self.config_file = os.path.join(self.config_dir, "config")
        self.permissions_file = os.path.join(self.config_dir, "permissions.json")
        self.sessions_dir = os.path.join(self.state_dir, "sessions")
        self.history_file = os.path.join(self.state_dir, "history")

    def _load_config_file(self):
        if not os.path.isfile(self.config_file) or os.path.islink(self.config_file):
            return
        try:
            if os.path.getsize(self.config_file) > 65536:
                return
        except OSError:
            return
        try:
            with open(self.config_file, encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("\"'")
                    if key in {"MODEL", "OPENAI_MODEL"} and val:
                        self.model = val
                    elif key in {"OPENAI_BASE_URL", "BASE_URL", "OLLAMA_HOST"} and val:
                        self.base_url = val
                    elif key in {"OPENAI_API_KEY", "API_KEY"} and val:
                        self.api_key = val
                    elif key == "MAX_TOKENS" and val:
                        try:
                            self.max_tokens = int(val)
                        except ValueError:
                            pass
                    elif key == "TEMPERATURE" and val:
                        try:
                            self.temperature = float(val)
                        except ValueError:
                            pass
                    elif key == "CONTEXT_WINDOW" and val:
                        try:
                            self.context_window = int(val)
                        except ValueError:
                            pass
        except OSError:
            pass

    def _load_env(self):
        if os.environ.get("OPENAI_BASE_URL"):
            self.base_url = os.environ["OPENAI_BASE_URL"]
        elif os.environ.get("OLLAMA_HOST"):
            self.base_url = os.environ["OLLAMA_HOST"]
        if os.environ.get("OPENAI_API_KEY"):
            self.api_key = os.environ["OPENAI_API_KEY"]
        if os.environ.get("QUIET_DROID_MODEL"):
            self.model = os.environ["QUIET_DROID_MODEL"]
        elif os.environ.get("OPENAI_MODEL"):
            self.model = os.environ["OPENAI_MODEL"]
        if os.environ.get("QUIET_DROID_DEBUG") == "1":
            self.debug = True

    def _load_cli_args(self, argv=None):
        raw = list(argv) if argv is not None else list(__import__("sys").argv[1:])
        normalized = []
        for arg in raw:
            if "\u3000" in arg:
                normalized.extend(arg.replace("\u3000", " ").split())
            else:
                normalized.append(arg)
        parser = argparse.ArgumentParser(
            prog="quiet-droid",
            description="Coding agent powered by an OpenAI-compatible API",
        )
        parser.add_argument("-p", "--prompt", help="One-shot prompt (non-interactive)")
        parser.add_argument("-m", "--model", help="Model name")
        parser.add_argument("-y", "--yes", action="store_true", help="Auto-approve all tool calls")
        parser.add_argument("--debug", action="store_true", help="Debug mode")
        parser.add_argument("--resume", action="store_true", help="Resume the saved session for this project")
        parser.add_argument("--session-id", help="Resume a specific saved session")
        parser.add_argument("--list-sessions", action="store_true", help="List saved sessions")
        parser.add_argument("--base-url", "--openai-base-url", dest="base_url", help="OpenAI-compatible base URL")
        parser.add_argument("--api-key", "--openai-api-key", dest="api_key", help="API key for the OpenAI-compatible API")
        parser.add_argument("--ollama-host", dest="base_url_legacy", help=argparse.SUPPRESS)
        parser.add_argument("--max-tokens", type=int, help="Max output tokens")
        parser.add_argument("--temperature", type=float, help="Sampling temperature")
        parser.add_argument("--context-window", type=int, help="Context window size")
        parser.add_argument("--version", action="version", version=f"Quiet Droid {__version__}")
        parser.add_argument("--dangerously-skip-permissions", action="store_true", help="Alias for -y")
        args = parser.parse_args(normalized)

        if args.prompt:
            self.prompt = args.prompt
        if args.model:
            self.model = args.model
        if args.yes or args.dangerously_skip_permissions:
            self.yes_mode = True
        if args.debug:
            self.debug = True
        if args.resume:
            self.resume = True
        if args.session_id:
            self.session_id = args.session_id
            self.resume = True
        if args.list_sessions:
            self.list_sessions = True
        if args.base_url:
            self.base_url = args.base_url
        elif args.base_url_legacy:
            self.base_url = args.base_url_legacy
        if args.api_key:
            self.api_key = args.api_key
        if args.max_tokens is not None:
            self.max_tokens = args.max_tokens
        if args.temperature is not None:
            self.temperature = args.temperature
        if args.context_window is not None:
            self.context_window = args.context_window

    def _validate_ollama_host(self):
        parsed = urllib.parse.urlparse(self.base_url)
        if not parsed.scheme or not parsed.netloc:
            self.base_url = self.DEFAULT_BASE_URL
            parsed = urllib.parse.urlparse(self.base_url)
        if parsed.username or parsed.password:
            clean = f"{parsed.scheme}://{parsed.hostname}"
            if parsed.port:
                clean += f":{parsed.port}"
            clean += parsed.path.rstrip("/")
            self.base_url = clean
        self.base_url = self.base_url.rstrip("/")
        if self.context_window <= 0 or self.context_window > 1_048_576:
            self.context_window = self.DEFAULT_CONTEXT_WINDOW
        if self.max_tokens <= 0 or self.max_tokens > 131_072:
            self.max_tokens = self.DEFAULT_MAX_TOKENS
        if self.temperature < 0 or self.temperature > 2:
            self.temperature = self.DEFAULT_TEMPERATURE
        safe_model = re.compile(r"^[a-zA-Z0-9_.:\-/]+$")
        for attr in ("model",):
            value = getattr(self, attr, "")
            if value and not safe_model.match(value):
                print(
                    f"{C.YELLOW}Warning: invalid {attr} name {value!r} — resetting to default.{C.RESET}",
                    file=__import__("sys").stderr,
                )
                setattr(self, attr, self.DEFAULT_MODEL)

    def _ensure_dirs(self):
        for directory in [self.config_dir, self.state_dir, self.sessions_dir]:
            try:
                os.makedirs(directory, mode=0o700, exist_ok=True)
            except PermissionError:
                print(f"Warning: Cannot create directory {directory} (permission denied).", file=__import__("sys").stderr)
            except OSError as e:
                print(f"Warning: Cannot create directory {directory}: {e}", file=__import__("sys").stderr)
