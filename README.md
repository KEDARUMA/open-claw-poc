# OpenClawでAI社員を試してみる

AI社員による業務自動化が流行っているようなので、実際に試してみることにした。
AIが自走し、課題を自己解決しながら人のように振る舞う仕組みを検討したところ、複数のAIエージェント基盤があり、比較・検討した結果、OpenClawを採用する事にした。
OpenClawを選んだ理由は、Agentが視覚的に表示されて状態を把握しやすいこと、各Agentへ個別に指示を出しやすいこと、Codexをサブスクリプション認証で利用できること、GitHubでの評価や利用規模が大きく、コミュニティも活発であること。

## 現在の構成

### OpenClawのAI社員

この環境では、次の6名をOpenClawに登録し、それぞれ専用の作業ディレクトリ（workspace）と役割指示を設定している。

| 役割               | 登録ID      | 担当                                                   |
| ------------------ | ----------- | ------------------------------------------------------ |
| Manager            | `main`      | 成果物を統合し、完了状況をまとめる                     |
| ソフトウェア設計者 | `architect` | システム構成、API、データモデルなどを設計する          |
| UI/UXデザイナー    | `designer`  | 画面と利用者の操作フローを設計する                     |
| Webアプリ開発者    | `engineer`  | 方針に沿ってコードを変更する                           |
| Reviewer           | `reviewer`  | 決められた完了条件に照らして方針と成果物をレビューする |
| QA                 | `qa`        | 受入条件に沿ってテストと動作確認を行う                 |

Managerはユーザーの依頼を作業単位に分け、ほかの5名へ担当を割り振る。

役割指示の配置と適用範囲は [AI社員が使う指示ファイル](docs/AI社員_指示ファイル一覧.md) に記載した。AI社員を実行しチャット接続を管理する常駐プロセス（Gateway）と、状態確認や操作を行うブラウザー画面（Control UI）にはOpenClaw標準機能を使う。AI社員専用の管理画面はない。

### Pythonでの作業進行とレビュー制御

バックエンドにはPythonを使用しており、1件ごとの依頼をTask単位で管理しながら作業を進行する。基本の流れは、作業方針の提示、方針レビュー、実装、実装結果レビューの順で進む。

各レビューで合格しなかった場合は、再度作業方針の提示まで戻ってやり直す「Review Loop Core」を組み込んでいる。このレビュー制御が、最終的な成果物の完成度を大きく左右する。

Task登録、AI社員の実行、状態とレビュー履歴の保存を行うRLC APIの起動方法は [Review Loop Coreの起動とAPI](docs/RLC_起動とAPI.md) を参照する。

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
