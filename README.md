<h1 align="center">Quiet Droid</h1>

<p align="center">
  <strong>Minimal Terminal Coding Agent for OpenAI-Compatible APIs</strong>
</p>

<p align="center">
  <a href="README_JP.md"><img src="https://img.shields.io/badge/ドキュメント-日本語-white.svg" alt="Japanese documentation"></a>
  <a href="README.md"><img src="https://img.shields.io/badge/english-document-white.svg" alt="English documentation"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Quiet-Droid-111111?style=for-the-badge&logo=android&logoColor=A4C639" alt="Quiet Droid">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/API-OpenAI%20Compatible-black" alt="OpenAI Compatible API">
  <img src="https://img.shields.io/badge/UI-Terminal-green" alt="Terminal UI">
</p>

<p align="center">
  Quiet until it matters: a terminal coding agent for focused local workflows.
</p>

<p align="center">
  <img src="asset/screen.png" alt="Quiet Droid terminal screenshot" width="900">
</p>

## ✨ Features

- Uses the OpenAI-compatible `/v1/chat/completions` API
  - Uses `/chat/completions` instead when the `model` name starts with `glm-`
- Ships with a small core tool set
  - `Bash`
  - `Read`
  - `Write`
  - `Edit`
  - `Glob`
  - `Grep`
- Agent helper tools
  - `SubAgent`
  - `ParallelAgents`
- Automatic Skills loading
- Hooks
- Automatic project instruction loading from `AGENTS.md`, `CLAUDE.md`, and `.quiet-droid.json`
- Interactive mode and one-shot mode
- Session storage, input history, and permission management

## 🚀 Quick Start

Use the `qd` command:

```bash
pipx install .
export OPENAI_BASE_URL="http://localhost:8000/v1"
export OPENAI_API_KEY="your-api-key"
qd
```

Run the script directly:

```bash
export OPENAI_BASE_URL="http://localhost:8000/v1"
export OPENAI_API_KEY="your-api-key"
python3 quiet-droid.py
```

Run a one-shot prompt:

```bash
python3 quiet-droid.py -p "run pwd"
```

On Debian and Ubuntu systems, PEP 668 can make `pip install -e .` fail. Use `pipx install .`, or create a virtual environment and run `pip install -e .` inside it.

## 📦 Installation

With `pipx`:

```bash
pipx install .
```

Update:

```bash
pipx reinstall .
```

Uninstall:

```bash
pipx uninstall quiet-droid
```

With a virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Remove the virtual environment install:

```bash
deactivate  # only if the environment is active
rm -rf .venv
```

After installation, these commands are available:

```bash
qd --help
quiet-droid --help
```

## 📋 Requirements

- Python 3.10+
- OpenAI-compatible API server
  - `/v1/chat/completions`

## ⚙️ Configuration

Quiet Droid accepts configuration from three sources:

1. Environment variables
2. CLI arguments
3. `~/.config/quiet-droid/config`

Precedence is `CLI arguments > config file > environment variables > defaults`.

On first launch, Quiet Droid creates its config and state directories automatically.
It does not choose a model automatically. Set one explicitly with `--model`, `MODEL`, `QUIET_DROID_MODEL`, or `OPENAI_MODEL`.

Linux / macOS:

- Config directory: `~/.config/quiet-droid`
- Permission config: `~/.config/quiet-droid/permissions.json`
- State directory: `~/.local/state/quiet-droid`
- Session directory: `~/.local/state/quiet-droid/sessions`
- Input history: `~/.local/state/quiet-droid/history`

Windows:

- Config directory: `%LOCALAPPDATA%\quiet-droid`
- Config file: `%LOCALAPPDATA%\quiet-droid\config`
- Permission config: `%LOCALAPPDATA%\quiet-droid\permissions.json`
- State directory: `%LOCALAPPDATA%\quiet-droid`
- Session directory: `%LOCALAPPDATA%\quiet-droid\sessions`
- Input history: `%LOCALAPPDATA%\quiet-droid\history`

The `config` file itself is not generated automatically. Create `~/.config/quiet-droid/config` manually only when you need it.

Global instruction loading prefers `~/.config/quiet-droid/CLAUDE.md`. If that file does not exist, Quiet Droid loads `~/.config/quiet-droid/AGENTS.md`.

### Environment Variables

```bash
export OPENAI_BASE_URL="http://localhost:8000/v1"
export OPENAI_API_KEY="your-api-key"
export QUIET_DROID_MODEL="gpt-4.1-mini"
export OPENAI_MODEL="gpt-4.1-mini"
export QUIET_DROID_DEBUG="1"
```

Model selection prefers `QUIET_DROID_MODEL`. `OPENAI_MODEL` is supported for compatibility.

For compatibility, `OLLAMA_HOST` can also be used as a replacement for `OPENAI_BASE_URL`.

When using `glm-*` models from `z.ai`, set `OPENAI_BASE_URL` to the API root instead of a `/v1` URL.

```bash
export OPENAI_BASE_URL="https://api.z.ai/api/paas/v4"
export QUIET_DROID_MODEL="glm-4.5"
```

### Config File

`~/.config/quiet-droid/config`

```ini
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_API_KEY=your-api-key
MODEL=gpt-4.1-mini
OPENAI_MODEL=gpt-4.1-mini
MAX_TOKENS=8192
TEMPERATURE=0.7
CONTEXT_WINDOW=32768
```

In the config file, `MODEL` takes precedence. `OPENAI_MODEL` is supported for compatibility.

### CLI

```bash
python3 quiet-droid.py --base-url http://localhost:8000/v1 --api-key your-api-key --model gpt-4.1-mini
```

Common additional options:

```bash
python3 quiet-droid.py \
  --max-tokens 8192 \
  --temperature 0.7 \
  --context-window 32768 \
  --debug \
  --yes
```

Resume a saved conversation:

```bash
qd --resume
qd --session-id 20260429_123456_ab12cd
qd --list-sessions
```

## 💻 Usage

Interactive mode:

```bash
qd
```

One-shot mode:

```bash
qd -p "run pwd"
```

Help:

```bash
qd --help
```

## ⌨️ Interactive Commands

- `/help`
- `/exit`
- `/clear`
- `/status`
- `/save`
- `/compact`
- `/model`
- `/models`
- `/yes`
- `/no`
- `/debug`

Plain `exit`, `quit`, or `bye` also ends an interactive session.
Press `Tab` to complete slash commands. Enter `/` by itself to list available commands.
Press `Tab` to complete `$skill` names. Enter `$` by itself to list loaded Skills.

## 🧩 Skills

Quiet Droid automatically loads `*.md` files from these directories:

- `~/.config/quiet-droid/skills/`
- `.quiet-droid/skills/`
- `./skills/`

Skills are injected into the system prompt.
Loaded Skill names are also used for Tab completion and listing, so you can easily reference them during a session with input such as `$plan`.

## 📜 Project Instructions

Quiet Droid searches upward from the current directory and automatically loads these project instruction files:

- `.quiet-droid.json`
- `CLAUDE.md`
- `AGENTS.md`

Discovered content is injected into the system prompt in order. This supports workflows where `AGENTS.md` defines operating rules, output language, or project-specific guidance.
When multiple instruction files exist in the same directory, Quiet Droid uses only the first matched file for that directory.
In the global config directory, `CLAUDE.md` takes precedence over `AGENTS.md`.

## 🪝 Hooks

Quiet Droid supports `command` hooks as a minimal hook implementation. Hook config files are loaded in this order:

- `~/.config/quiet-droid/hooks.json`
- `./.quiet-droid/hooks.json`

See [docs/hooks.md](docs/hooks.md) for supported events, hook types, and examples.

Claude Code official documentation:

- https://code.claude.com/docs/ja/hooks

## 📝 Config Example

Minimal config:

```ini
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_API_KEY=your-api-key
MODEL=gpt-4.1-mini
```

## 📎 Notes

- `OPENAI_BASE_URL` works with or without a `/v1` suffix.
- Set `OPENAI_API_KEY` when your server requires one.
- Startup fails when no model is configured.
- `--yes` and `--dangerously-skip-permissions` have the same meaning: tool confirmations are approved automatically.
- For compatibility, `OLLAMA_HOST` and `--ollama-host` are accepted and treated internally as `base_url`.

## 💐 Acknowledgments

Thanks to Professor Yoichi Ochiai at the University of Tsukuba for publishing [vibe-local](https://github.com/ochyai/vibe-local).

## 📄 License

MIT
