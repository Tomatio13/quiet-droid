import os
import shutil
import sys
import threading
import unicodedata


_print_lock = threading.Lock()


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"
    BBLUE = "\033[94m"
    _enabled = True

    @classmethod
    def disable(cls):
        for attr in dir(cls):
            if attr.isupper() and isinstance(getattr(cls, attr), str) and attr != "_enabled":
                setattr(cls, attr, "")
        cls._enabled = False


def init_terminal_colors():
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass

    if (not sys.stdout.isatty()
            or os.environ.get("NO_COLOR") is not None
            or os.environ.get("TERM") == "dumb"):
        C.disable()


def ansi(code: str) -> str:
    return code if C._enabled else ""


def get_terminal_width(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except Exception:
        return default


def display_width(text: str) -> int:
    total = 0
    for ch in text:
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def truncate_to_display_width(text: str, max_width: int) -> str:
    width = 0
    for i, ch in enumerate(text):
        char_width = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if width + char_width > max_width:
            return text[:i] + "..."
        width += char_width
    return text

