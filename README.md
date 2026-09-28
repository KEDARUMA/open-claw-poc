# OpenClawでAI社員を試してみる

OpenClawは、自分で管理する環境で動かし、チャットから仕事を頼めるAIアシスタントである。

## 現在の構成

### OpenClawのAI社員

この環境では、次の6名をOpenClawに登録し、それぞれ専用の作業ディレクトリ（workspace）と役割指示を設定している。

| 役割 | 登録ID | 担当 |
| --- | --- | --- |
| Manager | `main` | 成果物を統合し、完了状況をまとめる |
| ソフトウェア設計者 | `architect` | システム構成、API、データモデルなどを設計する |
| UI/UXデザイナー | `designer` | 画面と利用者の操作フローを設計する |
| Webアプリ開発者 | `engineer` | 方針に沿ってコードを変更する |
| Reviewer | `reviewer` | 決められた完了条件に照らして方針と成果物をレビューする |
| QA | `qa` | 受入条件に沿ってテストと動作確認を行う |

Managerはユーザーの依頼を作業単位に分け、ほかの5名へ担当を割り振る。

役割指示の配置と適用範囲は [AI社員が使う指示ファイル](docs/AI社員_指示ファイル一覧.md) に記載した。AI社員を実行しチャット接続を管理する常駐プロセス（Gateway）と、状態確認や操作を行うブラウザー画面（Control UI）にはOpenClaw標準機能を使う。AI社員専用の管理画面はない。

### Pythonでの作業進行とレビュー制御

Python側には、1件ごとの依頼を管理する作業単位（Task）の状態を追い、レビューで指摘が出た場合に計画へ戻すコードがある。レビュー進行を制御するこの部分がReview Loop Coreだ。

Taskごとに完了判定の基準（Baseline Requirements）を定め、それに沿って進行とレビューを管理する。主な機能は次のとおり。

- Baseline Requirementsの検証とTask状態遷移
- Planと作業結果のレビュー、およびHIGH / MEDIUMの指摘後にPlanへ戻る制御
- Reviewerの出力形式・confidence検証と、形式不正時の再試行
- Task単位の排他制御と、実行時間・turn数・tool call数・変更ファイル数の上限

計画を作り作業を進める実行役（Worker）と、計画や成果物を確認する審査役（Reviewer）の呼び出し仕様を定義している。単体テストではテスト用WorkerとReviewerを使う。OpenClawや、ターミナルからAIに指示を出すツール（Codex CLI）を実際に呼び出す処理はまだない。

作業単位（Task）のDB保存、AI社員の状態確認・操作を行うAPIと画面（Control Plane）、AI社員の実行・観測に使うAgentScopeとの連携はPython実装に含まれない。Python実装はReview LoopとTask状態の制御コアまでだ。

## Review Loop Core

Taskごとに定めた完了判定の基準（Baseline Requirements）に沿ってレビューする。要件に違反しない一般改善、将来の要望、リファクタリングは指摘対象にしない。

```text
TASK_RECEIVED
├─ Baseline Requirementsなし → HUMAN_REQUIRED
├─ 前提Task未完了             → WAITING_DEPENDENCY
└─ PLAN_DRAFT → PLAN_REVIEW
                 ├─ HIGH / MEDIUM → PLAN_DRAFT
                 │                  (再開上限に達したらHUMAN_REQUIRED)
                 └─ それ以外 → EXECUTE → RESULT_REVIEW
                                              ├─ HIGH / MEDIUM → PLAN_DRAFT
                                              │                  (再開上限に達したらHUMAN_REQUIRED)
                                              └─ 指摘なし / LOWのみ → COMPLETE
```

Reviewerの出力形式やconfidenceに問題があるときは、設定回数まで同じReviewerで再試行する。上限に達すると `HUMAN_REQUIRED` に移る。Workerの回復不能エラーや実行上限の超過でも停止する。上限の初期値は `ai-employees/app/core/limits.py` にある。状態遷移は `ai-employees/app/core/state_machine.py` で定義している。

## OpenClawを使う理由

OpenClawでは、AI社員ごとに実行主体（Agent）と作業領域（Workspace）を分け、会話の進行状態（Session）を管理できる。各社員が使う機能（Tool）を実行し、活動状況は標準の管理画面（Control UI）で確認する。AI社員の基盤を自作せず、役割と仕事の流れを試せる。

セットアップ手順はOpenAI providerのCodex認証を使う設定を扱う。利用可能なモデルと利用量は契約内容とOpenClawの対応状況に従う。Ollamaは現在のセットアップ対象に含めていない。

## セットアップと操作

OpenClawの導入、認証、GatewayとControl UIの起動手順は [OpenClawセットアップ手順](docs/openclaw-setup.md) に記載した。セットアップ後は、次のスクリプトでGatewayを操作する。

AI社員の登録手順は [社員追加セットアップ手順](docs/社員追加セットアップ.md) を参照する。Codex CLIで実行する場合は、PowerShellでプロジェクトルートへ移動してから次のコマンドを実行する。

```powershell
codex exec --approve-for-me --cd . "docs/社員追加セットアップ.md を読み、この手順を実行してください。認証など人の操作が必要になったら、その場で停止して案内してください。"
```

```powershell
.\scripts\openclaw-control.ps1 start
.\scripts\openclaw-control.ps1 stop
.\scripts\openclaw-control.ps1 restart
.\scripts\openclaw-control.ps1 cli models status --check
```

## 参考資料

- [OpenClaw](https://openclaw.ai/)
- [OpenClaw Docs](https://docs.openclaw.ai/)
- [OpenAI providerの認証・セットアップ](docs/openclaw-setup.md)
- [AI社員の指示ファイル一覧](docs/AI社員_指示ファイル一覧.md)
