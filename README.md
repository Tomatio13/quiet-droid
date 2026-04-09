# Quiet-AI

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
3. `~/.config/quiet-ai/config`

優先順位は `CLI引数 > 環境変数 > configファイル > デフォルト値` です。

初回起動時には設定ディレクトリと状態保存ディレクトリを自動作成します。

- 設定ディレクトリ: `~/.config/quiet-ai`
- 状態保存ディレクトリ: `~/.local/state/quiet-ai`
- セッション保存先: `~/.local/state/quiet-ai/sessions`

`config` ファイル本体は自動生成しません。必要な場合だけ `~/.config/quiet-ai/config` を手動で作成してください。

### Environment Variables

```bash
export OPENAI_BASE_URL="http://localhost:8000/v1"
export OPENAI_API_KEY="your-api-key"
export QUIET_AI_MODEL="gpt-4.1-mini"
export QUIET_AI_DEBUG="1"
```

### Config File

`~/.config/quiet-ai/config`

```ini
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_API_KEY=your-api-key
MODEL=gpt-4.1-mini
MAX_TOKENS=8192
TEMPERATURE=0.7
CONTEXT_WINDOW=32768
```

### CLI

```bash
python3 quiet-ai.py --base-url http://localhost:8000/v1 --api-key your-api-key --model gpt-4.1-mini
```

## Usage

対話モード:

```bash
python3 quiet-ai.py
```

one-shot:

```bash
python3 quiet-ai.py -p "pwd を実行して"
```

ヘルプ:

```bash
python3 quiet-ai.py --help
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

- `~/.config/quiet-ai/skills/`
- `.quiet-ai/skills/`
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
quiet-ai.py
quiet_ai/
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
python3 -m py_compile quiet-ai.py quiet_ai/*.py quiet_ai/tools/*.py
```
