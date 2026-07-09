# Goal — 長時間タスクのゴール管理

`quiet-droid` は `/goal` コマンドで「ゴール（長時間タスクの目的）」を設定し、エージェントが自律的にゴール達成まで動き続ける仕組みを提供します。Codex CLI の `/goal` 機能を、quiet-droid のアーキテクチャ（標準ライブラリのみ・同期ループ）に合わせて移植したものです。

設計の詳細は [goal-design_JP.md](goal-design_JP.md) を参照してください。

## できること

ゴールを設定すると、エージェントは**ゴールが完了・ブロック・一時停止されるまで自動的にターンを継続**します。

- **永続化**: ゴールは `~/.local/state/quiet-droid/goals.db`（SQLite）に `session_id` 単位で保存され、セッションをまたいで復元されます。
- **自動継続**: エージェントが「考えた」後にツールを呼ばなかった（＝1ターン終了）とき、ゴールがアクティブなら継続用プロンプトを注入して次のターンを自動開始します。
- **予算管理**: トークン予算を設定すると、消費量が予算に達した時点で自動停止します。
- **自己完了判定**: エージェントは `update_goal` ツールでゴールの完了・ブロックを自ら宣言できます。

## 使い方

```
/goal                       現在のゴールを表示
/goal <objective>           新しいゴールを設定（アクティブなゴールがあれば確認）
/goal clear                 ゴールを削除
/goal edit                  ゴールの目的を編集
/goal pause                 一時停止（自動継続を止める）
/goal resume                再開（自動継続を再開）
/goal budget <N>            トークン予算を設定（正の整数）
/goal budget clear          トークン予算を解除（無制限）
```

### 基本的な流れ

```
❯ /goal APIエンドポイントを3つ追加して、それぞれのテストを書く
  Goal set: active
  Objective: APIエンドポイントを3つ追加して、それぞれのテストを書く
  Tokens: 0/∞ · Time: 0s

  droid: （ツールを呼び出して作業を開始…）
  ▶ Goal continuation (turn 1)
  droid: （さらに作業を継続…）
  ▶ Goal continuation (turn 2)
  ...

❯ /goal
  ━━ Goal ━━━━━━━━━━━━━━━━━━━
  Status     active
  Objective  APIエンドポイントを3つ追加して、それぞれのテストを書く
  Tokens     4520/∞
  Time       3m 12s
  Commands: /goal pause · /goal edit · /goal clear
```

ゴールを設定するとすぐにエージェントが動き出します。途中で `/goal` を実行すると、現在のステータス・目的・消費トークン・経過時間を確認できます。

## ステータス

ゴールは6つのステータスを遷移します。

| Status | 意味 | 自動継続 | 遷移のきっかけ |
| --- | --- | --- | --- |
| `active` | ゴール追跡中 | ✅ する | `/goal <objective>`、`/goal resume` |
| `paused` | 一時停止 | ❌ しない | `/goal pause` |
| `complete` | 完了 | ❌ しない | エージェントが `update_goal(status=complete)` を宣言 |
| `blocked` | ブロック（行き詰まり） | ❌ しない | エージェントが `update_goal(status=blocked)` を宣言、またはターン内で致命的エラー発生 |
| `budget_limited` | 予算到達 | ❌ しない | トークン消費が `budget` に達した |
| `usage_limited` | （将来用） | ❌ しない | 現状では発生しません |

`active` のときだけ自動継続が働きます。それ以外は停止します。

## トークン予算

`/goal budget <N>` でトークン上限を設定できます。消費量が上限に達すると、ゴールは自動的に `budget_limited` になり、自動継続が止まります。

```
❯ /goal budget 10000
  Token budget set to 10000.

❯ /goal
  Status     active
  Tokens     10100/10000    ← 予算超過
```

予算到達時、エージェントは「**予算が尽きたからといって完了とはしない**」よう指示されており、現状を整理してユーザーに報告します。予算を増やす（`/goal budget 20000`）、一時停止する（`/goal pause`）、削除する（`/goal clear`）はユーザーの判断です。

## 安全機能

### ターン上限

予算を設定しない場合の無限ループを防ぐため、**1ゴールあたり最大20ターン**（`GoalRuntime.MAX_GOAL_TURNS`）のハードリミットがあります。上限に達すると自動継続が停止します。これは quiet-droid 固有の安全機能で、Codex にはありません。

### 完了判定の厳格化

エージェントは `update_goal` ツールで完了を宣言できますが、継続用プロンプトが**証拠ベースの完了監査**を厳しく要求します：

- 各要件ごとに具体的証拠（ファイルパス、コマンド出力、テスト成功）を示す
- 証拠が弱い場合は完了宣言せず作業を続ける
- **予算切れを理由に完了としない**
- `blocked` は「同じブロック条件が3回連続のゴールターンで再発した場合のみ」許可

### 割り込み

実行中に `Ctrl+C` を押すと現在のターンを中断します。ゴールは `active` のまま残るので、`/goal` で確認のうえ `/goal pause` や `/goal clear` で制御できます。

## ゴールの裏側（仕組み）

ユーザーが見える動作の背後で、次の3つの仕組みが連携しています。

### 1. システムプロンプトへの overlay 注入

ゴールが `active` の間、毎ターンのシステムプロンプト末尾にゴール概要が常時追加されます。エージェントは常に「いま何を目指しているか」を認識した状態で動きます。

### 2. 継続用 steering プロンプト

エージェントがテキスト応答で1ターンを終えたとき、ゴールが `active` なら継続用プロンプト（steering）が user メッセージとして注入され、次のターンが自動開始されます。steering には「次の具体的ステップを取れ」「完了監査のルール」が含まれます。

### 3. usage accounting

各ターン終了時に、消費トークンと経過時間が SQLite に加算されます。この値が `/goal` で表示される `Tokens` と `Time` です。

## セッションレジューム

`qd --resume` でセッションを復元すると、同じ `session_id` のゴールも自動復元されます。

- `active` なゴール → 復元メッセージを表示。ただし**自動では再開しない**ので、必要なら普通にプロンプトを送るか `/goal resume` で再開してください。
- `paused` なゴール → 再開を促すメッセージを表示。

## 設定

特別な設定は不要です。ゴールDBは `config.state_dir`（通常 `~/.local/state/quiet-droid/goals.db`）に自動作成されます。このパスは `Config.goal_db_path` で、`config.py` の `_refresh_paths` で決定されます。

ゴール機能は常に有効です（feature flag はありません）。

## 注意事項・制限

- **objective はプレーンテキストのみ**: 画像やペースト添付の materialize（Codex の `GoalDraft`／`attachments/`）は未サポートです。ファイル参照は既存の `@file` 展開を使ってください。
- **`usage_limited` は発生しない**: quiet-droid には API usage limit の概念がないため、このステータスは将来用の予約です。
- **イースターエッグなし**: Codex の `gooooooal` 変換は実装していません。
- **ゴールは1セッション1つ**: `session_id` が主キーのため、1セッションに複数ゴールは持てません（設定し直すと上書き）。

## 内部構造（開発者向け）

| ファイル | 役割 |
| --- | --- |
| `quiet_droid/goal_store.py` | SQLite 永続化・`Goal` モデル・CRUD・バリデーション |
| `quiet_droid/goal_controller.py` | `/goal` コマンドの引数解析と表示 |
| `quiet_droid/goal_steering.py` | steering プロンプト3種（continuation/objective_updated/budget_limit）＋ overlay |
| `quiet_droid/goal_runtime.py` | 自動継続・usage accounting・ステータス遷移の中枢 |
| `quiet_droid/tools/goal_tool.py` | モデル向け `update_goal` ツール（自己完了判定） |
| `tests/test_goal_*.py` | 上記各モジュールのテスト（計75件） |

データモデル・ステータス遷移・アーキテクチャ判断の根拠は [goal-design_JP.md](goal-design_JP.md) に詳述しています。
