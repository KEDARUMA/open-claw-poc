# AI社員が使う指示ファイル

2026-09-28時点で、OpenClawには6名の社員を登録している。各社員は設定された専用ワークスペースの `AGENTS.md` と `SOUL.md` を使う。

## 社員ごとの配置

| 社員 | agent ID | 使用するAGENTS.md | 使用するSOUL.md | SOULの正本 |
| --- | --- | --- | --- | --- |
| マネージャー | `main` | `.openclaw/workspaces/main/AGENTS.md` | `.openclaw/workspaces/main/SOUL.md` | `ai-employees/employee-profiles/roles/manager/SOUL.md` |
| ソフトウェア設計者 | `architect` | `.openclaw/workspaces/architect/AGENTS.md` | `.openclaw/workspaces/architect/SOUL.md` | `ai-employees/employee-profiles/roles/architect/SOUL.md` |
| UI/UXデザイナー | `designer` | `.openclaw/workspaces/designer/AGENTS.md` | `.openclaw/workspaces/designer/SOUL.md` | `ai-employees/employee-profiles/roles/designer/SOUL.md` |
| Webアプリ開発者 | `engineer` | `.openclaw/workspaces/engineer/AGENTS.md` | `.openclaw/workspaces/engineer/SOUL.md` | `ai-employees/employee-profiles/roles/engineer/SOUL.md` |
| レビュワー | `reviewer` | `.openclaw/workspaces/reviewer/AGENTS.md` | `.openclaw/workspaces/reviewer/SOUL.md` | `ai-employees/employee-profiles/roles/reviewer/SOUL.md` |
| QA | `qa` | `.openclaw/workspaces/qa/AGENTS.md` | `.openclaw/workspaces/qa/SOUL.md` | `ai-employees/employee-profiles/roles/qa/SOUL.md` |

`SOUL.md` は各社員の役割・人格を定める。2026-09-28に確認し、6名のワークスペース側SOULは各役割SOULの正本と一致している。

共通のCodex作業指示は、6つのワークスペースの親にある `.openclaw/workspaces/AGENTS.md` から適用する。各社員のワークスペースにも個別の `AGENTS.md` があり、そちらも使用される。共通の親ファイルと社員別ファイルは別々に保存され、自動同期されない。

`ai-employees/employee-profiles/common/AGENTS.md` は現在空であり、実際に適用される共通ルールの正本ではない。

## 読み込み範囲

- OpenClawは各agentの `workspace` 設定に従い、その社員用ワークスペースを使う。現在の設定では6名それぞれに専用ディレクトリを指定している。
- OpenClawはワークスペースの `AGENTS.md` を作業指示として、`SOUL.md` を役割・口調として各セッションで読み込む。
- `agents.defaults.skipBootstrap=true` は指示ファイルの自動生成を止める設定である。すでに置かれている `AGENTS.md` と `SOUL.md` の読み込みは止めない。
- Codex連携の `plugins.entries.codex.config.appServer.homeScope` は `agent` に設定している。ユーザー個人のCodexホームと社員のCodexホームを分ける。
- Codexは実行フォルダーまでのプロジェクト指示ファイルも読み込む。このプロジェクトのルート `AGENTS.md` は現在 `# AGENTS` だけの内容だが、6名のワークスペースの親ディレクトリにある。ここへ指示を書き足すと、Codexが社員共通の追加指示として読む可能性がある。
- 既存の `.openclaw/workspace/AGENTS.md` は今回登録した6名の `workspace` には指定されていない。社員6名の指示ファイルとしては使われない。
- OpenClaw本体や同梱ドキュメント、テスト用データにも `AGENTS.md` が存在する。この一覧は `agents.entries` に登録された社員6名のワークスペースを対象にしている。

## 指示を変更するとき

共通指示を変更する場合は `.openclaw/workspaces/AGENTS.md` を編集する。社員別指示を変更する場合は各社員のワークスペースにある `AGENTS.md` を編集する。役割SOULは `ai-employees/employee-profiles/roles/` の正本を編集し、該当ワークスペースの `SOUL.md` に手動で反映する。2026-09-28時点で、起動時に自動コピーする仕組みはない。

変更後は各ワークスペースのファイル内容を正本と照合する。OpenClawのCodex連携で既に開いているネイティブスレッドは、開始時に渡された `AGENTS.md` のスナップショットを保持する。更新内容を反映するには新しいスレッドを開始する。

## 参照先

| 内容 | 参照先 |
| --- | --- |
| 社員登録とワークスペース | `.openclaw/openclaw.json` の `agents.entries` |
| 共通Codex作業指示 | `.openclaw/workspaces/AGENTS.md` |
| 社員別作業指示 | `.openclaw/workspaces/{agent-id}/AGENTS.md` |
| 役割別SOULの正本 | `ai-employees/employee-profiles/roles/` |
| OpenClawのワークスペース指示ファイル説明 | `.openclaw-runtime/cli/node_modules/openclaw/docs/concepts/agent-workspace.md` |
| OpenClawのCodex実行フォルダーと指示ファイル | `.openclaw-runtime/cli/node_modules/openclaw/docs/concepts/system-prompt.md` |
| Codex harnessのプロジェクト指示とスレッド | `.openclaw-runtime/cli/node_modules/openclaw/docs/plugins/codex-harness/configuration.md` |
| `skipBootstrap` の説明 | `.openclaw-runtime/cli/node_modules/openclaw/docs/gateway/config-agents/workspace-and-bootstrap.md` |
