# LangBot Skill Authoring

LangBot Skill Authoring は、LangBot 向けの Skill 作成・蓄積プラグインです。実行トレース、QA 証拠、トラブルシューティングメモ、ユーザーフィードバック、完了済みの会話ターンを、レビュー可能な `SKILL.md` 草案へ変換します。

これは LangBot の Skill ランタイムを置き換えるものではありません。Skill の発見、アクティベート、マウント、実行は引き続き LangBot が担当します。このプラグインは、登録前の作成ワークフローを補います。

```text
source evidence -> candidate -> risk report -> review -> export / publish package
```

個人アシスタント用途では、制御された自動蓄積モードも利用できます。

```text
source evidence or completed turn
  -> auto candidate -> risk report -> policy gate -> optional auto review / export
```

自動蓄積は `auto_deposition_enabled` のマスタースイッチで制御され、デフォルトでは無効です。

## ランタイム境界

このプラグインは、LangBot が Skill を発見、アクティベート、マウント、実行する方法を変更しません。ランタイムは引き続き LangBot Core が管理します。

- Agent は `/workspace` 配下に Skill パッケージを作成し、組み込みの `register_skill` ツールを呼び出せます。
- 管理者は既存の `/api/v1/skills` API で Skill を管理できます。
- アクティベート済み Skill は既存の sandbox と権限チェックを利用します。

このプラグインが担当するのは登録前の工程です。何を保存すべきかを判断し、構造化された草案を生成し、secrets や環境依存のリスクを検査し、レビュー / 検証証拠を残し、通常のランタイム登録に渡せる Skill パッケージを出力します。

## 自動蓄積モード

自動蓄積は、ユーザーが確認した会話、繰り返し使う手順、トラブルシューティング経験を、個人アシスタントがワンクリックで学習するための機能です。

有効化すると、Page の `One-click Deposit` アクションと `skill_auto_deposit` ツールは次を行います。

1. 入力された証拠から Skill 候補を作成します。
2. 構造化された Skill 草案を生成します。
3. 決定的なリスクスキャンを実行します。
4. 設定されたリスクポリシーを適用します。
5. 許可される場合、自動レビュー記録を追加してパッケージを export します。

このモードでも、ランタイム Skill レジストリへ直接 publish することはありません。結果には `register_skill_hint` が含まれます。Agent はパッケージを `/workspace/<skill-name>` に書き出した後、LangBot 組み込みの `register_skill` ツールを呼び出せます。

このプラグインは、完了済みの LangBot ターンから受動的に学習することもできます。`auto_deposition_enabled` と `post_response_candidate_enabled` の両方が有効な場合、EventListener は `NormalMessageResponded` を監視し、現在の `user_message_text`、assistant の `response_text`、呼び出された関数名、利用可能な query vars を読み取ります。決定的な信頼度が高い場合、またはユーザーが「沉淀一下」「记住这个流程」「make this a skill」のように明示した場合だけ、Skill 候補を作成します。

応答後の抽出は保守的に設計されています。

- デフォルトでは無効
- デフォルトでは個人チャット / 個人アシスタント用途のみ
- デフォルトでは候補作成のみで、自動 export はしない
- 任意の自動 export も `auto_deposition_policy` に従う
- ランタイム `register_skill` は自動実行しない
- LongTermMemory へ自動書き込みしない

関連設定:

- `auto_deposition_enabled`: 自動蓄積のマスタースイッチ。デフォルト `false`
- `auto_deposition_policy`: 自動蓄積のリスクポリシー。`pass_only`、`allow_warn`、`allow_blocked`
- `auto_deposition_reviewer`: 自動レビュー記録に使う reviewer ラベル
- `post_response_candidate_enabled`: 応答後候補抽出を有効化。デフォルト `false`
- `post_response_auto_export`: 応答後候補の自動レビュー / export を許可。デフォルト `false`
- `post_response_private_only`: 個人チャットのみに限定。デフォルト `true`
- `post_response_min_confidence`: 候補作成に必要な最小信頼度。デフォルト `0.72`
- `post_response_max_source_chars`: 候補の source excerpt にコピーする最大文字数。デフォルト `6000`
- `post_response_explicit_only`: 明示的な蓄積指示がある場合のみ候補作成。デフォルト `false`

自動蓄積はリスクとコストを明示します。

- リスク: 一回限りの手順を過度に一般化する、個人情報やプライベート文脈を保存する、secrets やローカルパスを漏らす、prompt injection テキストを長期指示として保存する
- コスト: source 文字数、plugin storage 書き込み、任意の package export 書き込み、ランタイム変更、LLM 呼び出し有無。現在の決定的 MVP では LLM 呼び出しはありません

## ライフサイクルと保持

Hermes 型の学習には、書き込みだけでなく provenance、ガバナンス、回復可能な忘却が必要です。このプラグインは、蓄積された Skill 候補に軽量なライフサイクルを持たせます。

```text
candidate -> active -> deprecated -> archived
                  \-> superseded
```

各候補には provenance メタデータが含まれます。

- `origin`: `manual`、`auto_deposition`、`agent_review`、`imported`、`runtime_registered` など
- `protected`: 保護された候補は、明示的に `force=true` を渡さない限り deprecated、archived、superseded にできません
- `auto_curation_eligible`: 将来の自動ガバナンスフローで扱える候補であることを示します

`skill_lifecycle_manage` ツールまたは Page API でライフサイクルイベントを記録できます。

- 正のシグナル: `used`、`success`、`positive_feedback`、`eval_pass`
- 負のシグナル: `failure`、`negative_feedback`、`eval_fail`、`stale`、`security_issue`、`memory_conflict`、`superseded`

保持評価はスコアを計算し、`keep`、`deprecate`、`archive`、`superseded` を提案します。レポート内の `auto_apply_allowed` は、将来その操作を自動適用してよいかどうかを区別するためのものです。現在このプラグインが変更するのは自身のガバナンス記録だけです。ランタイム Skill の削除、非表示、復元には、LangBot 既存の Skill 管理機能または将来の admin proxy が必要です。

export されるパッケージには次が含まれます。

- `SKILL.md`
- `references/source-excerpt.md`
- `references/risk-report.json`
- `references/provenance.json`
- `references/learning-decision.json`
- `references/support-files.json`

セッション固有の詳細は support files に分離し、一回限りの実行記録をそのまま狭すぎる Skill にしない設計です。

## LongTermMemory との連携

LongTermMemory と Skill Authoring は別々の資産レイヤーとして扱うのが適切です。

- LongTermMemory L1: 安定したプロフィール事実と好み
- LongTermMemory L2: 状況記憶、意思決定、イベント、修正履歴
- Skill Authoring: ツール、手順、ガードレール、検証が必要な再利用可能な手順

`skill_lifecycle_manage` は `memory_plan` をサポートします。source が Skill、L1 profile 更新、L2 episodic memory、または手動レビューのどれに向いているかを分類できます。両方に該当する場合は、実行可能な手順を Skill として保持し、短い provenance や使用サマリーだけを L2 に保存するのが推奨です。

プラグインは機械可読な `learning-decision/v1` オブジェクトと、任意の LongTermMemory ツール提案を返します。このプラグインは LongTermMemory を直接呼び出しません。Agent または将来の host レベル workflow が、ユーザーレビュー後に提案された `update_profile` や `remember` を実行できます。

LongTermMemory がインストールされている場合、応答後候補には利用可能な `_ltm_context` の要約が provenance として保存されます。これにより、reviewer は session / speaker 文脈を把握できますが、2 つのプラグインを直接結合したり、記憶を重複書き込みしたりしません。

## Hermes との対応状況

このプラグインで実装済み:

- リスク / コスト開示付きのワンクリック蓄積
- `NormalMessageResponded` を使った LangBot-native な応答後候補抽出
- provenance、保護フラグ、自動ガバナンス資格
- 回復可能な archive / deprecate / supersede を持つライフサイクルスコアリング
- support files manifest を含む export パッケージ
- LongTermMemory 連携用の `learning-decision/v1`

このプラグイン内では未実装:

- Hermes のような完全会話をレビューするバックグラウンド fork
- prompt-cache-aware な補助モデルルーティング
- 現在の event / query vars を超えた完全な tool result trace レビュー
- ランタイム Skill の直接 archive / delete / restore
- インストール済み runtime Skills 全体に対する自動 umbrella consolidation

これらには、より安定した LangBot host API が必要です。具体的には、より完全な実行 trace、クロスプラグイン呼び出し、runtime Skill provenance、回復可能な runtime archive / restore です。現在の候補作成ループの前提条件ではありません。

今後の pipeline refactor 計画は `docs/pipeline-host-integration-plan.md` にあります。

## 現在利用できる機能

- 候補、レビュー、検証、export の Page backend API
- 管理者向け Page UI
- LLM から呼び出せるツール:
  - `skill_auto_deposit`
  - `skill_lifecycle_manage`
  - `skill_candidate_create`
  - `skill_candidate_risk_check`
  - `skill_candidate_export`
- source refs と risk notes を含む決定的な `SKILL.md` 生成
- LangBot 内では plugin storage、テストやオフライン開発では in-memory fallback を利用

## 開発

```bash
python -m pytest
```

LangBot plugin SDK CLI が利用できる場合は次でビルドできます。

```bash
lbp build
```

LangBot 内で実行する場合、Agent は export されたパッケージを `/workspace` に書き込み、組み込みの `register_skill` ツールで最終的な runtime Skill を作成できます。レビュー画面から直接 publish したいデプロイでは、将来的に Page backend から `/api/v1/skills` を呼び出す拡張も可能です。
