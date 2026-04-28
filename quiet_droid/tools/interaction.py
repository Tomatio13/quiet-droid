import threading

from .base import Tool
from ..terminal import C, ansi


_print_lock = threading.Lock()


class AskUserQuestionTool(Tool):
    name = "AskUserQuestion"
    description = (
        "Ask the user a clarifying question during execution. "
        "Present options when useful and return the user's answer."
    )
    parameters = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The question to ask the user"},
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional choices for the user. The user can also type a custom answer.",
            },
        },
        "required": ["question"],
    }

    def execute(self, params):
        question = params.get("question", "")
        options = params.get("options", [])
        if not question:
            return "Error: question is required"
        if not isinstance(options, list):
            options = []

        with _print_lock:
            print(f"\n{ansi(C.CYAN)}{C.BOLD}Question:{C.RESET} {question}")
            if options:
                for idx, option in enumerate(options, start=1):
                    print(f"  {ansi(C.CYAN)}{idx}.{C.RESET} {option}")
                print(f"  {C.DIM}Enter number or type your own answer:{C.RESET}")
            else:
                print(f"  {C.DIM}Type your answer:{C.RESET}")

        try:
            answer = input(f"  {ansi(C.CYAN)}>{C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            return "User cancelled the question."

        if not answer:
            return "User provided no answer."
        if options and answer.isdigit():
            idx = int(answer) - 1
            if 0 <= idx < len(options):
                return f"User chose: {options[idx]}"
        return f"User answered: {answer}"
