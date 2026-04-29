# Smart Truncation Hook 機能設計書

## 1. 目的

この機能は、ローカルLLM利用時に長大なツール出力をそのまま会話コンテキストへ流し込まず、重要行を保全した短い要約へ置き換えるためのものです。

主な狙いは次の3点です。

- 末尾に出やすいエラーや終了コードを失いにくくする
- コンテキスト消費を抑えて、後続ターンの品質低下を防ぐ
- 本体実装へ常時組み込まず、利用者が明示的に有効化できるようにする

## 2. 背景

従来の `quiet-droid` には複数の切り詰め処理がありましたが、文字数ベースの単純切断が中心でした。

- `Bash` は head/tail の単純保存
- `Session` は文字数超過時の切断
- サブエージェント結果も順序ベースで圧縮

この方式では、次のような問題が起きます。

- 末尾の `Error:` `Traceback` `(exit code: N)` が落ちる
- diff やビルドログの重要行がノイズに埋もれる
- ローカルLLMの小さめのコンテキストを過剰に消費する

## 3. 設計方針

この機能は「本体の汎用フック機構」と「任意導入の外部hook」の組み合わせとして設計しています。

- 本体側は `PostToolUse` / `PostToolUseFailure` の戻り値で本文差し替えを許可する
- smart truncation のロジック自体は hook スクリプト側へ置く
- hook は `install-hooks` コマンドで明示的に導入する
- ローカルLLMと判定できる場合にだけ動作させる

この方針により、remote API 利用者へ挙動を押し付けずに済みます。

## 4. 対象範囲

対象:

- `Bash`
- `SubAgent`
- `ParallelAgents`
- `PostToolUse`
- `PostToolUseFailure`

対象外:

- `PreToolUse` の許可判定そのもの
- `Read` `Write` `Grep` など個別ツールの専用構造要約
- モデル呼び出しによるLLM要約
- 外部ストレージの索引化や後読みAPI

## 5. 構成

### 5.1 本体側

- `quiet_droid/hooks.py`
  - hook payload へ `model` と `api_base_url` を追加
  - `transform_tool_response()` を追加
- `quiet_droid/agent.py`
  - hook が返した `transformedOutput` を UI 表示と session 保存へ反映
- `quiet_droid/config.py`
  - `install-hooks`
  - `install-hooks --force`
- `quiet_droid/app.py`
  - installer の実行入口

### 5.2 hook実装側

- `quiet_droid/smart_truncate_hook.py`
  - 要約ロジック本体
- `quiet_droid/hook_installer.py`
  - グローバル設定ディレクトリへの配置処理
- `~/.config/quiet-droid/hooks.json`
  - 利用者環境に書き出される hook 設定
- `~/.config/quiet-droid/hooks/smart_truncate.py`
  - thin wrapper

### 5.3 ローカル開発用

- `./.quiet-droid/hooks.json`
- `./.quiet-droid/hooks/smart_truncate.py`

これらはリポジトリ内での検証用です。

## 6. イベントフロー

### 6.1 通常のツール実行

1. Agent がツールを実行する
2. ツール出力を受け取る
3. `PostToolUse` または `PostToolUseFailure` を emit する
4. hook が `transformedOutput` を返せば本文を差し替える
5. 差し替え後の本文を TUI 表示と session 履歴へ保存する

### 6.2 installer 実行

1. 利用者が `quiet-droid install-hooks` を実行する
2. `~/.config/quiet-droid/hooks/` を作成する
3. wrapper script を書き出す
4. `hooks.json` を生成する
5. 既存 `hooks.json` があれば既定では上書きしない

## 7. hook 入出力仕様

### 7.1 入力 payload

hook には JSON が stdin で渡されます。

主な項目:

- `hook_event_name`
- `tool_name`
- `tool_input`
- `tool_response`
- `duration_seconds`
- `session_id`
- `transcript_path`
- `cwd`
- `permission_mode`
- `model`
- `api_base_url`

### 7.2 出力 payload

smart truncation hook は次の形式を返します。

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "transformedOutput": "要約済み本文"
  }
}
```

`transformedOutput` を返さない場合、本体は元の `tool_response` をそのまま使います。

## 8. smart truncation ロジック

### 8.1 適用条件

次の条件を満たすときだけ動作します。

- event が `PostToolUse` または `PostToolUseFailure`
- backend が local と判定される
- 出力長がツール別上限を超える

### 8.2 local backend 判定

次の host を local とみなします。

- `localhost`
- `::1`
- private IP
- loopback IP
- `.local` ドメイン

remote API では処理を素通しします。

### 8.3 行選択ルール

次の行を優先的に残します。

- 先頭の一定行数
- 末尾の一定行数
- `Traceback`
- `Error`
- `Exception`
- `Warning`
- `permission denied`
- `(exit code: N)`
- diff ヘッダと変更行

中間で抜けた範囲は `...(N lines omitted)...` で表現します。

### 8.4 アーティファクト保存

全文はプロジェクト配下の `.quiet-droid/artifacts/` へ保存します。

要約本文の末尾には次の注記を付けます。

```text
[full output saved to .quiet-droid/artifacts/....log]
```

### 8.5 保存先正規化

単体実行や wrapper 経由実行では `cwd` が `.quiet-droid` や `.quiet-droid/hooks` になることがあります。

このため、保存先決定前に project dir を正規化します。

- `.../.quiet-droid/hooks` ならプロジェクトルートへ戻す
- `.../.quiet-droid` なら1階層親へ戻す

## 9. しきい値

現在の主なしきい値は次の通りです。

- 既定要約上限: 8000文字
- `Bash`: 12000文字
- `SubAgent`: 12000文字
- `ParallelAgents`: 10000文字
- 先頭保持: 18行
- 末尾保持: 18行
- 1行最大表示: 240文字

`Bash` 側の事前切り詰めは、hook が働く前に情報が落ちないよう 120000 文字へ緩和しています。

## 10. install-hooks 仕様

コマンド:

```bash
quiet-droid install-hooks
quiet-droid install-hooks --force
qd install-hooks
```

仕様:

- `hooks.json` が無ければ生成
- `smart_truncate.py` wrapper を生成
- script 実行コマンドには現在の `sys.executable` を埋め込む
- `--force` なしでは既存 `hooks.json` を上書きしない

このコマンドを明示実行にしている理由は、利用者が必ずしもローカルLLMを使うとは限らないためです。

## 11. エラーハンドリング

設計上の扱いは次の通りです。

- hook が JSON を返さない場合は無効として扱う
- hook が変換を返さない場合は元の本文を使う
- backend が local でなければ無変換
- wrapper script が失敗しても本体は元の出力で継続できる

この設計により、hook は補助機能であり、本体の可用性を下げないようにしています。

## 12. 制約

- 現状は `command` hook のみ対応
- 本文変換はプレーンテキスト前提
- JSON 構造や表構造を深く理解した要約はまだ行わない
- 全文保存先はプロジェクト配下固定
- `hooks.json` 既存内容との自動マージは未対応

## 13. 今後の拡張候補

- ツール別の構造認識
  - diff
  - pytest
  - JSON
  - build logs
- `hooks.json` の安全なマージ支援
- artifact のローテーション
- 重要行抽出ルールの設定ファイル化
- `Read` `Write` 系ツールへの適用拡大
- LLM要約とのハイブリッド化

## 14. 関連ファイル

- `quiet_droid/hooks.py`
- `quiet_droid/agent.py`
- `quiet_droid/config.py`
- `quiet_droid/app.py`
- `quiet_droid/hook_installer.py`
- `quiet_droid/smart_truncate_hook.py`
- `docs/hooks.md`
- `docs/hooks_JP.md`
