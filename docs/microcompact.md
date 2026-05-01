# Microcompact 実装計画

## Context

Quiet Droid の会話はツール呼び出し結果（ファイル内容、コマンド出力等）によりコンテキストウィンドウを急速に消費する。現在の autocompact（会話全体の LLM 要約）は高コストで、コンテキストの大部分は古いツール結果が占めている。`microcompact-design.md` に記載の **Time-based Microcompact** を実装し、アイドル時間経過後に古いツール結果をプレースホルダーで置換することで、autocompact を遅延・回避する。

**対象外**: Cache-editing Microcompact と API-native context management は Anthropic 固有機能であり、OpenAI 互換 API を使用する Quiet Droid では適用不可。

---

## Phase 1: 基盤 — タイムスタンプ追跡（影響なし）

### `quiet_droid/session.py`

1. **定数追加** (インポート後、class 定義前):
   ```python
   COMPACTABLE_TOOLS = frozenset({
       "Read", "Bash", "Grep", "Glob", "Write", "Edit",
       "SubAgent", "ParallelAgents",
   })
   MICROCOMPACT_CLEARED = "[Old tool result content cleared]"
   ```

2. **`add_droid_message()`** (L126-133): `_timestamp` キーを追加
   ```python
   msg["_timestamp"] = time.time()
   ```

3. **`get_messages()`** (L172-173): API 送信前に `_timestamp` を除去
   ```python
   def get_messages(self):
       msgs = [{k: v for k, v in m.items() if k != "_timestamp"} for m in self.messages]
       return [{"role": "system", "content": self.system_prompt}] + msgs
   ```

### `quiet_droid/config.py`

4. **`Config.__init__()`** (L25-33 付近): デフォルト値追加
   ```python
   self.microcompact_gap_minutes = 60   # 0 で無効化
   self.microcompact_keep_recent = 5
   ```

5. **`_load_config_file()`** (L93-97 の後): 設定ファイルパース追加
   ```python
   elif key == "MICROCOMPACT_GAP_MINUTES" and val:
       try: self.microcompact_gap_minutes = int(val)
       except ValueError: pass
   elif key == "MICROCOMPACT_KEEP_RECENT" and val:
       try: self.microcompact_keep_recent = int(val)
       except ValueError: pass
   ```

6. **`_load_cli_args()`** (L143 の後): CLI 引数追加
   ```python
   parser.add_argument("--microcompact-gap", type=int, help="Idle minutes before clearing old tool results (0=disabled)")
   parser.add_argument("--microcompact-keep", type=int, help="Recent tool results to keep (default=5)")
   ```
   L178 の後で args から反映。

**影響範囲**: 3ファイル、6箇所の変更。動作への影響はゼロ（タイムスタンプを記録するのみ）。

---

## Phase 2: Time-based Microcompact ロジック

### `quiet_droid/session.py`

7. **新メソッド `microcompact_if_needed()`** (L294 の `compact_if_needed()` の後):
   - 最後の assistant メッセージの `_timestamp` から経過時間を計算
   - `gap_threshold` (デフォルト60分) 未満なら return False
   - 全メッセージから compactable ツールの call ID を時系列順に収集
   - `keep_recent` 個（最低1）を保持し、残りをクリア対象に
   - 対象の `role: "tool"` メッセージの content を `MICROCOMPACT_CLEARED` に置換
   - トークン推定値を減算（負になったら `_recalculate_tokens()` で再計算）
   - `PostMicrocompact` フックを発火
   - 全体を try/except でラップ（ベストエフォート）

   ```python
   def microcompact_if_needed(self):
       try:
           gap = getattr(self.config, "microcompact_gap_minutes", 60)
           keep = max(1, getattr(self.config, "microcompact_keep_recent", 5))
           if gap <= 0: return False
           # ... (上記ロジック)
       except Exception:
           return False
   ```

**影響範囲**: 1ファイル、1メソッド追加。まだエージェントループから呼ばれないため動作変更なし。

---

## Phase 3: エージェントループ統合

### `quiet_droid/agent.py`

8. **L292 の autocompact 前に microcompact を挿入**:
   ```python
   # Microcompact: try cheap clearing first
   self.session.microcompact_if_needed()
   # Autocompact: full summarization if still needed
   before = self.session.get_token_estimate()
   self.session.compact_if_needed()
   ```

9. **`_ensure_context_window_before_send()` (L47-53)**: 強制パスでも microcompact を先に試行:
   ```python
   def _ensure_context_window_before_send(self):
       status = self.session.context_window_status()
       if status["ok"]: return True
       self.session.microcompact_if_needed()  # 追加
       status = self.session.context_window_status()
       if status["ok"]: return True
       # ... 既存の force compact 継続
   ```

**影響範囲**: 1ファイル、2箇所の挿入。これで機能が有効化される。

---

## Phase 4: テスト

### `tests/test_session.py`

10. **新テストクラス追加**（既存の `DummyConfig` に属性追加）:
    - `test_no_action_when_recent` — 60分未満のギャップでは何もしない
    - `test_clears_old_tool_results` — 60分以上のギャップで古い結果をクリア
    - `test_preserves_recent_n` — 直近 N 個の結果は保持
    - `test_preserves_non_compactable` — AskUserQuestion の結果は保持
    - `test_no_timestamp_is_noop` — レガシーセッションでタイムスタンプな場合は何もしない
    - `test_idempotent` — 2回実行しても同じ結果
    - `test_disabled_with_zero_gap` — gap=0 で無効化
    - `test_token_estimate_updated` — トークン推定値が減少
    - `test_timestamp_survives_save_load` — 保存/読み込みでタイムスタンプ保持
    - `test_timestamp_stripped_from_api_messages` — `get_messages()` に `_timestamp` を含まない

---

## 設定方法

| 手段 | キー | 例 |
|------|------|----|
| 設定ファイル | `MICROCOMPACT_GAP_MINUTES=60` | `~/.config/quiet-droid/config` |
| 設定ファイル | `MICROCOMPACT_KEEP_RECENT=5` | 同上 |
| CLI | `--microcompact-gap 60` | `quiet-droid --microcompact-gap 30` |
| CLI | `--microcompact-keep 5` | `quiet-droid --microcompact-keep 3` |
| 無効化 | gap=0 | `MICROCOMPACT_GAP_MINUTES=0` |

---

## 変更ファイル一覧

| ファイル | 変更内容 |
|----------|----------|
| `quiet_droid/session.py` | 定数追加、`_timestamp` 追跡、`microcompact_if_needed()` 追加 |
| `quiet_droid/agent.py` | 2箇所の統合ポイント（L292, L47） |
| `quiet_droid/config.py` | 設定属性、ファイルパース、CLI引数 |
| `tests/test_session.py` | 10件のユニットテスト追加 |

---

## 検証方法

1. `python -m unittest discover tests` — 全テスト通過確認
2. 手動テスト: `quiet-droid` を起動し、ツール呼び出し後に `_timestamp` がセッションファイルに保存されることを確認
3. 手動テスト: `--microcompact-gap 0` で無効化されることを確認
4. 手動テスト: セッションファイルを直接編集して古いタイムスタンプを設定し、microcompact が発動することを確認
