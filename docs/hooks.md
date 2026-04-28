# Hooks

`quiet-droid` supports `command` hooks as a minimal hook implementation.

Hook config files are loaded in this order:

- `~/.config/quiet-droid/hooks.json`
- `./.quiet-droid/hooks.json`

Claude Code official documentation:

- https://code.claude.com/docs/ja/hooks

## Event Support

This table shows Claude Code hook events and the current `quiet-droid` support status.

| Event | Status | Notes |
| --- | --- | --- |
| `SessionStart` | Supported | Implemented |
| `InstructionsLoaded` | Not supported | Instruction-load event is not implemented |
| `UserPromptSubmit` | Supported | Implemented |
| `PreToolUse` | Supported | Supports `allow`, `ask`, and `deny` |
| `PermissionRequest` | Supported | Integrated with the existing permission UI |
| `PostToolUse` | Supported | Fires after successful tool use |
| `PostToolUseFailure` | Supported | Fires after tool errors |
| `PermissionDenied` | Supported | Fires for deny rules and user denial |
| `Notification` | Not supported | Notification abstraction is not implemented |
| `SubagentStart` | Supported | Fires when `SubAgent` starts |
| `SubagentStop` | Supported | Fires when `SubAgent` finishes |
| `TaskCreated` | Not supported | Parallel tasks exist, but no dedicated event is implemented |
| `TaskCompleted` | Not supported | Parallel tasks exist, but no dedicated event is implemented |
| `Stop` | Supported | Fires when the droid returns its final response |
| `StopFailure` | Not supported | API error termination event is not implemented |
| `TeammateIdle` | Not supported | Team lifecycle is not implemented |
| `ConfigChange` | Not supported | Dynamic reload is not implemented |
| `CwdChanged` | Not supported | Persistent current-working-directory model is not implemented |
| `FileChanged` | Not supported | File watcher is not implemented |
| `WorktreeCreate` | Not supported | Worktree support is not implemented |
| `WorktreeRemove` | Not supported | Worktree support is not implemented |
| `PreCompact` | Supported | Fires before compaction |
| `PostCompact` | Supported | Fires after compaction |
| `SessionEnd` | Supported | Implemented |
| `Elicitation` | Not supported | MCP elicitation is not implemented |
| `ElicitationResult` | Not supported | MCP elicitation is not implemented |

## Hook Types

These hook types are implemented.

| Hook Type | Status | Notes |
| --- | --- | --- |
| `command` | Supported | Minimal implementation |
| `http` | Not supported | Not implemented |
| `prompt` | Not supported | Not implemented |
| `agent` | Not supported | Not implemented |

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

Hooks receive event JSON through stdin.

`PreToolUse` can reject a tool call by returning JSON like this through stdout.

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "blocked by local hook"
  }
}
```

`Stop` fires when the droid returns its final response and the turn completes.

Hook types other than `command`, and advanced Claude Code lifecycle / watcher events, are not supported yet.
