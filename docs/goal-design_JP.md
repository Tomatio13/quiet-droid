# `/goal` 実装設計書（quiet-droid 版）

## Context

Codex の `/goal` は、長時間タスクの「ゴール」をスレッドに永続化し、**idle 時の自動ターン継続・steering プロンプト注入・予算管理・モデルによる自己完了判定**までを駆動する機能である。本設計は、quiet-droid に同等の機能を、**quiet-droid のアーキテクチャ（標準ライブラリのみ・同期ループ・JSONL セッション）に合わせて移植**する。

### Codex とのアーキテクチャ差と適用方針

| 側面 | Codex | quiet-droid での方針 |
|------|-------|----------------------|
| プロセスモデル | app-server（JSON-RPC）＋ TUI（別プロセス） | 単一プロセスの同期ループ。JSON-RPC 層は持たず、`/goal` ハンドラから直接ビジネスロジックを呼ぶ |
| 永続化 | SQLite（`thread_goals` テーブル） | **SQLite（標準ライブラリ `sqlite3`）を採用**。Codex 準拠のスキーマとする |
| スレッドID | `thread_id`（rollout 単位） | `session_id`（`Session.session_id`）をそのまま使用 |
| 自動継続 | app-server が idle を検知して新ターン起動 | 同期ループ内でターン終了後に「継続すべきか」を判定し、追加ターンを **同じ `agent.run` 呼び出し内のループで** 実行（新規ユーザー入力扱いではなく、steering プロンプトを user メッセージとして注入） |
| steering | `InternalContextSource` でコンテキストに注入 | システムプロンプト末尾にゴール概要を常時注入 ＋ 継続時に user メッセージで steering を注入 |
| 完了判定 | モデル向け関数ツール `update_goal` | **同名のツール `update_goal` を `ToolRegistry` に登録**。モデルが完了を宣言 |
| feature gate | Cargo feature `Goals` | 常に有効（ミニマル実装のため）。設定で無効化は Phase 以降で検討 |

### 対象外（本設計では扱わない）

- **画像/ペースト添付の materialize**（Codex の `GoalDraft`／`attachments/<uuid>/`）：objective はプレーンテキストのみとする。`@file` 展開は既存の `inject_file_context` に任せる。
- **rollout（JSONL ログ）へのゴールイベント追記**：quiet-droid の JSONL はメッセージ履歴のみ。ゴール状態は SQLite が単一ソース。
- ** ephemeral スレッド制限**：quiet-droid は常にセッションを持つため不要。
- **イースターエッグ**（`gooooooal`）：実装しない。

---

## 概要

```
/goal                     # 現在のゴールサマリを表示
/goal <objective>         # 新規ゴール設定（既存アクティブなら確認）
/goal clear               # ゴール削除
/goal edit                # objective を編集（編集プロンプトを開く）
/goal pause               # Active -> Paused
/goal resume              # Paused -> Active
/goal budget <N>          # トークン予算を設定（省略時は無制限）
```

ゴールは `session_id` を主キーに SQLite へ永続化され、以下を駆動する：

1. **steering 注入** — ゴールが Active の間、システムプロンプトに概要を常時表示し、継続ターンで追加 steering を user メッセージとして注入。
2. **自動継続** — エージェントループ終了時にゴールが Active ＆ Complete でなければ、steering プロンプトで次ターンを起動。
3. **予算管理** — ターンごとに `tokens_used` / `time_used_seconds` を加算。`token_budget` 超過で `BudgetLimited` へ自動遷移し追跡停止。
4. **自己完了判定** — モデルが `update_goal` ツールで `complete` / `blocked` を宣言。完了時は最終消費報告を促す。

---

## Phase 1: データモデルと永続化層

### 新規ファイル `quiet_droid/goal_store.py`

SQLite アクセスをカプセル化する。Codex のスキーマ（`state/goals_migrations/0001_thread_goals.sql`）に準拠：

```python
import os
import sqlite3
import time
import uuid

GOAL_STATUSES = ("active", "paused", "blocked", "usage_limited", "budget_limited", "complete")
MAX_OBJECTIVE_CHARS = 4000

SCHEMA = """
CREATE TABLE IF NOT EXISTS thread_goals (
    session_id      TEXT PRIMARY KEY NOT NULL,
    goal_id         TEXT NOT NULL,
    objective       TEXT NOT NULL,
    status          TEXT NOT NULL CHECK(status IN ('active','paused','blocked','usage_limited','budget_limited','complete')),
    token_budget    INTEGER,
    tokens_used     INTEGER NOT NULL DEFAULT 0,
    time_used_seconds INTEGER NOT NULL DEFAULT 0,
    created_at_ms   INTEGER NOT NULL,
    updated_at_ms   INTEGER NOT NULL
);
"""

class Goal:
    """ゴールの不変スナップショット（DB 行の Python 表現）。"""
    __slots__ = ("session_id", "goal_id", "objective", "status",
                 "token_budget", "tokens_used", "time_used_seconds",
                 "created_at_ms", "updated_at_ms")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def is_active(self):
        return self.status == "active"

    def is_terminal(self):
        return self.status in ("complete", "blocked", "usage_limited", "budget_limited")

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}
```

`sqlite3` 接続は関数スコープで開いて都度閉じる（スレッド安全性と simplicity の両立）。DB パスは `config.state_dir/goals.db`。

主なメソッド（戻り値は `Goal` または `None`）：

- `get_goal(session_id) -> Goal | None`
- `replace_goal(session_id, objective, token_budget=None) -> Goal` — 新規作成または置換。`goal_id` を `uuid.uuid4().hex`、`status="active"`、`created_at_ms=updated_at_ms=now`。
- `update_status(session_id, status) -> Goal | None` — `updated_at_ms` 更新。
- `update_objective(session_id, objective) -> Goal | None`
- `update_budget(session_id, token_budget) -> Goal | None`
- `account_usage(session_id, tokens_delta, seconds_delta) -> Goal | None` — `tokens_used`/`time_used_seconds` 加算。
- `delete_goal(session_id) -> bool`
- `validate_objective(text) -> str` — 空不可・`MAX_OBJECTIVE_CHARS` 以下。違反時 `ValueError`。

バリデーションは Codex の `validate_thread_goal_objective`（`protocol/src/protocol.rs:3983`）相当。

### `quiet_droid/config.py`

- `Config.__init__`／`_refresh_paths`（`config.py:59-63`）に `self.goal_db_path = os.path.join(self.state_dir, "goals.db")` を追加。
- `_ensure_dirs` で `config_dir`/`state_dir` は既に作成済みなので、DB ファイル自体は `goal_store.py` 初期化時に作成（`CREATE TABLE IF NOT EXISTS`）。

### テスト `tests/test_goal_store.py`

`tempfile.TemporaryDirectory()` で DB を分離し、`replace_goal` → `get_goal` → `update_status` → `account_usage` → `delete_goal` の CRUD と、objective バリデーション（空・4001文字）を検証。

---

## Phase 2: スラッシュコマンド `/goal`（UI/ディスパッチ）

### `quiet_droid/tui.py`

`SLASH_COMMAND_SPECS`（`tui.py:21-37`）に1行追加：

```python
("/goal", "Set or view the goal for a long-running task"),
```

`/help` 表示と Tab 補完に自動的に反映される（`SLASH_COMMANDS` は派生リスト）。

### `quiet_droid/app.py` — ディスパッチ拡張

`app.py:155-216` の if 文チェインに `/goal` ブロックを追加。実行ロジックは後述の `GoalController` に委譲し、`app.py` は引数解析とハンドラ呼び出しのみを行う（既存コマンドが `session.compact_if_needed()` 等を直接呼ぶ慣行に合わせつつ、ゴールは状態が多いため controller に集約）。

```python
if cmd == "/goal":
    goal_controller.handle_slash(user_input)
    continue
```

`GoalController` は main ループの初期化部（`app.py:68-77` 付近）で生成し、`session` と `config` と `tui` を注入する。

### 新規ファイル `quiet_droid/goal_controller.py`

スラッシュコマンドの引数解析と表示を担う。コア API：

```python
class GoalController:
    def __init__(self, config, tui):
        self.config = config
        self.tui = tui

    def handle_slash(self, user_input: str) -> None:
        parts = user_input.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if arg == "":
            self._show_summary()
        elif arg == "clear":
            self._clear()
        elif arg == "edit":
            self._edit()
        elif arg == "pause":
            self._set_status("paused")
        elif arg == "resume":
            self._set_status("active")
        elif arg.startswith("budget"):
            self._set_budget(arg)
        else:
            # /goal <objective>: objective 全体を本文とみなす
            self._set_objective(arg)
```

各サブコマンドの挙動：

- **`_show_summary`**: `GoalStore.get_goal(session_id)`。存在すれば Status / Objective（折返し表示）/ Time used / Tokens used / Token budget と、状態に応じたコマンドヒント（`/goal pause`、`/goal resume`、`/goal clear`、`/goal edit`）を表示。未設定なら usage ヒント。Codex `goal_menu.rs:85 goal_summary_lines` 相当。
- **`_set_objective(objective)`**: `validate_objective` → 既存ゴールが `active` なら確認プロンプト（`tui.ask_permission` 相当の yes/no）→ `replace_goal`。設定成功メッセージ（`Goal active` + usage サマリ）を表示。
- **`_clear`**: `delete_goal`。`Goal cleared` または `No goal to clear`。
- **`_edit`**: 既存 objective を `tui.get_multiline_input` のプリフィルドで開き（readline の `prefill_hook` 使用）、確定したら `update_objective`。objective 変更時は後述の `objective_updated` steering を次ターンへ（Phase 4）。
- **`_set_status`**: `update_status`。`Paused`/`Active` 切替メッセージ。
- **`_set_budget`**: `update_budget`。引数は正の整数のみ（Codex `validate_goal_budget` 相当）。

### テスト `tests/test_goal_controller.py`

`DummyConfig`/`DummyTUI` で各サブコマンドの引数解析と分岐を検証。`/goal`、`/goal foo`、`/goal clear`、`/goal pause`、`/goal budget 1000`、`/goal budget -5`（エラー）。

---

## Phase 3: システムプロンプトへのゴール概要注入

### `quiet_droid/prompts.py`

ゴールは `Session` 生成後に変わり得るため、`build_system_prompt`（起動時1回）ではなく、**毎ターン組み立てられるメッセージリスト**に注入する。`Session.get_messages()`（`session.py:212-216`）が毎ターン呼ばれるので、ここでゴール概要をシステムプロンプト末尾に追記する。

```python
def get_messages(self):
    msgs = [{k: v for k, v in m.items() if k != "_timestamp"} for m in self.messages]
    system = self.system_prompt
    if self._goal_overlay:           # GoalRuntime が設定した文字列
        system += "\n\n" + self._goal_overlay
    return [{"role": "system", "content": system}] + msgs
```

`_goal_overlay` は `GoalRuntime`（Phase 5）が Active ゴールの概要文字列をセットする。形式：

```
# Active Goal
Objective: <objective>
Status: active | Tokens: <used>/<budget or ∞> | Time: <mm:ss>
Pursue this goal. Use the update_goal tool to mark it complete (with evidence)
or blocked (only if the same blocker recurred across 3 goal turns).
```

**設計上の注意点**: 既存の `Session.get_token_estimate()`（`session.py:218-219`）は `self.system_prompt` のみを足している。overlay 分もトークン推定に含めるよう `_goal_overlay` の estimate を加算する（microcompact/compact の閾値判定に影響するため）。

---

## Phase 4: steering プロンプト

### 新規ファイル `quiet_droid/goal_steering.py`

3種のテンプレートを関数で返す（Codex `ext/goal/templates/goals/*.md` 相当）。内容は Codex のものを quiet-droid 向けに簡素化して翻訳：

- **`continuation(goal)`**: idle 継続時に user メッセージとして注入。ゴール全体像を保ちつつ次の具体的進捗を作る指示、完了監査（要件ごとに証拠で証明、証拠が弱ければ完了とみなさない、予算切れで完了とするな）、blocked 監査（同じブロック条件が3回連続のゴールターンで再発した場合のみ）を含む。
- **`objective_updated(goal)`**: `/goal edit` で objective 変更時に、進行中の次ターンへ注入。「objective が更新された。新objective を優先せよ」。
- **`budget_limit(goal)`**: 予算超過時に注入。「予算到達。これ以上の自動継続は停止する。現状を整理して報告せよ」。

各テンプレートは `str` を返す純関数とし、テストで内容を assert する。

---

## Phase 5: `GoalRuntime` — 自動継続と accounting の中核

### 新規ファイル `quiet_droid/goal_runtime.py`

`Agent` に組み込まれ、ターン境界で呼ばれる。Codex `GoalRuntimeHandle`（`ext/goal/src/runtime.rs:24`）相当だが、同期ループ向けに単純化する。

```python
class GoalRuntime:
    def __init__(self, config, store, steering):
        self.config = config
        self.store = store
        self.steering = steering
        self._turn_start_tokens = 0
        self._turn_start_time = 0.0
        self._goal_turn_count = 0

    def has_active_goal(self, session_id) -> bool: ...

    def begin_turn(self, session_id) -> None:
        """ターン開始時: 開始トークン/時刻を記録、ゴール概要を overlay に反映。"""

    def end_turn(self, session_id, session, agent) -> str | None:
        """
        ターン終了時:
        1. usage 加算（tokens_used/time_used）
        2. 予算超過チェック -> BudgetLimited 遷移 + budget_limit steering
        3. Active 継続判定 -> continuation steering を返す（呼び出し元が次ターン起動）
        戻り値: 次ターンへ注入する steering テキスト。None で継続不要。
        """
```

### `quiet_droid/agent.py` への組み込み

`Agent.__init__`（`agent.py:20-39`）に `goal_runtime` 引数を追加（デフォルト `None` で後方互換）。`Agent.run`（`agent.py:124`）を以下のように拡張：

1. **ターン開始**（`agent.py:158` ループ入口付近）: `goal_runtime.begin_turn` 呼び出し。
2. **ターン終了時の継続判定**: 現在の `agent.run` は tool_calls が無ければループ脱出（`agent.py:223-232`）。この脱出後に、`goal_runtime.end_turn` を呼び、steering が返れば **`session.add_user_message(steering)` してループを継続**（`iteration` を進めずに、新しい user メッセージとして扱う）。実装上は `agent.run` の内部ループを「ユーザー起点のターン」と「ゴール継続ターン」の2層にするか、`MAX_ITERATIONS` の枠内で継続メッセージを注入する。

**自動継続の安全弁**:
- `_goal_turn_count` に上限を設ける（例: Codex には無いが quiet-droid では `MAX_GOAL_TURNS = 20` 程度を新設）。超過時は強制停止＋ユーザーへ報告。
- `_interrupted`（`agent.py:159`）がセットされていれば継続しない。
- `Paused` のゴールは継続しない。
- 予算超過（`BudgetLimited`）時は継続しない。

3. **usage accounting**: 各ターンで `session._token_estimate` の差分と `time.time()` 経過秒を `store.account_usage` で加算。`response.usage`（`agent.py:206-211`）が取れる場合はそちらを優先（より正確）。

### ステータス自動遷移（Codex 準拠）

- ターン内の致命的エラー（`agent.py:465-472` の `except Exception`）→ `Blocked`（reason `TurnError`）。
- usage limit 到達 — quiet-droid には明示的な usage limit が無いため、**本 Phase では `UsageLimited` は発生させない**（`token_budget` による `BudgetLimited` のみ実装）。`UsageLimited` は将来フェーズ。

---

## Phase 6: モデル向けツール `update_goal`

### 新規ファイル `quiet_droid/tools/goal_tool.py`

Codex `ext/goal/src/tool.rs` の `update_goal` 相当。`create_goal`/`get_goal` も理論上はあるが、quiet-droid では `/goal` スラッシュコマンドが作成を担うため、**まず `update_goal` のみ実装**（完了判定が本機能の要）。`create_goal`/`get_goal` は将来追加。

```python
class UpdateGoalTool(Tool):
    name = "update_goal"
    description = (
        "Mark the active goal as complete or blocked. "
        "Use ONLY when the goal is truly done (with evidence) or blocked "
        "(same blocker recurred across 3 goal turns)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["complete", "blocked"],
                "description": "complete = goal achieved; blocked = unrecoverable blocker",
            },
            "summary": {
                "type": "string",
                "description": "Evidence-based justification for the status change.",
            },
        },
        "required": ["status", "summary"],
    }

    def execute(self, params):
        status = params.get("status")
        if status not in ("complete", "blocked"):
            return "Error: status must be 'complete' or 'blocked'."
        # controller/runtime 経由で store.update_status + 完了時の精算
        ...
```

`status` は `complete`/`blocked` のみ許可（Codex `tool.rs:226-234`）。完了時は `account_active_goal_progress` 相当の最終使用量精算を行い、**完了報告指示**（「ユーザーに最終消費トークンを報告せよ」）をツール結果としてモデルへ返す（Codex `tool.rs:424-428` 相当）。これにより自動継続が停止し、モデルが最終サマリを生成する。

### `quiet_droid/app.py` / `tools/registry.py` への登録

`app.py:72-77` のレジストリ組み立て部で `registry.register(UpdateGoalTool(...))` を追加。`PermissionMgr.SAFE_TOOLS`（`registry.py:37`）に `"update_goal"` を追加（ゴール状態変更は安全＝副作用が DB のみでファイルシステム/コマンド実行を伴わないため）。

### テスト `tests/test_goal_tool.py`

`complete`/`blocked` の正常系と、不正 status のエラー系を検証。完了時に store の status が `complete` になり、精算が走ることを確認。

---

## Phase 7: セッションレジューム時の復元

### `quiet_droid/app.py` のレジューム部（`app.py:94-113`）

`session.load` 後に `goal_runtime.restore_after_resume(session_id)` を呼ぶ。これは：

1. `store.get_goal(session_id)` でゴール取得。
2. 存在すれば overlay へ反映（次回 `get_messages` から概要表示）。
3. `Paused` の場合、resume プロンプトを表示（Codex `goal_menu.rs:39` 相当）：「一時停止中のゴールがあります。`/goal resume` で再開」。

ゴールは SQLite に `session_id` 主キーで永続されているため、**JSONL には何も書き込まない**。レジュームは session_id の一致だけで復元される。

---

## 影響範囲とファイル一覧

### 新規ファイル
| ファイル | 役割 |
|---------|------|
| `quiet_droid/goal_store.py` | SQLite 永続化・`Goal` モデル |
| `quiet_droid/goal_controller.py` | `/goal` スラッシュコマンド処理・表示 |
| `quiet_droid/goal_steering.py` | steering プロンプト3種 |
| `quiet_droid/goal_runtime.py` | 自動継続・accounting・ステータス遷移 |
| `quiet_droid/tools/goal_tool.py` | `update_goal` ツール |
| `tests/test_goal_store.py` | 永続化層テスト |
| `tests/test_goal_controller.py` | コマンド処理テスト |
| `tests/test_goal_steering.py` | steering テンプレートテスト |
| `tests/test_goal_runtime.py` | 継続/accounting テスト |
| `tests/test_goal_tool.py` | ツールテスト |

### 既存ファイル変更
| ファイル | 変更点 |
|---------|--------|
| `quiet_droid/tui.py`（`:21-37`） | `SLASH_COMMAND_SPECS` に `/goal` 追加 |
| `quiet_droid/config.py`（`:59-63`） | `goal_db_path` 追加 |
| `quiet_droid/session.py`（`:212-219`） | `get_messages` で `_goal_overlay` 注入、`get_token_estimate` に overlay 分を加算 |
| `quiet_droid/agent.py`（`:20-39`, `:124-232`） | `goal_runtime` 注入、`begin_turn`/`end_turn`、自動継続ループ |
| `quiet_droid/app.py`（`:68-77`, `:155-216`） | `GoalController`/`GoalRuntime` 生成、`/goal` ディスパッチ、レジューム復元 |
| `quiet_droid/prompts.py` | `update_goal` ツールの存在を CORE RULES に追記（任意・Phase 6 で） |
| `quiet_droid/tools/registry.py`（`:37`） | `SAFE_TOOLS` に `update_goal` 追加 |

---

## 実装順序（推奨）

Phase 間に依存があるため、下から順に積み上げる。各 Phase 完了時にテストを緑にしてから次へ：

1. **Phase 1**（store）— 他の全 Phase の基盤。DB が動くことを先に確定。
2. **Phase 2**（controller/コマンド）— この時点では「設定/表示/clear」のみ動く。手動でゴールを set して確認可能。
3. **Phase 3**（overlay 注入）— set したゴールがシステムプロンプトに載ることを確認。
4. **Phase 4**（steering）— テンプレートのみ。まだ注入しない。
5. **Phase 5**（runtime/継続/accounting）— Phase 3-4 を繋ぐ。ここで自動継続が動く。
6. **Phase 6**（update_goal ツール）— モデルが完了を宣言できるようになる。
7. **Phase 7**（レジューム復元）— セッション跨ぎの確認。

---

## 主要な設計判断と根拠

1. **JSON-RPC 層を持たない**: quiet-droid は単一プロセスの同期アプリ。Codex の app-server/TUI 分離に相当する境界が無く、controller → store の直接呼び出しで十分。レイヤーを増やさないことが quiet-droid の哲学（標準ライブラリのみ・ミニマル）。

2. **自動継続を `agent.run` 内のループで実現**: Codex は app-server が独立して idle を検知して新ターンを起動できるが、quiet-droid には常駐プロセスが無い。`agent.run` のターン終了後に継続判定 → steering user メッセージ注入 → ループ継続、が唯一の自然な実装。

3. **steering を user メッセージで注入**: Codex は `InternalContextSource` でコンテキスト層に注入するが、OpenAI 互換 API ではシステムプロンプトは静的（毎回同一）。代わりに user ロールで steering を送ることで、モデルに「新しい指示」として認識させる。概要は常時システムプロンプト（Phase 3 overlay）、行動喚起は user メッセージ（Phase 4 steering）と役割を分ける。

4. **`update_goal` を SAFE_TOOLS に**: 状態変更の副作用が SQLite のみで、ファイルシステム破壊やコマンド実行を伴わないため、ユーザー確認不要とする。これにより自動継続中の完了宣言が権限プロンプトで阻塞されない。

5. **`MAX_GOAL_TURNS` 安全弁の新設**: Codex は token_budget で停止するが、budget 未設定時の無限ループを防ぐため、quiet-droid では明示的なターン上限を設ける。これは Codex には無い quiet-droid 固有の安全機能。

---

## 未解決事項（実装開始前に要確認）

- **`_edit` のプリフィルド実装**: readline の `preedit_hook`/`set_startup_hook` で既存 objective を入力欄に前置できるか、`HAS_READLINE` 環境でのみ動作。不可なら「現在の objective を表示 → 新入力を促す」フォールバック。
- **`/goal edit` の objective 変更検出**: 同一文字列なら `objective_updated` steering をスキップすべきか。
- **ゴール削除時の overlay クリア**: `/goal clear` 後に `_goal_overlay` を即座に空にする（次回 `get_messages` に残らないよう）。

---

## 参照（Codex 側）

- コマンド enum: `codex-rs/tui/src/slash_command.rs:42`
- TUI ディスパッチ: `codex-rs/tui/src/chatwidget/slash_dispatch.rs:282-296, 745-850`
- ビジネスロジック: `codex-rs/ext/goal/src/api.rs`（`GoalService`）
- ランタイム/継続: `codex-rs/ext/goal/src/runtime.rs:24`（`GoalRuntimeHandle`）
- steering: `codex-rs/ext/goal/src/steering.rs:49-54`、`templates/goals/*.md`
- 完了判定ツール: `codex-rs/ext/goal/src/tool.rs`（`update_goal`）
- 永続化: `codex-rs/state/src/runtime/goals.rs`、`state/goals_migrations/0001_thread_goals.sql`
- スキーマ定義: `codex-rs/state/src/model/thread_goal.rs:12-21`（`ThreadGoalStatus`）
