# tiny-agent

OpenAI互換APIを使う、最小構成のターミナル向けコーディングエージェントです。  
単一ファイル版から分離し、`basic agent + skills loader` に絞った構成にしています。

## Features

- OpenAI互換APIの `/v1/chat/completions` を利用
- 基本ツールのみ搭載
  - `Bash`
  - `Read`
  - `Write`
  - `Edit`
  - `Glob`
  - `Grep`
- Skills の自動読込
- 対話モードと one-shot モード

## Requirements

- Python 3.10+
- OpenAI互換APIサーバ
  - `/v1/models`
  - `/v1/chat/completions`

## Configuration

設定方法は3通りあります。

1. 環境変数
2. CLI引数
3. `~/.config/tiny-agent/config`

優先順位は `CLI引数 > 環境変数 > configファイル > デフォルト値` です。

初回起動時には設定ディレクトリと状態保存ディレクトリを自動作成します。

- 設定ディレクトリ: `~/.config/tiny-agent`
- 状態保存ディレクトリ: `~/.local/state/tiny-agent`
- セッション保存先: `~/.local/state/tiny-agent/sessions`

`config` ファイル本体は自動生成しません。必要な場合だけ `~/.config/tiny-agent/config` を手動で作成してください。

### Environment Variables

```bash
export OPENAI_BASE_URL="http://localhost:8000/v1"
export OPENAI_API_KEY="your-api-key"
export TINY_AGENT_MODEL="gpt-4.1-mini"
export TINY_AGENT_SIDECAR_MODEL="qwen3:4b"
export TINY_AGENT_DEBUG="1"
```

### Config File

`~/.config/tiny-agent/config`

```ini
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_API_KEY=your-api-key
MODEL=gpt-4.1-mini
MAX_TOKENS=8192
TEMPERATURE=0.7
CONTEXT_WINDOW=32768
SIDECAR_MODEL=qwen3:4b
```

### CLI

```bash
python3 tiny-agent.py --base-url http://localhost:8000/v1 --api-key your-api-key --model gpt-4.1-mini
```

## Usage

対話モード:

```bash
python3 tiny-agent.py
```

one-shot:

```bash
python3 tiny-agent.py -p "pwd を実行して"
```

ヘルプ:

```bash
python3 tiny-agent.py --help
```

## Interactive Commands

- `/help`
- `/exit`
- `/clear`
- `/status`
- `/save`
- `/compact`
- `/model`
- `/yes`
- `/no`
- `/debug`

## Skills

以下のディレクトリにある `*.md` を自動で読み込みます。

- `~/.config/tiny-agent/skills/`
- `.tiny-agent/skills/`
- `./skills/`

Skills はシステムプロンプトへ注入されます。

## Config Example

最小構成の例:

```ini
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_API_KEY=your-api-key
MODEL=gpt-4.1-mini
```

## Project Structure

```text
tiny-agent.py
tiny_agent/
  app.py
  agent.py
  client.py
  config.py
  prompts.py
  session.py
  skills.py
  terminal.py
  tui.py
  tools/
    base.py
    bash.py
    filesystem.py
    registry.py
```

## Notes

- `OPENAI_BASE_URL` は `/v1` 付きでも無しでも動くようにしています。
- `OPENAI_API_KEY` が必要なサーバでは設定してください。
- 互換目的で `OLLAMA_HOST` と `--ollama-host` も受けますが、内部的には `base_url` として扱います。

## Verification

構文確認:

```bash
python3 -m py_compile tiny-agent.py tiny_agent/*.py tiny_agent/tools/*.py
```
