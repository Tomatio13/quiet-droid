import os
import signal
import sys
import time

from .agent import Agent
from .client import OpenAICompatClient
from .config import Config
from .hooks import HookManager
from .prompts import build_system_prompt
from .session import Session
from .skills import load_skills
from .terminal import C, ansi, init_terminal_colors
from .tools import MultiAgentCoordinator, ParallelAgentTool, PermissionMgr, SubAgentTool, ToolRegistry
from .tui import HAS_READLINE, TUI, readline


def main():
    init_terminal_colors()
    config = Config().load()
    hooks = None
    session = None

    tui = TUI(config)
    if not config.model:
        print(f"\n{C.RED}モデルが設定されていません。{C.RESET}")
        print(f"{C.DIM}--model、QUIET_DROID_MODEL、OPENAI_MODEL、または config の MODEL を指定してください。{C.RESET}")
        if sys.exit:
            sys.exit(1)

    if not config.prompt:
        tui.banner(config, model_ok=True)

    client = OpenAICompatClient(config)
    system_prompt = build_system_prompt(config)
    skills = load_skills(config)
    tui.set_skill_names(skills.keys())
    if skills:
        system_prompt += "\n# Loaded Skills\n"
        system_prompt += "The following skill metadata was loaded at startup. Load full SKILL.md instructions only when the user explicitly invokes a skill.\n"
        for skill in skills.values():
            system_prompt += "\n".join(skill.summary_lines()) + "\n"
        if config.debug:
            print(f"{C.DIM}[debug] Loaded {len(skills)} skills: {', '.join(skills.keys())}{C.RESET}", file=sys.stderr)

    session = Session(config, system_prompt)
    session.set_client(client)
    hooks = HookManager(config, session=session)
    session.set_hooks(hooks)
    registry = ToolRegistry().register_defaults()
    permissions = PermissionMgr(config, hooks=hooks)
    registry.register(SubAgentTool(config, client, registry, permissions, hooks))
    coordinator = MultiAgentCoordinator(config, client, registry, permissions, hooks)
    registry.register(ParallelAgentTool(coordinator))
    agent = Agent(config, client, registry, permissions, session, tui, hooks, skills=skills)
    hooks.emit("SessionStart", {"source": "prompt" if config.prompt else "interactive"})

    def signal_handler(sig, frame):
        agent.interrupt()
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, signal_handler)

    try:
        if config.prompt:
            agent.run(config.prompt)
            session.save()
            return

        last_ctrl_c = [0.0]
        session_start = time.time()

        while True:
            try:
                user_input = tui.get_multiline_input(session=session)
                if user_input is None:
                    break
                user_input = user_input.strip()
                if not user_input:
                    continue

                if user_input.lower() in {"exit", "exit;", "quit", "quit;", "bye", "bye;"}:
                    session.save()
                    elapsed = int(time.time() - session_start)
                    mins, secs = divmod(elapsed, 60)
                    duration = f"{mins}m {secs}s" if mins else f"{secs}s"
                    print(f"\n  {ansi(chr(27)+'[38;5;51m')}✦ Session saved. Duration: {duration}.{C.RESET}")
                    break

                if user_input == "/":
                    tui.show_help()
                    continue

                if user_input == "$":
                    tui.show_skill_list()
                    continue

                if user_input.startswith("/"):
                    cmd = user_input.split()[0].lower()
                    if cmd in {"/exit", "/quit", "/q"}:
                        session.save()
                        print(f"\n  {ansi(chr(27)+'[38;5;51m')}✦ Session saved.{C.RESET}")
                        break
                    if cmd == "/help":
                        tui.show_help()
                        continue
                    if cmd == "/clear":
                        session.save()
                        old_sid = session.session_id
                        session.messages.clear()
                        session._token_estimate = 0
                        session.session_id = time.strftime("%Y%m%d_%H%M%S") + "_" + __import__("uuid").uuid4().hex[:6]
                        print(f"{C.GREEN}Conversation cleared.{C.RESET}")
                        print(f"{C.DIM}Previous session saved as: {old_sid}{C.RESET}")
                        continue
                    if cmd == "/status":
                        tui.show_status(session, config)
                        continue
                    if cmd == "/save":
                        session.save()
                        filepath = os.path.join(config.sessions_dir, f"{session.session_id}.jsonl")
                        print(f"{C.GREEN}Session saved: {session.session_id}{C.RESET}")
                        print(f"{C.DIM}  {filepath}{C.RESET}")
                        continue
                    if cmd == "/compact":
                        before = session.get_token_estimate()
                        session.compact_if_needed(force=True)
                        after = session.get_token_estimate()
                        print(f"{C.GREEN}Compacted: {before} -> {after} tokens{C.RESET}" if after < before else f"{C.DIM}Already compact ({after} tokens){C.RESET}")
                        continue
                    if cmd in {"/model", "/models"}:
                        parts = user_input.split(maxsplit=1)
                        if len(parts) > 1 and cmd == "/model":
                            new_model = parts[1].strip()
                            if not __import__("re").match(r"^[a-zA-Z0-9_.:\-/]+$", new_model):
                                print(f"{C.RED}Invalid model name: {new_model!r}{C.RESET}")
                                continue
                            config.model = new_model
                            print(f"{C.GREEN}Switched to model: {new_model}{C.RESET}")
                        else:
                            print(f"\n  {C.BOLD}Current model:{C.RESET} {ansi(chr(27)+'[38;5;51m')}{config.model}{C.RESET}")
                            print(f"  {C.DIM}Context window: {config.context_window} tokens{C.RESET}")
                        continue
                    if cmd == "/yes":
                        config.yes_mode = True
                        permissions.yes_mode = True
                        print(f"{C.GREEN}Auto-approve enabled for this session.{C.RESET}")
                        continue
                    if cmd == "/no":
                        config.yes_mode = False
                        permissions.yes_mode = False
                        print(f"{C.GREEN}Auto-approve disabled for this session.{C.RESET}")
                        continue
                    if cmd == "/debug":
                        config.debug = not config.debug
                        print(f"  Debug mode: {C.GREEN if config.debug else C.RED}{'ON' if config.debug else 'OFF'}{C.RESET}")
                        continue
                    print(f"{C.YELLOW}Unknown command. Type /help for available commands.{C.RESET}")
                    continue

                agent.run(user_input)
                session.save()
            except KeyboardInterrupt:
                now = time.time()
                if now - last_ctrl_c[0] < 1.5:
                    session.save()
                    break
                last_ctrl_c[0] = now
                print(f"\n{C.DIM}(Ctrl+C again within 1.5s to exit, or type /exit){C.RESET}")
            except EOFError:
                break
    finally:
        if session is not None:
            session.save()
        if hooks is not None:
            hooks.emit("SessionEnd", {})
        if HAS_READLINE:
            try:
                readline.write_history_file(config.history_file)
            except Exception:
                pass
        print(f"\n  {ansi(chr(27)+'[38;5;51m')}✦ Goodbye! ✦{C.RESET}")
