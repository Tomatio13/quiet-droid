import json
import locale
import os
import re
import sys
import threading
import time

from .config import Config
from .input_expansion import _resolve_reference
from .terminal import C, ansi, get_terminal_width, truncate_to_display_width

try:
    import readline

    HAS_READLINE = True
except ImportError:
    HAS_READLINE = False


SLASH_COMMAND_SPECS = [
    ("/help", "Show this help"),
    ("/exit", "Exit"),
    ("/quit", "Exit"),
    ("/q", "Exit"),
    ("/clear", "Clear conversation"),
    ("/model", "Show or switch model"),
    ("/models", "Show current model"),
    ("/status", "Session info"),
    ("/save", "Save session"),
    ("/compact", "Compress context"),
    ("/resume", "Use qd --resume"),
    ("/yes", "Auto-approve ON"),
    ("/no", "Auto-approve OFF"),
    ("/debug", "Toggle debug mode"),
]
SLASH_COMMANDS = [command for command, _ in SLASH_COMMAND_SPECS]


class TUI:
    _ANSI_RE = re.compile(r"\033\[[0-9;]*[a-zA-Z]")

    def __init__(self, config):
        self.config = config
        self.skill_names = []
        self._spinner_stop = threading.Event()
        self._spinner_thread = None
        self.is_interactive = sys.stdin.isatty() and sys.stdout.isatty()
        self._is_cjk = self._detect_cjk_locale()
        if HAS_READLINE:
            try:
                if os.path.isfile(config.history_file):
                    readline.read_history_file(config.history_file)
                readline.set_history_length(1000)

                def completer(text, state):
                    options = self.get_completion_candidates(text)
                    return options[state] if state < len(options) else None

                readline.set_completer(completer)
                readline.set_completer_delims(" \t\n")
                readline.parse_and_bind("tab: complete")
            except Exception:
                pass

    def set_skill_names(self, skill_names):
        self.skill_names = sorted(set(skill_names))

    def get_completion_candidates(self, text):
        if text.startswith("/"):
            return [cmd for cmd in SLASH_COMMANDS if cmd.startswith(text)]
        if text.startswith("$"):
            skill_commands = [f"${name}" for name in self.skill_names]
            return [cmd for cmd in skill_commands if cmd.startswith(text)]
        if text.startswith("@"):
            return self._get_file_completion_candidates(text)
        return []

    def _get_file_completion_candidates(self, text):
        raw_path = text[1:]
        base_dir = os.getcwd()
        search_dir = base_dir
        prefix = ""
        if raw_path:
            normalized = os.path.expanduser(raw_path)
            dirname, prefix = os.path.split(normalized)
            if dirname:
                candidate_dir = dirname if os.path.isabs(dirname) else os.path.join(base_dir, dirname)
                resolved_dir, error = _resolve_reference(candidate_dir, base_dir)
                if error or not resolved_dir or not os.path.isdir(resolved_dir):
                    return []
                search_dir = resolved_dir
        try:
            entries = os.listdir(search_dir)
        except OSError:
            return []
        candidates = []
        for entry in sorted(entries):
            if not entry.startswith(prefix):
                continue
            full_path = os.path.join(search_dir, entry)
            rel_path = os.path.relpath(full_path, base_dir)
            if os.path.isdir(full_path):
                rel_path += "/"
            candidates.append(f"@{rel_path}")
        return candidates

    def _detect_cjk_locale(self):
        try:
            lang = locale.getlocale()[0] or ""
        except Exception:
            lang = os.environ.get("LANG", "")
        if not lang:
            lang = os.environ.get("LANG", "")
        return any(lang.startswith(prefix) for prefix in ("ja", "zh", "ko", "ja_JP", "zh_CN", "zh_TW", "ko_KR"))

    def banner(self, config, model_ok=True):
        term_w = get_terminal_width()
        if term_w >= 82:
            banner_lines = [
                "   ██████╗ ██╗   ██╗██╗███████╗████████╗    ██████╗ ██████╗  █████╗ ██╗██████╗ ",
                "  ██╔═══██╗██║   ██║██║██╔════╝╚══██╔══╝    ██╔══██╗██╔══██╗██╔══██╗██║██╔══██╗",
                "  ██║   ██║██║   ██║██║█████╗     ██║       ██║  ██║██████╔╝██║  ██║██║██║  ██║",
                "  ██║▄▄ ██║██║   ██║██║██╔══╝     ██║       ██║  ██║██╔══██╗██║  ██║██║██║  ██║",
                "  ╚██████╔╝╚██████╔╝██║███████╗   ██║       ██████╔╝██║  ██║╚█████╔╝██║██████╔╝",
                "   ╚══▀▀═╝  ╚═════╝ ╚═╝╚══════╝   ╚═╝       ╚═════╝ ╚═╝  ╚═╝ ╚════╝ ╚═╝╚═════╝ ",
            ]
        elif term_w >= 50:
            banner_lines = [
                "  ╔═╗╦ ╦╦╔═╗╔╦╗  ╔╦╗╦═╗╔═╗╦╔╦╗",
                "  ║═╬╗║ ║║║╣  ║    ║║╠╦╝║ ║║ ║║",
                "  ╚═╝╚╚═╝╩╚═╝ ╩   ═╩╝╩╚═╚═╝╩═╩╝",
            ]
        else:
            banner_lines = ["  QUIET DROID"]
        gradient = [
            ansi("\033[38;5;31m"),
            ansi("\033[38;5;38m"),
            ansi("\033[38;5;44m"),
            ansi("\033[38;5;45m"),
            ansi("\033[38;5;51m"),
            ansi("\033[38;5;37m"),
        ]
        print()
        for i, line in enumerate(banner_lines):
            print(f"{gradient[i % len(gradient)]}{line}{C.RESET}")
        print(f"\n  {ansi(chr(27)+'[38;5;38m')}{C.BOLD}QUIET DROID{C.RESET}")
        print(f"  {ansi(chr(27)+'[38;5;44m')}API:{C.RESET} {config.base_url}")
        print(f"  {ansi(chr(27)+'[38;5;44m')}CWD:{C.RESET} {os.getcwd()}")
        if not model_ok:
            print(f"\n  {C.RED}Model '{config.model}' was not found by the API.{C.RESET}")
        if not config.yes_mode:
            print(f"  {C.DIM}Tip: use -y for auto-approve mode.{C.RESET}")
        print()

    def show_input_separator(self, plan_mode=False):
        sep_w = min(60, get_terminal_width() - 4)
        print(f"{C.DIM}{'·' * sep_w}{C.RESET}")

    def get_input(self, session=None, plan_mode=False, prefill=""):
        try:
            if prefill and HAS_READLINE:
                def hook():
                    readline.insert_text(prefill)
                    readline.redisplay()

                readline.set_startup_hook(hook)
            prompt = f"{ansi(chr(27)+'[38;5;51m')}❯{C.RESET} "
            if session:
                pct = min(int((session.get_token_estimate() / session.config.context_window) * 100), 100)
                prompt = f"{C.DIM}ctx:{pct}%{C.RESET} {prompt}"
            return input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        finally:
            if HAS_READLINE:
                readline.set_startup_hook()

    def get_multiline_input(self, session=None, plan_mode=False, prefill=""):
        self.show_input_separator(plan_mode=plan_mode)
        first_line = self.get_input(session=session, plan_mode=plan_mode, prefill=prefill)
        if first_line is None:
            return None
        if first_line.strip() == '"""':
            lines = []
            print(f"{C.DIM}  (multi-line input, end with \"\"\" on its own line){C.RESET}")
            while True:
                try:
                    line = input(f"{C.DIM}...{C.RESET} ")
                    if line.strip() == '"""':
                        break
                    lines.append(line)
                except (EOFError, KeyboardInterrupt):
                    print(f"\n{C.DIM}(Cancelled){C.RESET}")
                    return None
            return "\n".join(lines)
        if self._is_cjk and first_line.strip() and not first_line.strip().startswith("/"):
            if not hasattr(self, "_ime_hint_shown"):
                self._ime_hint_shown = True
                print(f"{C.DIM}  (IME mode: press Enter on empty line to send, \"\"\" for multiline){C.RESET}")
            lines = [first_line]
            while True:
                try:
                    line = input(f"{C.DIM}...{C.RESET} ")
                    if not line.strip():
                        break
                    lines.append(line)
                except (EOFError, KeyboardInterrupt):
                    print(f"\n{C.DIM}(Cancelled){C.RESET}")
                    return None
            return "\n".join(lines)
        return first_line

    def start_spinner(self, label):
        self.stop_spinner()
        self._spinner_stop.clear()

        def spin():
            frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            idx = 0
            while not self._spinner_stop.wait(0.08):
                print(f"\r  {C.DIM}{frames[idx % len(frames)]} {label}{C.RESET}", end="", flush=True)
                idx += 1
            print("\r" + " " * 100 + "\r", end="", flush=True)

        self._spinner_thread = threading.Thread(target=spin, daemon=True)
        self._spinner_thread.start()

    def stop_spinner(self):
        self._spinner_stop.set()
        if self._spinner_thread:
            self._spinner_thread.join(timeout=1)
            self._spinner_thread = None

    def start_tool_status(self, tool_name):
        self.start_spinner(f"Running {tool_name}")

    def show_tool_call(self, tool_name, params):
        summary = ""
        if tool_name == "Bash":
            summary = truncate_to_display_width(params.get("command", ""), max(20, get_terminal_width() - 20))
        elif "file_path" in params:
            summary = params["file_path"]
        elif "pattern" in params:
            summary = params["pattern"]
        print(f"\n  {ansi(chr(27)+'[38;5;226m')}tool{C.RESET}: {tool_name} {C.DIM}{summary}{C.RESET}")

    def show_tool_result(self, tool_name, output, is_error=False, duration=None, params=None):
        color = C.RED if is_error else C.DIM
        prefix = "error" if is_error else "result"
        duration_text = f" ({duration:.1f}s)" if duration is not None else ""
        text = str(output)
        if len(text) > 1200:
            text = text[:1200] + "\n...(truncated)"
        print(f"  {color}{prefix}{duration_text}:{C.RESET} {text}")

    def _render_markdown(self, text):
        print(text, end="")

    def show_sync_response(self, response, known_tools=None):
        message = response.get("choices", [{}])[0].get("message", {})
        content = message.get("content", "") or ""
        tool_calls = message.get("tool_calls") or []
        normalized = []
        for idx, tc in enumerate(tool_calls):
            function = tc.get("function", {})
            args = function.get("arguments", {})
            if not isinstance(args, str):
                args = json.dumps(args, ensure_ascii=False)
            normalized.append({
                "id": tc.get("id", f"call_{idx}"),
                "type": "function",
                "function": {"name": function.get("name", ""), "arguments": args},
            })
        if content:
            print(f"\n{C.BBLUE}droid{C.RESET}: ", end="")
            self._render_markdown(content)
            print()
        return content, normalized

    def stream_response(self, response_iter, known_tools=None):
        text_parts = []
        tool_calls = {}
        print(f"\n{C.BBLUE}droid{C.RESET}: ", end="", flush=True)
        for raw_line in response_iter:
            if not raw_line:
                continue
            if isinstance(raw_line, bytes):
                raw_line = raw_line.decode("utf-8", errors="replace")
            for line in raw_line.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    print()
                    normalized = []
                    for idx in sorted(tool_calls):
                        entry = tool_calls[idx]
                        normalized.append({
                            "id": entry["id"],
                            "type": "function",
                            "function": {
                                "name": entry["name"],
                                "arguments": entry["arguments"] or "{}",
                            },
                        })
                    return "".join(text_parts), normalized
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                choice = (data.get("choices") or [{}])[0]
                delta = choice.get("delta", {})
                content = delta.get("content")
                if content:
                    text_parts.append(content)
                    print(content, end="", flush=True)
                for tc in delta.get("tool_calls") or []:
                    index = tc.get("index", 0)
                    entry = tool_calls.setdefault(index, {"id": tc.get("id") or f"call_{index}", "name": "", "arguments": ""})
                    if tc.get("id"):
                        entry["id"] = tc["id"]
                    function = tc.get("function", {})
                    if function.get("name"):
                        entry["name"] = function["name"]
                    if function.get("arguments"):
                        entry["arguments"] += function["arguments"]
        print()
        return "".join(text_parts), []

    def ask_permission(self, tool_name, params, reason=""):
        summary = tool_name
        if tool_name == "Bash":
            summary = params.get("command", "")
        elif "file_path" in params:
            summary = params["file_path"]
        print(f"\n{C.YELLOW}Permission required:{C.RESET} {tool_name}")
        if summary:
            print(f"  {C.DIM}{truncate_to_display_width(summary, 120)}{C.RESET}")
        if reason:
            print(f"  {C.DIM}{truncate_to_display_width(reason, 120)}{C.RESET}")
        while True:
            answer = input(f"{C.CYAN}Allow? [y]es / [n]o / [a]llow tool / [Y]es mode: {C.RESET}").strip()
            lowered = answer.lower()
            if lowered in {"", "y", "yes"}:
                return True
            if lowered in {"n", "no"}:
                return False
            if lowered in {"a", "allow"}:
                return "allow_all"
            if answer == "Y":
                return "yes_mode"

    def show_help(self):
        _c51 = ansi("\033[38;5;51m")
        _c87 = ansi("\033[38;5;87m")
        _c198 = ansi("\033[38;5;198m")
        sep = "━" * min(36, get_terminal_width() - 4)
        ime_hint = f"\n  {C.DIM}IME: 空行で送信 / \"\"\" で複数行{C.RESET}" if self._is_cjk else ""
        command_lines = "\n".join(
            f"  {_c198}{cmd:<18}{C.RESET} {desc}" for cmd, desc in SLASH_COMMAND_SPECS
        )
        print(f"""
  {_c51}━━ Commands {sep[10:]}{C.RESET}
{command_lines}
  {_c198}\"\"\"{C.RESET}                Multi-line input
  {C.DIM}/ + Enter      show commands / Tab for completion{C.RESET}
  {C.DIM}$ + Enter      show skills / Tab for completion{C.RESET}
  {C.DIM}@path          inline file / Tab for completion{C.RESET}
  {_c51}━━ Tools {sep[8:]}{C.RESET}
  {_c87}Bash, Read, Write, Edit, Glob, Grep, SubAgent, ParallelAgents{C.RESET}{ime_hint}
""")

    def show_skill_list(self):
        _c51 = ansi("\033[38;5;51m")
        _c87 = ansi("\033[38;5;87m")
        if not self.skill_names:
            print(f"\n  {_c51}━━ Skills ━━━━━━━━━━━━━━━━━━━{C.RESET}")
            print(f"  {C.DIM}No skills loaded.{C.RESET}")
            return
        skills_text = ", ".join(f"${name}" for name in self.skill_names)
        print(f"\n  {_c51}━━ Skills ━━━━━━━━━━━━━━━━━━━{C.RESET}")
        print(f"  {_c87}{skills_text}{C.RESET}")
        print(f"  {C.DIM}Type $name to invoke a skill hint in your prompt. Tab completes names.{C.RESET}")

    def show_status(self, session, config):
        tokens = session.get_token_estimate()
        messages = len(session.messages)
        pct = min(int((tokens / config.context_window) * 100), 100)
        bar_len = 20
        filled = int(bar_len * pct / 100)
        bar_color = ansi("\033[38;5;46m") if pct < 50 else ansi("\033[38;5;226m") if pct < 80 else ansi("\033[38;5;196m")
        bar = bar_color + "█" * filled + C.DIM + "░" * (bar_len - filled) + C.RESET
        print(f"""
  {ansi('\033[38;5;51m')}━━ Status ━━━━━━━━━━━━━━━━━━━{C.RESET}
  {ansi('\033[38;5;87m')}Session{C.RESET}   {session.session_id}
  {ansi('\033[38;5;87m')}Messages{C.RESET}  {messages}
  {ansi('\033[38;5;87m')}Context{C.RESET}   [{bar}] {pct}%  ~{tokens}/{config.context_window}
  {ansi('\033[38;5;87m')}Model{C.RESET}     {config.model}
  {ansi('\033[38;5;87m')}CWD{C.RESET}       {os.getcwd()}
""")
