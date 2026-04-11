<h1 align="center">Quiet Droid</h1>

<p align="center">
  <strong>Minimal Terminal Coding Agent for OpenAI-Compatible APIs</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Quiet-Droid-111111?style=for-the-badge&logo=android&logoColor=A4C639" alt="Quiet Droid">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/API-OpenAI%20Compatible-black" alt="OpenAI Compatible API">
  <img src="https://img.shields.io/badge/UI-Terminal-green" alt="Terminal UI">
</p>

<p align="center">
  静かに動いて、必要なときだけ強く出るターミナル向けコーディングエージェント
</p>

単一ファイル版から分離し、`basic agent + skills loader` に絞った構成にしています。

## ✨ Features

- OpenAI互換APIの `/v1/chat/completions` を利用
  - ただし `model` が `glm-` で始まる場合は `/chat/completions` を利用
- 基本ツールのみ搭載
  - `Bash`
  - `Read`
  - `Write`
  - `Edit`
  - `Glob`
  - `Grep`
- エージェント補助ツール
  - `SubAgent`
  - `ParallelAgents`
- Skills の自動読込
- `AGENTS.md` / `CLAUDE.md` / `.quiet-droid.json` によるプロジェクト指示の自動読込
- 対話モードと one-shot モード
- セッション保存、履歴保存、権限確認の管理

## 🚀 Quick Start

`qd` コマンドで使う場合:

```bash
pipx install .
export OPENAI_BASE_URL="http://localhost:8000/v1"
export OPENAI_API_KEY="your-api-key"
qd
```

スクリプトを直接実行する場合:

```bash
export OPENAI_BASE_URL="http://localhost:8000/v1"
export OPENAI_API_KEY="your-api-key"
python3 quiet-droid.py
```

one-shot 実行:

```bash
python3 quiet-droid.py -p "pwd を実行して"
```

Debian / Ubuntu 系では PEP 668 により `pip install -e .` が失敗することがあります。その場合は `pipx install .` か、仮想環境を作って `pip install -e .` を使ってください。

## 📦 Installation

`pipx` を使う場合:

```bash
pipx install .
```

更新する場合:

```bash
pipx reinstall .
```

アンインストールする場合:

```bash
pipx uninstall quiet-droid
```

仮想環境を使う場合:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

仮想環境版を削除する場合:

```bash
deactivate  # 有効化している場合のみ
rm -rf .venv
```

インストール後は次のコマンドが使えます。

```bash
qd --help
quiet-droid --help
```

## 📋 Requirements

- Python 3.10+
- OpenAI互換APIサーバ
  - `/v1/models`
  - `/v1/chat/completions`

## ⚙️ Configuration

設定方法は3通りあります。

1. 環境変数
2. CLI引数
3. `~/.config/quiet-droid/config`

優先順位は `CLI引数 > configファイル > 環境変数 > デフォルト値` です。

初回起動時には設定ディレクトリと状態保存ディレクトリを自動作成します。

Linux / macOS:

- 設定ディレクトリ: `~/.config/quiet-droid`
- 権限設定: `~/.config/quiet-droid/permissions.json`
- 状態保存ディレクトリ: `~/.local/state/quiet-droid`
- セッション保存先: `~/.local/state/quiet-droid/sessions`
- 入力履歴: `~/.local/state/quiet-droid/history`

Windows:

- 設定ディレクトリ: `%LOCALAPPDATA%\quiet-droid`
- 設定ファイル: `%LOCALAPPDATA%\quiet-droid\config`
- 権限設定: `%LOCALAPPDATA%\quiet-droid\permissions.json`
- 状態保存ディレクトリ: `%LOCALAPPDATA%\quiet-droid`
- セッション保存先: `%LOCALAPPDATA%\quiet-droid\sessions`
- 入力履歴: `%LOCALAPPDATA%\quiet-droid\history`

`config` ファイル本体は自動生成しません。必要な場合だけ `~/.config/quiet-droid/config` を手動で作成してください。

### Environment Variables

```bash
export OPENAI_BASE_URL="http://localhost:8000/v1"
export OPENAI_API_KEY="your-api-key"
export QUIET_DROID_MODEL="gpt-4.1-mini"
export QUIET_DROID_DEBUG="1"
```

互換目的で `OLLAMA_HOST` も `OPENAI_BASE_URL` の代替として利用できます。

`z.ai` の `glm-*` モデルを使う場合は、`OPENAI_BASE_URL` に `/v1` ではなく API ルートを指定してください。

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
MAX_TOKENS=8192
TEMPERATURE=0.7
CONTEXT_WINDOW=32768
```

### CLI

```bash
python3 quiet-droid.py --base-url http://localhost:8000/v1 --api-key your-api-key --model gpt-4.1-mini
```

主な追加オプション:

```bash
python3 quiet-droid.py \
  --max-tokens 8192 \
  --temperature 0.7 \
  --context-window 32768 \
  --debug \
  --yes
```

## 💻 Usage

対話モード:

```bash
qd
```

one-shot:

```bash
qd -p "pwd を実行して"
```

ヘルプ:

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

通常入力では `exit` / `quit` / `bye` でも終了できます。
`Tab` で `/` コマンド補完ができます。`/` だけを入力して Enter するとコマンド一覧を表示します。
`Tab` で `$skill` 補完ができます。`$` だけを入力して Enter すると、ロード済み Skill 一覧を表示します。

## 🧩 Skills

以下のディレクトリにある `*.md` を自動で読み込みます。

- `~/.config/quiet-droid/skills/`
- `.quiet-droid/skills/`
- `./skills/`

Skills はシステムプロンプトへ注入されます。
対話中に `$plan` のように Skill 名を入力しやすいよう、ロード済み Skill 名は Tab 補完と一覧表示に使われます。

## 📜 Project Instructions

プロジェクト固有の指示ファイルとして、カレントディレクトリから親ディレクトリ方向へ以下を探索して自動読込します。

- `.quiet-droid.json`
- `CLAUDE.md`
- `AGENTS.md`

見つかったファイル内容はシステムプロンプトへ順に注入されます。`AGENTS.md` に運用ルールや出力言語、作業方針を書いておく運用に対応しています。
同一階層に複数あっても、各ディレクトリでは最初に見つかった1ファイルのみを採用します。

## 🪝 Hooks

最小実装として `command` 型フックをサポートしています。設定ファイルは次の順で読み込みます。

- `~/.config/quiet-droid/hooks.json`
- `./.quiet-droid/hooks.json`

Claude Code の公式ドキュメント:

- https://code.claude.com/docs/ja/hooks

Claude Code フック一覧と `quiet-droid` の対応状況:

| Event | Status | Notes |
| --- | --- | --- |
| `SessionStart` | Supported | 対応済み |
| `InstructionsLoaded` | Not supported | instruction 読み込み時イベントは未実装 |
| `UserPromptSubmit` | Supported | 対応済み |
| `PreToolUse` | Supported | `allow` / `ask` / `deny` をサポート |
| `PermissionRequest` | Supported | 既存 permission UI と連動 |
| `PostToolUse` | Supported | 成功時に発火 |
| `PostToolUseFailure` | Supported | エラー時に発火 |
| `PermissionDenied` | Supported | deny ルールや user deny で発火 |
| `Notification` | Not supported | 通知抽象が未実装 |
| `SubagentStart` | Supported | `SubAgent` 実行開始時 |
| `SubagentStop` | Supported | `SubAgent` 実行終了時 |
| `TaskCreated` | Not supported | 並列タスクはあるが専用イベントは未実装 |
| `TaskCompleted` | Not supported | 並列タスクはあるが専用イベントは未実装 |
| `Stop` | Supported | droid の最終応答で発火 |
| `StopFailure` | Not supported | API エラー終端イベントは未実装 |
| `TeammateIdle` | Not supported | team lifecycle 未実装 |
| `ConfigChange` | Not supported | 動的 reload 未実装 |
| `CwdChanged` | Not supported | persistent cwd モデル未実装 |
| `FileChanged` | Not supported | watcher 未実装 |
| `WorktreeCreate` | Not supported | worktree 機能未実装 |
| `WorktreeRemove` | Not supported | worktree 機能未実装 |
| `PreCompact` | Supported | compact 前に発火 |
| `PostCompact` | Supported | compact 後に発火 |
| `SessionEnd` | Supported | 対応済み |
| `Elicitation` | Not supported | MCP elicitation 未実装 |
| `ElicitationResult` | Not supported | MCP elicitation 未実装 |

実装済みのフックタイプ:

| Hook Type | Status | Notes |
| --- | --- | --- |
| `command` | Supported | 最小実装 |
| `http` | Not supported | 未実装 |
| `prompt` | Not supported | 未実装 |
| `agent` | Not supported | 未実装 |

最小例:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "type": "command",
        "matcher": "Bash",
        "command": "python3 .quiet-droid/hooks/block_rm.py"
      }
    ]
  }
}
```

フックにはイベント JSON が stdin で渡されます。`PreToolUse` では次のような JSON を stdout に返すと拒否できます。

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "blocked by local hook"
  }
}
```

`Stop` は「droid が最終応答を返してターンが完了したとき」に発火します。`command` 以外のフックタイプと、Claude Code の高度な lifecycle / watcher 系イベントはまだ未対応です。

## 📝 Config Example

最小構成の例:

```ini
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_API_KEY=your-api-key
MODEL=gpt-4.1-mini
```

## 🗂️ Project Structure

```text
quiet-droid.py
quiet_droid/
  __init__.py
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
    __init__.py
    agents.py
    base.py
    bash.py
    filesystem.py
    registry.py
```

## 📎 Notes

- `OPENAI_BASE_URL` は `/v1` 付きでも無しでも動くようにしています。
- `OPENAI_API_KEY` が必要なサーバでは設定してください。
- モデル未指定時は、`/v1/models` とマシンのRAM量を見て自動選択を試みます。
- `--yes` と `--dangerously-skip-permissions` は同じ意味で、ツール確認を自動承認します。
- 互換目的で `OLLAMA_HOST` と `--ollama-host` も受けますが、内部的には `base_url` として扱います。

## ✅ Verification

構文確認:

```bash
python3 -m py_compile quiet-droid.py quiet_droid/*.py quiet_droid/tools/*.py
python3 -m unittest discover -s tests -v
```
