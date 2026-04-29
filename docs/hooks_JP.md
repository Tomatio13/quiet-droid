# Hooks

`quiet-droid` は最小実装として `command` 型フックをサポートしています。

設定ファイルは次の順で読み込みます。

- `~/.config/quiet-droid/hooks.json`
- `./.quiet-droid/hooks.json`

Claude Code の公式ドキュメント:

- https://code.claude.com/docs/ja/hooks

## Event Support

Claude Code フック一覧と `quiet-droid` の対応状況です。

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

## Hook Types

実装済みのフックタイプです。

| Hook Type | Status | Notes |
| --- | --- | --- |
| `command` | Supported | 最小実装 |
| `http` | Not supported | 未実装 |
| `prompt` | Not supported | 未実装 |
| `agent` | Not supported | 未実装 |

## Minimal Example

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

フックにはイベント JSON が stdin で渡されます。

`PreToolUse` では次のような JSON を stdout に返すと拒否できます。

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "blocked by local hook"
  }
}
```

`PostToolUse` / `PostToolUseFailure` では、UI 表示と session 履歴へ入るツール出力本文を差し替えられます。

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "transformedOutput": "full raw output の代わりに使う短い要約"
  }
}
```

hook payload には `model` と `api_base_url` も含まれるため、プロジェクトローカル hook 側で「ローカル LLM のときだけ有効」にできます。

smart truncation hook の設計背景と内部仕様は [hook-smart-truncation-design_JP.md](hook-smart-truncation-design_JP.md) を参照してください。

`Stop` は「droid が最終応答を返してターンが完了したとき」に発火します。

`command` 以外のフックタイプと、Claude Code の高度な lifecycle / watcher 系イベントはまだ未対応です。
