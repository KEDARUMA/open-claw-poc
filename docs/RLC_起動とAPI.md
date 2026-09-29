# Review Loop Coreの起動とAPI

## 起動

プロジェクトルートでPython 3.12を使い、依存パッケージをインストールします。

    python -m pip install -r ai-employees/requirements.txt
    python -m uvicorn app.api:app --app-dir ai-employees --host 127.0.0.1 --port 8000

このAPIはGatewayを起動・停止しません。AI社員を呼び出すときは、既存OpenClaw Gatewayが稼働し、main、engineer、reviewerを含む6名が登録されている必要があります。呼び出しには scripts/openclaw-control.ps1 cli agent を使います。

## Taskの登録と実行

POST /tasks にGoalと固定Baseline Requirementsを渡します。Baselineは作成後にAPIから変更できません。

    {
      "goal": "一覧画面を実装する",
      "baseline_requirements": [
        {
          "requirement_id": "BR-001",
          "text": "利用者が登録済みの項目一覧を閲覧できる"
        },
        {
          "requirement_id": "BR-002",
          "text": "一覧を名前の昇順で表示する"
        }
      ]
    }

登録応答の task.task_id を使って、次のAPIを呼び出します。

| 操作 | API |
| --- | --- |
| 実行 | POST /tasks/{task_id}/run |
| 状態取得 | GET /tasks/{task_id} |
| イベント履歴取得 | GET /tasks/{task_id}/events |
| 停止 | POST /tasks/{task_id}/stop |
| Human Requiredから再開 | POST /tasks/{task_id}/resume |

run と resume は非同期で受け付けます。engineerがPlan作成・実装を行い、reviewerがBaseline Requirementsに限定してPlanと結果をレビューします。レビュー指摘を次のWorker呼び出しへ渡す処理はありません。

停止要求やプロセス再起動で実行が中断されたTaskは HUMAN_REQUIRED になります。作業状態を人が確認してから resume を呼び出してください。再開時は同じTask・BaselineでReview Loopを最初から実行します。

## 保存先

Task、Baseline、状態、履歴、Plan、レビュー応答、実行結果、OpenClaw session IDと利用量は、既定で .openclaw/rlc/tasks.sqlite3 に保存します。この保存先はGit管理対象外です。別の場所を使う場合は、API起動前に RLC_DB_PATH を設定してください。

GET /tasks/{task_id}/events のAgent応答イベントには、観測できたturn数、tool call数、費用、session IDを記録します。OpenClawが費用を返さない場合は cost_usd が null になります。

API仕様は起動後に http://127.0.0.1:8000/docs で確認できます。
