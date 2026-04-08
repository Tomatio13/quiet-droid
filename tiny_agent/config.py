import argparse
import json
import os
import platform
import re
import shutil
import urllib.parse
import urllib.request

from . import __version__
from .terminal import C


def _get_ram_gb() -> int:
    try:
        if platform.system() == "Darwin":
            import subprocess

            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0:
                return max(1, int(int(result.stdout.strip()) / (1024 ** 3)))
        elif os.name == "posix":
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            return max(1, int((pages * page_size) / (1024 ** 3)))
    except Exception:
        pass
    return 8


def _get_vram_gb() -> int:
    return 0


class Config:
    APP_NAME = "tiny-agent"
    DEFAULT_BASE_URL = "http://localhost:8000/v1"
    DEFAULT_MODEL = ""
    DEFAULT_SIDECAR = ""
    DEFAULT_MAX_TOKENS = 8192
    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_CONTEXT_WINDOW = 32768

    MODEL_CONTEXT_SIZES = {
        "deepseek-v3:671b": 131072,
        "qwen3-coder:30b": 65536,
        "qwen3:14b": 65536,
        "qwen3:8b": 32768,
        "qwen3:4b": 16384,
        "qwen3:1.7b": 4096,
        "llama3.1:8b": 32768,
        "llama3.2:3b": 8192,
        "deepseek-coder:6.7b": 16384,
        "codellama:7b": 16384,
    }

    MODEL_TIERS = [
        ("deepseek-v3:671b", 256, "S"),
        ("qwen3-coder:30b", 32, "B"),
        ("qwen3:14b", 16, "C"),
        ("qwen3:8b", 8, "D"),
        ("llama3.1:8b", 8, "D"),
        ("deepseek-coder:6.7b", 8, "D"),
        ("codellama:7b", 8, "D"),
        ("qwen3:4b", 4, "E"),
        ("qwen3:1.7b", 2, "E"),
        ("llama3.2:3b", 4, "E"),
    ]

    _SIDECAR_CANDIDATES = ["qwen3:8b", "qwen3:4b", "qwen3:1.7b", "llama3.2:3b"]

    def __init__(self):
        self.base_url = self.DEFAULT_BASE_URL
        self.api_key = ""
        self.model = self.DEFAULT_MODEL
        self.sidecar_model = self.DEFAULT_SIDECAR
        self.max_tokens = self.DEFAULT_MAX_TOKENS
        self.temperature = self.DEFAULT_TEMPERATURE
        self.context_window = self.DEFAULT_CONTEXT_WINDOW
        self.prompt = None
        self.yes_mode = False
        self.debug = False
        self.session_id = None
        self.cwd = os.getcwd()

        if os.name == "nt":
            appdata = os.environ.get("LOCALAPPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Local"))
            self.config_dir = os.path.join(appdata, self.APP_NAME)
            self.state_dir = os.path.join(appdata, self.APP_NAME)
        else:
            home = os.path.expanduser("~")
            self.config_dir = os.path.join(home, ".config", self.APP_NAME)
            self.state_dir = os.path.join(home, ".local", "state", self.APP_NAME)

        self.config_file = os.path.join(self.config_dir, "config")
        self.permissions_file = os.path.join(self.config_dir, "permissions.json")
        self.sessions_dir = os.path.join(self.state_dir, "sessions")
        self.history_file = os.path.join(self.state_dir, "history")

    def load(self, argv=None):
        self._load_config_file()
        self._load_env()
        self._load_cli_args(argv)
        self._auto_detect_model()
        self._validate_ollama_host()
        self._ensure_dirs()
        return self

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
                    if key == "MODEL" and val:
                        self.model = val
                    elif key == "SIDECAR_MODEL" and val:
                        self.sidecar_model = val
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
        if os.environ.get("TINY_AGENT_MODEL"):
            self.model = os.environ["TINY_AGENT_MODEL"]
        if os.environ.get("TINY_AGENT_SIDECAR_MODEL"):
            self.sidecar_model = os.environ["TINY_AGENT_SIDECAR_MODEL"]
        if os.environ.get("TINY_AGENT_DEBUG") == "1":
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
            prog="tiny-agent",
            description="Coding agent powered by an OpenAI-compatible API",
        )
        parser.add_argument("-p", "--prompt", help="One-shot prompt (non-interactive)")
        parser.add_argument("-m", "--model", help="Model name")
        parser.add_argument("-y", "--yes", action="store_true", help="Auto-approve all tool calls")
        parser.add_argument("--debug", action="store_true", help="Debug mode")
        parser.add_argument("--base-url", "--openai-base-url", dest="base_url", help="OpenAI-compatible base URL")
        parser.add_argument("--api-key", "--openai-api-key", dest="api_key", help="API key for the OpenAI-compatible API")
        parser.add_argument("--ollama-host", dest="base_url_legacy", help=argparse.SUPPRESS)
        parser.add_argument("--max-tokens", type=int, help="Max output tokens")
        parser.add_argument("--temperature", type=float, help="Sampling temperature")
        parser.add_argument("--context-window", type=int, help="Context window size")
        parser.add_argument("--version", action="version", version=f"tiny-agent {__version__}")
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

    def _query_installed_models(self):
        parsed = urllib.parse.urlparse(self.base_url)
        if not parsed.scheme or not parsed.netloc:
            return []
        path = parsed.path.rstrip("/")
        if path.endswith("/v1"):
            url = urllib.parse.urlunparse(parsed._replace(path=path + "/models"))
        else:
            url = urllib.parse.urlunparse(parsed._replace(path=path + "/v1/models"))
        try:
            request = urllib.request.Request(url)
            if self.api_key:
                request.add_header("Authorization", f"Bearer {self.api_key}")
            resp = urllib.request.urlopen(request, timeout=3)
            try:
                data = json.loads(resp.read(10 * 1024 * 1024))
            finally:
                resp.close()
            return [m.get("id", "").strip() for m in data.get("data", []) if m.get("id")]
        except Exception:
            return []

    def _pick_best_model(self, installed, ram_gb):
        installed_set = set(installed)
        for model_name, min_ram, _ in self.MODEL_TIERS:
            if ram_gb < min_ram:
                continue
            if model_name in installed_set:
                return model_name
            if model_name + ":latest" in installed_set:
                return model_name + ":latest"
        return None

    def _pick_sidecar(self, installed, main_model):
        installed_set = set(installed)
        for candidate in self._SIDECAR_CANDIDATES:
            if candidate == main_model:
                continue
            if candidate in installed_set:
                self.sidecar_model = candidate
                return
            if candidate + ":latest" in installed_set:
                self.sidecar_model = candidate + ":latest"
                return

    def _auto_detect_model(self):
        if self.model:
            self._apply_context_window(self.model)
            return
        ram_gb = max(_get_ram_gb(), _get_vram_gb())
        installed = self._query_installed_models()
        if installed:
            best = self._pick_best_model(installed, ram_gb)
            if best:
                self.model = best
                self._apply_context_window(best)
                if not self.sidecar_model:
                    self._pick_sidecar(installed, best)
                return
        if ram_gb >= 32:
            self.model = "qwen3-coder:30b"
        elif ram_gb >= 16:
            self.model = "qwen3:8b"
        else:
            self.model = "qwen3:1.7b"
            self.context_window = 4096
        if not self.sidecar_model:
            if ram_gb >= 32:
                self.sidecar_model = "qwen3:8b"
            elif ram_gb >= 16:
                self.sidecar_model = "qwen3:1.7b"

    def _apply_context_window(self, model_name):
        if self.context_window != self.DEFAULT_CONTEXT_WINDOW:
            return
        for name, ctx in self.MODEL_CONTEXT_SIZES.items():
            if name in model_name or model_name in name:
                self.context_window = ctx
                return

    @classmethod
    def get_model_tier(cls, model_name):
        for name, min_ram, tier in cls.MODEL_TIERS:
            if name in model_name or model_name.split(":")[0] == name.split(":")[0]:
                return tier, min_ram
        return None, None

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
        for attr in ("model", "sidecar_model"):
            value = getattr(self, attr, "")
            if value and not safe_model.match(value):
                print(
                    f"{C.YELLOW}Warning: invalid {attr} name {value!r} — resetting to default.{C.RESET}",
                    file=__import__("sys").stderr,
                )
                setattr(self, attr, "" if attr == "sidecar_model" else self.DEFAULT_MODEL)

    def _ensure_dirs(self):
        for directory in [self.config_dir, self.state_dir, self.sessions_dir]:
            try:
                os.makedirs(directory, mode=0o700, exist_ok=True)
            except PermissionError:
                print(f"Warning: Cannot create directory {directory} (permission denied).", file=__import__("sys").stderr)
            except OSError as e:
                print(f"Warning: Cannot create directory {directory}: {e}", file=__import__("sys").stderr)
