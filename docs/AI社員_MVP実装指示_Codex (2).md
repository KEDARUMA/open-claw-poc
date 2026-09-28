# AI社員プラットフォームの最小構成（MVP）実装指示書

## 0. この文書の目的

ターミナルからAIへ作業を依頼できるツール（Codex CLI）が、追加の設計相談なしにAI社員プラットフォームのMVP実装へ着手できるよう、仕様・設計理由・実装順・受入条件を固定する。

本システムでは、ユーザーの依頼を個別に実行・確認できる作業単位（Task）へ分ける。各Taskの完了は、定めた要件（Baseline Requirements）に照らして判定する。社員が計画と作業を進め、別の社員がそれらを確認する。高・中の問題が見つかれば計画へ戻す。この進行管理がReview Loop Coreの基本動作だ。人間は管理APIと画面（Control Plane）で進捗を確認し、停止や差し戻しを行う。

本プロジェクトの目的は、汎用マルチエージェントFWを作ることではない。

**AI社員を作成・配置し、複数のAI社員が役割分担しながら自走し、人間が作業状況を可視化・停止・差し戻しできるローカル実行基盤を作る。**

最初のMVPでは、ソフトウェア開発チームをAI社員として再現する。

---

# 1. 現在確定している前提

MVPでは以下を固定する。

- OS: Windows 11
- Runtime: Python 3.12
- AI社員の実行・観測基盤: AgentScope 2.x
- AI実行: ローカルPC上のCodex CLI
- Codex認証: 現在利用中のChatGPTサブスク認証
- AI社員: Manager / Engineer / Reviewer / QA
- 各AI社員を、システム上で作業を受け持つ実行主体（Agent）として扱う
- 4名全員がCodex CLIを利用する
- 社員ごとに独立した会話履歴（Codex session）を持つ
- 同じTaskで同じ社員が続けて作業するときは、同一sessionをresumeして使い続ける
- 全AgentはMVPでは技術的にフルアクセス可能とする
- 通常工程では人間の承認を待たず自走する
- Review Loop Coreを開始するTaskには必ず `Baseline Requirements` を持たせる
- 重要度が高・中のレビュー指摘があればPLANからやり直す
- 規定回数のやり直し、異常、上限超過時だけ、ユーザー確認が必要な停止状態（HUMAN_REQUIRED）へ移る
- AI実行層は抽象化し、将来CodexからローカルLLM等へ差し替え可能にする

### 理由

現時点でユーザーが実運用上の品質を確認できているAI実行環境が、ローカルPC上のCodex CLIだから。

最初からQwen、Ministral、Ollama等を同時導入すると、Agent Orchestration、Review Loop、Prompt、モデル性能、LLM Runtimeの問題が混在し、原因切り分けが難しくなる。

まずCodexだけでAI社員システムそのものを成立させる。

---

# 2. MVPで作るAI社員

## 2.1 Manager

役割:

- ユーザーの依頼を受ける
- 依頼をTaskへ分解する
- 明確で具体的なTask Goalを `Baseline Requirements` として確定する
- Goalが遠い・抽象的・曖昧で、レビュー基準として使える粒度のBaseline Requirementsを新たな推測なしに確定できない場合はHUMAN_REQUIREDへ移行してユーザーに定義を求める
- Engineer / QAへTaskを割り当てる
- 各Taskの状態を監視する
- 完了条件を満たしたら全体を完了にする

Roleルール:

- 原則として製品コードを自分で実装しない
- Task分解・割当・進捗判断が主業務

## 2.2 Engineer

役割:

- 実装対象を調査する
- 実装方針を作成する
- 承認済み方針に従ってコードを変更する
- build / unit test等、実装に必要な確認を行う
- Review指摘がHIGH / MEDIUMなら方針からやり直す

## 2.3 Reviewer

役割:

- Manager / Engineer / QAが作成した方針をレビューする
- Manager / Engineer / QAの成果物をレビューする
- HIGH / MEDIUM / LOWの問題を構造化して返す
- 自分で成果物を修正しない

**Reviewerは品質ゲート専用Agentとする。**

Review Loop Coreは「成果物を作る作業主体Agent」に適用し、Reviewer自身へ同じReview Loopを再帰適用しない。

### 理由

Reviewer自身をさらに別Reviewerでレビューすると、Reviewer → Reviewer → Reviewerという無限再帰が発生するため。

Reviewer品質は、別のReview Loopではなく以下で担保する。

- 構造化Schema検証
- Codex sessionの独立
- review retry
- confidence検査
- 異常時HUMAN_REQUIRED
- 実行ログ保存

## 2.4 QA

役割:

- テスト方針を作成する
- 必要なbuild / unit / E2Eを実行する
- テスト証跡を残す
- 不具合を構造化して返す
- Review指摘がHIGH / MEDIUMならテスト方針からやり直す

MVPではWeb QAを対象とする。
Mobile/AppiumはMVP対象外。

---

# 3. 全体アーキテクチャ

AI社員の実行、レビュー制御、人による確認・操作を分け、Taskや実行履歴を保存する。AIを呼び出す方式を交換できる層（AIBackend）と、情報を保存する領域（Store）を設ける。

```text
Windows 11
│
├─ AI社員 Platform
│
├─ AgentScope 2.x
│   ├─ Manager
│   ├─ Engineer
│   ├─ Reviewer
│   └─ QA
│
├─ Review Loop Core
│
├─ AIBackend
│   ├─ Codex CLIとの接続（CodexBackend）       ← MVPで使用
│   └─ 他のAI基盤との接続（OtherBackend）      ← 将来差し替え用
│       ├─ Ollama / Qwen
│       ├─ Ministral
│       └─ その他
│
├─ Codex CLI
│   └─ ChatGPTサブスク認証
│
├─ Task / Session / Event Store
│   └─ SQLite
│
├─ FastAPI Control Plane
│
└─ Git / worktree
```

重要:

**AgentScopeはAgent実行と観測の基盤として使うが、Review Loop・状態遷移・上限制御の最終決定権は本プロジェクト側が持つ。**

### 理由

フレームワーク固有の自律判断に任せると、誤った前提のまま処理が進む問題を再発させる可能性がある。

本プロジェクトでは「AIが賢いから進ませる」のではなく、「決められた品質管理工程を通った場合だけ進める」を基本とする。

---

# 4. AI実行Backendの抽象化

AgentコードからCodex CLIを直接呼ばない。

```text
AIEmployee
    ↓
AIBackend
    ├─ CodexBackend      ← 現在使用
    └─ LocalLLMBackend   ← 将来追加
```

想定Interface:

```python
class AIBackend(Protocol):
    async def start_session(
        self,
        agent_id: str,
        task_id: str,
        initial_prompt: str,
    ) -> "BackendSession":
        ...

    async def resume_session(
        self,
        session_id: str,
        prompt: str,
    ) -> "BackendResult":
        ...

    async def cancel(self, session_id: str) -> None:
        ...
```

Agent側は以下を知らないこと。

- `codex` コマンドの詳細
- ChatGPT認証方式
- Codex JSONL形式
- Ollama URL
- 将来のmodel名

### 理由

将来的に、

```text
Manager  → Codex
Engineer → Codex
Reviewer → Qwen
QA       → Ministral
```

のようにAgent単位でAI実行Backendを変更できるようにするため。

AIモデルを変更するだけでReview LoopやTask管理を書き直す設計は禁止する。

---

# 5. Codex session管理

## 5.1 基本単位

**Task × Agent ごとに独立したCodex sessionを1つ持つ。**

例:

```text
Task #123
├─ Manager session   M-123
├─ Engineer session  E-123
├─ Reviewer session  R-123
└─ QA session        Q-123
```

## 5.2 session継続ルール

```text
新Task
    → 新session

同じTask + 同じAgent
    → 既存sessionをresume

Agent変更
    → そのAgent専用session

ユーザーがsession resetを指示
    → 新session

Task完了
    → session終了扱い
```

session切替をAI自身に判断させない。

### 理由

同じTaskで同じAgentのsessionを維持すると、調査内容、過去の判断、レビュー指摘、失敗履歴を毎回ゼロから説明し直さずに済む。

一方でEngineerとReviewerが同じsessionを共有すると、ReviewerがEngineerの前提や自己正当化に引っ張られる可能性がある。

そのためAgent間ではsessionを共有しない。

---

# 6. Sessionは正式な記憶ではない

**SQLite上のTask状態をSource of Truthとする。Codex sessionは作業用コンテキストである。**

DBへ最低限保存するもの:

- Task本文
- Task Goal
- Baseline Requirements
- root_task_id
- parent_task_id
- 前提Task参照
- 現在State
- 現在PLAN
- Review履歴
- restart_count
- assigned_agent_id
- AgentごとのCodex session ID
- 実行結果
- changed files
- git diff
- test結果
- Token / Usage情報（取得可能な範囲）
- 重要な設計判断
- human action

ManagerがTaskを分解した場合、子Taskは必ず `parent_task_id` で親Taskへ紐付ける。

MVPでは複雑なDAGスケジューラは作らない。必要最小限として、子Taskの親子関係と単純な前提Task参照だけを扱う。

Codex sessionのresumeに失敗した場合:

```text
resume失敗
    ↓
新Codex session作成
    ↓
DBからTask Snapshot生成
    ↓
bootstrap promptとして投入
    ↓
作業再開
```

Task Snapshotには最低限以下を含める。

- Task
- Task Goal
- Baseline Requirements
- 現在のPLAN
- 過去Review指摘
- 対応済み/未対応事項
- 現在のgit diff
- test結果
- 重要な設計理由

### 理由

AI社員の記憶をCodex sessionだけへ依存すると、session破損・削除・resume失敗時にTaskの経緯を失うため。

---

# 7. 最重要仕様: Review Loop Core

Review Loop Coreを適用する作業主体Agent:

- Manager
- Engineer
- QA

Reviewerは品質ゲート専用Agentであり、このLoopを自身へ再帰適用しない。

## 7.1 Baseline Requirements

**Review Loop Coreは、Taskに有効な `Baseline Requirements` が存在しない状態では開始してはいけない。**

原則:

- 明確で具体的なTask Goalが示されている場合、そのGoalをBaseline Requirementsとして使用する。
- System / Managerは、明示されたGoalを内容を増やさずに `BR-001`, `BR-002` ... の形式へ正規化してよい。完了条件が明示されている場合は、それもBaseline Requirementsへ含めてよい。
- Goalが遠い・抽象的・曖昧で、レビュー基準として使える粒度のBaseline Requirementsを新たな推測なしに確定できない場合、PLANへ進んではいけない。
- 上記の場合は `HUMAN_REQUIRED` へ移行し、reasonを `BASELINE_REQUIREMENTS_REQUIRED` としてユーザーにBaseline Requirementsの定義または明確化を求める。
- Baseline Requirementsが保存された後にReview Loopを再開する。
- Baseline Requirements不足はWorkerの品質問題ではないため、`restart_count` へ加算しない。

Baseline Requirementsの例:

```text
BR-001: ユーザーがブラウザからTaskを登録できる
BR-002: 登録されたTaskをEngineerへ割り当てられる
BR-003: Taskの現在StateをControl Planeで確認できる
```

## 7.2 Review Scope

Reviewは**Baseline Requirementsの範囲内だけ**で行う。

Reviewerは、Baseline Requirementsを満たすために必要な問題だけを指摘する。

以下は、それ自体がBaseline Requirements違反を引き起こしていない限り、Review findingとして扱わない。

- refactoring opportunity
- possible future requirement
- 将来不要になる可能性
- general improvement idea
- Baseline Requirements外のarchitecture / design preference
- 「こちらの方が綺麗」「一般的にはこちらが良い」といった要件外の好み

各Review findingは、どのBaseline Requirementに対する指摘なのかを必ず示す。

## 7.3 Review Finding Rules

- findingは1から始まる連番を持つ。
- severityは以下の3種類だけを使用する。

```text
HIGH
MEDIUM
LOW
```

- HIGH / MEDIUMが1件でも存在する場合はPLANへ戻る。
- LOWのみの場合は次工程へ進む。
- findingが0件の場合は次工程へ進む。

## 7.4 Flow

基本フロー:

```text
TASK_RECEIVED
    ↓
Baseline Requirementsは有効か？
    ├─ NO → HUMAN_REQUIRED
    │        reason = BASELINE_REQUIREMENTS_REQUIRED
    │        ↓
    │      ユーザーがBaseline Requirementsを定義
    │        ↓
    └─────── YES
             ↓
         PLAN_DRAFT
             ↓
         PLAN_REVIEW
             ↓
有効なReviewに HIGH / MEDIUM がある？
    ├─ YES → restart_count + 1 → PLAN_DRAFT
    └─ NO
         ↓
EXECUTE
         ↓
RESULT_REVIEW
         ↓
有効なReviewに HIGH / MEDIUM がある？
    ├─ YES → restart_count + 1 → PLAN_DRAFT
    └─ NO
         ↓
COMPLETE
```

**RESULT_REVIEWで問題が出てもEXECUTEへ直接戻さない。必ずPLAN_DRAFTへ戻す。**

### 理由

レビュー対象をBaseline Requirementsへ固定することで、Agentが依頼されていないリファクタリングや将来要件を勝手にスコープへ追加することを防ぐ。

また、実装だけを繰り返し修正すると、間違った設計前提を維持したまま変更を積み重ねる危険がある。

```text
悪い例

実装
↓
レビューNG
↓
実装修正
↓
レビューNG
↓
さらに修正
```

本システムでは:

```text
実装
↓
レビューNG
↓
PLANへ戻る
↓
Baseline Requirementsと設計前提から再確認
↓
再実装
```

とする。

この方法は現在の実開発で良い結果を出しているため、AI社員の基本品質管理プロセスとして採用する。

---

# 8. Reviewerの出力Schema

Reviewerは問題を1件だけ返す形式にしない。

複数指摘を返せる形式とする。

```json
{
  "summary": "レビュー全体の要約",
  "confidence": 0.93,
  "issues": [
    {
      "number": 1,
      "severity": "HIGH",
      "baseline_requirement_ids": ["BR-002"],
      "category": "DESIGN",
      "problem": "具体的な問題",
      "evidence": ["根拠1", "根拠2"],
      "required_action": "必要な対応"
    },
    {
      "number": 2,
      "severity": "LOW",
      "baseline_requirement_ids": ["BR-003"],
      "category": "IMPLEMENTATION",
      "problem": "軽微な問題",
      "evidence": [],
      "required_action": "必要な対応"
    }
  ]
}
```

category候補:

```text
REQUIREMENT
DESIGN
IMPLEMENTATION
TEST
SECURITY
PERFORMANCE
OPERABILITY
OTHER
```

severity候補:

```text
HIGH
MEDIUM
LOW
```

問題なしは `issues: []` とする。

Review promptには毎回Baseline Requirements全文とReview Scopeを含める。

ReviewResult validatorは最低限以下を検証する。

- `number` が1から始まる連番である
- `severity` が `HIGH` / `MEDIUM` / `LOW` のいずれかである
- 各Issueが1件以上の `baseline_requirement_ids` を持つ
- `baseline_requirement_ids` がTaskに存在するBaseline Requirement IDだけを参照している
- Baseline Requirements外の一般改善・将来要件・リファクタリング提案をReview findingとして要求しないPromptになっている

番号・severity・Baseline Requirement参照がSchema違反の場合はReviewer異常として扱い、WorkerをPLANへ戻さずreview retryする。

`overall_severity` はLLMに返させず、アプリ側で `issues[]` から決定論的に算出する。

```text
HIGHが1件以上   → HIGH
それ以外でMEDIUMが1件以上 → MEDIUM
それ以外でLOWが1件以上    → LOW
issuesが空               → NONE
```

### 理由

LLMに `overall_severity` と `issues[]` の両方を書かせると、両者が矛盾する可能性があるため。

---

# 9. Reviewer異常とWorker品質問題を分離する

以下はWorkerのPLAN不良ではなくReviewer側の実行異常として扱う。

- JSON parse失敗
- Schema違反
- confidenceが設定閾値未満
- Codex reviewer session error

この場合、WorkerをPLANへ戻さない。

処理:

```text
Reviewer異常
    ↓
同じReviewer sessionでreview retry
    ↓
規定回数失敗
    ↓
HUMAN_REQUIRED
```

Reviewer retryは `restart_count` に加算しない。

### 理由

Reviewerのフォーマットエラーや不確実性を理由にEngineerへ再設計させても、問題の原因を修正できないため。

---

# 10. restart_count

旧 `loop_count` は使用しない。

`restart_count` は、**有効なレビュー結果のHIGH / MEDIUMによってPLAN_DRAFTへ戻った回数**だけを数える。

初回実行は0。

例:

```text
初回PLAN                   restart_count = 0
MEDIUM → PLANへ戻る        restart_count = 1
HIGH   → PLANへ戻る        restart_count = 2
MEDIUM → PLANへ戻る        restart_count = 3
                           ↓
                    HUMAN_REQUIRED
```

MVPデフォルト:

```text
max_restart_count = 3
```

---

# 11. Task State

```python
class TaskState(str, Enum):
    TASK_RECEIVED = "TASK_RECEIVED"
    WAITING_DEPENDENCY = "WAITING_DEPENDENCY"
    PLAN_DRAFT = "PLAN_DRAFT"
    PLAN_REVIEW = "PLAN_REVIEW"
    EXECUTE = "EXECUTE"
    RESULT_REVIEW = "RESULT_REVIEW"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
```

状態変更は必ず `TaskStateMachine` 経由にする。

DBのstateをAgentやAPI endpointから直接書き換えることを禁止する。

Review retryはTask StateをPLANへ戻さず、PLAN_REVIEWまたはRESULT_REVIEW内の内部retryとして扱う。

前提Taskが未完了の場合は `WAITING_DEPENDENCY` とし、前提Task完了後に `PLAN_DRAFT` へ進める。

---

# 12. 同一Taskの排他制御

**同一Taskで同時にACTIVEになれるAgentは、Reviewerを含め常に1つだけとする。**

例:

```text
Task A: Engineer ACTIVE
Task A: QA       WAITING
Task A: Reviewer REVIEW時のみACTIVE
```

別Taskは並列実行可能。

```text
Task A → Engineer ACTIVE
Task B → QA       ACTIVE
```

は許可する。

### 理由

同じworktreeに対し、Engineer変更中、QAテスト中、Reviewer diff取得などが同時発生すると、観測対象が変化してレビュー結果の再現性がなくなるため。

MVPでは同一Taskを直列化して安全性を優先する。

---

# 13. Agent権限

MVPではManager / Engineer / Reviewer / QAすべて、OS・ファイル・Shell等へ技術的にはフルアクセス可能とする。

ただし**技術的権限とRole上の行動制約は別物**とする。

例:

- Manager: 技術的には書込み可能だが、Roleルールでは製品コードを書かない
- Reviewer: 技術的には書込み可能だが、Roleルールではレビュー対象を変更しない
- Engineer: 実装変更可能
- QA: テストコードを含め必要な変更を行える

### 理由

MVPでは権限管理の問題とAgent能力の問題を切り分けやすくするため。

将来Permission機能を追加できるよう、Tool実行層はAgent本体から分離する。

---

# 14. Codex CLI Adapter

CodexBackendはローカルPCにインストール済みで、ChatGPTアカウント認証済みの `codex` CLIを使用する。

OpenAI API Key経由のAPI実行はMVPでは使用しない。

実装開始前に現在のCodex CLIで以下を実測確認すること。

- version
- 非対話実行方法
- session ID取得方法
- session resume方法
- JSON / JSONL event出力方法
- cancel/interrupt方法
- sandbox / approval / permission関連の利用可能オプション
- 対話承認待ちを発生させず、必要なShell / File操作を行える実行モード
- Token / Usage情報を取得できるeventまたは出力

全AgentはMVPでは技術的にフルアクセス可能とするため、CodexBackendは**実機のCodex CLIが提供する範囲で、対話承認待ちによって自走が停止しない実行モード**を使用する。

ただし、sandbox/approvalを無効化する具体的なCLIオプション名は推測して文書へ固定しない。インストール済みCodexの `--help`、version、実行結果を確認して確定する。

**CLI引数やevent名を推測して実装しない。実機のCodex CLIのhelp / version /実行結果を確認してからAdapterを確定する。**

想定責務:

```python
class CodexBackend(AIBackend):
    async def start_session(...): ...
    async def resume_session(...): ...
    async def cancel(...): ...
    async def stream_events(...): ...
```

---

# 15. 共通Agent Event

Codex固有のeventをそのままシステム全体へ漏らさない。

```text
Codex JSONL
      ↓
CodexBackend
      ↓
Common Agent Event
      ↓
AgentScope / DB / Control Plane
```

最低限の共通Event:

```text
TASK_STARTED
PLAN_STARTED
PLAN_CREATED
PLAN_REVIEW_STARTED
PLAN_REVIEW_COMPLETED
REVIEW_RETRY
EXECUTION_STARTED
AI_OUTPUT
TOOL_CALL_STARTED
TOOL_CALL_COMPLETED
COMMAND_STARTED
COMMAND_COMPLETED
FILE_CHANGED
EXECUTION_COMPLETED
RESULT_REVIEW_STARTED
RESULT_REVIEW_COMPLETED
PLAN_RESTARTED
HUMAN_REQUIRED
TASK_COMPLETED
TASK_FAILED
TASK_CANCELLED
SESSION_STARTED
SESSION_RESUMED
SESSION_RECREATED
SESSION_FAILED
USAGE_UPDATED
```

Event形式:

```json
{
  "timestamp": "...",
  "agent_id": "...",
  "task_id": "...",
  "event_type": "...",
  "summary": "...",
  "data": {}
}
```

### 理由

将来CodexBackendをローカルLLM等へ差し替えても、Control PlaneとDBを作り直さないため。

---

# 16. 可視化方針

## AgentScope

MVPからAgentScope 2.xを使用する。

主用途:

- Agent管理
- Agent間メッセージ
- Agent実行の観測
- Event stream
- session/agent lifecycleの補助

## 独自Control Plane

AgentScope標準UIと重複する汎用トレース画面を一から作り直さない。

独自Control Planeは本プロジェクト固有の管理へ集中する。

表示対象:

- AI社員一覧
- Agent status
- Taskツリー（root / child / dependency / assigned agent / current state）
- 現在Task
- 現在Phase
- Baseline Requirements
- Codex session ID
- 現在PLAN
- PLAN Review
- RESULT Review
- issues一覧
- restart_count
- changed files
- git diff
- test結果
- elapsed time
- Token / Usage（取得可能な項目）
- Agent / Task / Session単位の累積Usage
- error
- human action履歴

操作:

- STOP
- RESUME
- CANCEL
- SESSION RESET
- HUMAN_REQUIREDからの再開
- コメント付き差し戻し

### 理由

AgentScopeはAgent実行を観測する基盤として使い、本プロジェクト特有のReview Loop、diff、Task状態、Human操作だけを独自UIへ追加することで二重実装を減らす。

---

# 17. AgentScopeだけへ依存しない観測

Codex CLIをsubprocessとして利用する以上、Codex内部のすべてのイベントがAgentScopeから必ず見えるとは限らない。

そのため本システム自身でも最低限以下をDBへ保存する。

```text
Agent
Role
Task
Current phase
Baseline Requirements
Codex session ID
Plan
Review result
AI output summary
Command
Changed files
git diff
Test result
restart_count
Execution time
Token / Usage（Codexが提供する取得可能な項目のみ）
Error
```

### 理由

AgentScopeやCodexのevent仕様が変わっても、AI社員を監督するための最低限の情報を失わないため。

---

# 18. Human-in-the-loop

通常工程では人間のApproveを待たない。

```text
PLAN
↓
PLAN REVIEW
↓
問題なし
↓
EXECUTE
↓
RESULT REVIEW
↓
問題なし
↓
COMPLETE
```

HIGH / MEDIUMの場合も、上限に達するまでは自動でPLANへ戻る。

以下のみHUMAN_REQUIREDへ移行する。

- `restart_count >= max_restart_count`
- Reviewer retry上限超過
- turn数上限超過
- tool call上限超過
- changed files上限超過
- execution時間上限超過
- 回復不能error
- session復旧不能
- ユーザーからSTOP

### 理由

目的はAI社員が自走することだから。

各工程で毎回人間が承認する仕組みにすると、自律化の利点を失う。

---

# 19. 暴走制限

MVPから以下を設定可能にする。

```yaml
limits:
  max_restart_count: 3
  max_review_retries: 2
  max_turns_per_phase: 12
  max_tool_calls_per_phase: 20
  max_changed_files: 10
  max_execution_minutes: 30
```

CodexがToken / Usage情報をリアルタイム取得できる場合は、Task / Agent / Session単位で累積してControl Planeへ表示する。

取得できるusage項目はCodex CLIの実測結果に従う。input/output/cached/reasoning/total等を取得できない場合、推測値を作らない。

Token上限をCodex CLI側で確実に強制できない場合でも暴走を抑えられるよう、turn数・tool call数・実行時間の上限を必ず持つ。

上限超過時にLLMへ「続けるべきか」を判断させない。

プログラム側で決定論的にHUMAN_REQUIREDへ遷移する。

---

# 20. Git / worktree

各実装TaskはGit worktreeで分離する。

```text
repo/
worktrees/
  task-0001/
  task-0002/
```

原則:

- AI社員がmain/masterを直接変更しない
- 同じTaskのAgentは同じTask worktreeを順番に利用する
- `git status` / `git diff` / `git worktree` 等、Task分離・確認に必要なGit操作は許可する
- Review時点のworking tree / diff情報をEventへ記録する
- **AI社員による `git commit` / `git push` はMVPでは禁止する**

commit/pushが必要になった場合は、ユーザーが明示的に許可した時点で別途仕様変更する。

---

# 21. Agent共通インターフェース

作業主体Agent:

```python
class WorkerAgent(Protocol):
    id: str
    role: str

    async def create_plan(self, task: "Task") -> "Plan":
        ...

    async def execute(
        self,
        task: "Task",
        plan: "Plan",
    ) -> "ExecutionResult":
        ...
```

Reviewer:

```python
class ReviewerAgent(Protocol):
    id: str

    async def review_plan(
        self,
        task: "Task",
        plan: "Plan",
    ) -> "ReviewResult":
        ...

    async def review_result(
        self,
        task: "Task",
        plan: "Plan",
        result: "ExecutionResult",
    ) -> "ReviewResult":
        ...
```

Review Loop:

```python
class ReviewLoopRunner:
    async def run(
        self,
        worker: WorkerAgent,
        reviewer: ReviewerAgent,
        task: "Task",
    ) -> "TaskResult":
        ...
```

### 理由

自己レビュー型の `employee.review_plan()` にすると、Engineer自身が自分の方針をレビューする実装へ流れやすい。

WorkerとReviewerをInterface上でも分離する。

---

# 22. ReviewResultモデル

```python
@dataclass
class ReviewIssue:
    number: int
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    baseline_requirement_ids: list[str]
    category: str
    problem: str
    evidence: list[str]
    required_action: str

@dataclass
class ReviewResult:
    summary: str
    confidence: float
    issues: list[ReviewIssue]
```

アプリ側関数:

```python
def effective_severity(review: ReviewResult) -> str:
    ...
```

LLMがoverall判定を決めるのではなく、コード側でissuesを集計する。

---

# 23. DB

MVPはSQLiteを使う。

最低限のRepository対象:

```text
agents
tasks
task_dependencies
task_sessions
task_events
plans
reviews
executions
usage_records
human_actions
```

重要:

- `tasks` は `root_task_id` / `parent_task_id` / `assigned_agent_id` とBaseline Requirementsを持てる設計にする
- Baseline Requirementsは `BR-001` 等のIDと本文を保持し、Review Issueから参照できるようにする
- `task_dependencies` はMVPでは単純な前提Task参照だけを扱う
- DB accessはRepository層へ隔離する
- 将来PostgreSQLへ移行可能にする
- session IDをTask × Agent単位で保存する
- UsageをTask × Agent × Session単位で集計可能にする
- State変更はStateMachine経由のみ

---

# 24. API / Control Plane backend

FastAPIを使用する。

最低限の機能:

- Agent一覧取得
- Task一覧/詳細取得
- Task開始
- STOP
- RESUME
- CANCEL
- SESSION RESET
- HUMAN_REQUIRED操作
- Event stream配信

リアルタイム更新はWebSocketを第一候補とする。

ただしAgentScope側で利用可能なevent transportと重複する場合は、実装前調査で最小構成を選ぶ。

---

# 25. UI

MVPではシンプルなHTML + JavaScriptでよい。

React等のSPA FWは導入しない。

目的はデザインではなく、AI社員の現在作業とレビュー状態を人間が把握できること。

AgentScope標準UIで確認できる情報を重複して作り込まない。

---

# 26. config.yaml

MVP初期案:

```yaml
app:
  host: "127.0.0.1"
  port: 8765

backend:
  default: "codex"

codex:
  command: "codex"
  timeout_sec: 1800

review:
  confidence_threshold: 0.5
  max_review_retries: 2

limits:
  max_restart_count: 3
  max_turns_per_phase: 12
  max_tool_calls_per_phase: 20
  max_changed_files: 10
  max_execution_minutes: 30

database:
  path: "./data/ai-employees.db"

workspace:
  worktrees_dir: "./worktrees"
```

将来Agent単位でBackendを変更できる構造にする。

例:

```yaml
agents:
  manager:
    backend: "codex"
  engineer:
    backend: "codex"
  reviewer:
    backend: "codex"
  qa:
    backend: "codex"
```

将来ここを `local_llm` 等へ変更できる。

---

# 27. 推奨ディレクトリ構成

```text
ai-employees/
├─ app/
│  ├─ main.py
│  ├─ config.py
│  │
│  ├─ agents/
│  │  ├─ base.py
│  │  ├─ manager.py
│  │  ├─ engineer.py
│  │  ├─ reviewer.py
│  │  └─ qa.py
│  │
│  ├─ backends/
│  │  ├─ base.py
│  │  └─ codex.py
│  │
│  ├─ core/
│  │  ├─ review_loop.py
│  │  ├─ review_models.py
│  │  ├─ state_machine.py
│  │  ├─ events.py
│  │  ├─ locks.py
│  │  ├─ snapshots.py
│  │  └─ limits.py
│  │
│  ├─ git/
│  │  └─ worktree.py
│  │
│  ├─ db/
│  │  ├─ models.py
│  │  ├─ repository.py
│  │  └─ sqlite.py
│  │
│  ├─ api/
│  │  ├─ agents.py
│  │  ├─ tasks.py
│  │  └─ events.py
│  │
│  └─ web/
│     ├─ index.html
│     ├─ app.js
│     └─ style.css
│
├─ tests/
│  ├─ test_state_machine.py
│  ├─ test_review_loop.py
│  ├─ test_review_models.py
│  ├─ test_review_retry.py
│  ├─ test_task_lock.py
│  ├─ test_session_store.py
│  └─ test_limits.py
│
├─ data/
├─ worktrees/
├─ config.yaml
├─ requirements.txt
├─ README.md
└─ run.py
```

`LocalLLMBackend`はMVPでは実装しない。

Backend interfaceだけ先に切っておく。

---

# 28. 実装フェーズ

## Phase 0: 実機調査

コード変更前に確認する。

- repository構造
- Python環境
- `codex` CLIの存在
- Codex version
- Codex非対話実行
- Codex session ID取得
- Codex resume
- Codex JSON/JSONL出力
- Codex cancel/interrupt
- Codex sandbox / approval / permission関連オプション
- Codexを対話承認待ちで停止させずに動かす方法
- Codex Token / Usage取得方法
- AgentScope 2.xの現在のAPI
- AgentScopeのevent stream
- AgentScope標準UIで見える情報

**推測でCLI Adapterを実装しない。**

## Phase 1: Review Loop Core

Fake Worker / Fake Reviewerだけで実装する。

実装対象:

- BaselineRequirement
- TaskState
- ReviewIssue / ReviewResult
- effective_severity
- StateMachine
- ReviewLoopRunner
- restart_count
- review retry
- Task lock
- limits
- Unit tests

受入条件:

- Baseline Requirementsが未定義の場合はPLAN_DRAFTへ進まず、HUMAN_REQUIRED / BASELINE_REQUIREMENTS_REQUIREDになる
- 明確で具体的なGoalを、内容を追加せずBaseline Requirementsへ正規化できる
- Review promptにBaseline RequirementsとReview Scopeが必ず含まれる
- Review Issueが1から始まる連番になる
- Review Issueが存在するBaseline Requirement IDを必ず参照する
- 存在しないBaseline Requirement IDや番号不正はReviewer異常としてreview retryになる
- issues=[] で正常完了
- LOWのみで正常完了
- MEDIUMが1件でもあればPLANへ戻る
- HIGHが1件でもあればPLANへ戻る
- HIGH + LOWの複数Issueを正しくHIGH判定する
- restart_countが規定値でHUMAN_REQUIRED
- Reviewer JSON不正時はWorkerをPLANへ戻さずreview retry
- review retry上限でHUMAN_REQUIRED
- 同一TaskでReviewerを含む複数Agentが同時ACTIVEにならない
- 前提Task未完了時はWAITING_DEPENDENCYになり、実行されない

## Phase 2: SQLite / Session Store

実装対象:

- Task保存
- Baseline Requirements保存
- root / parent / assigned agent保存
- 前提Task参照保存
- Event保存
- Task × Agent session ID保存
- PLAN / Review / Execution保存
- Usage保存
- Task Snapshot生成

受入条件:

- Process再起動後もTask状態を復元できる
- 親子Taskを復元できる
- session IDをAgent別に復元できる
- UsageをTask / Agent / Session単位で集計できる
- Snapshotを生成できる

## Phase 3: CodexBackend

受入条件:

- 新session開始
- session ID取得
- 同一session resume
- stdout/event取得
- Token / Usage取得（Codex CLIが提供する範囲）
- 対話承認待ちで停止しない実行モード
- cancel
- timeout
- common eventへ変換
- resume失敗時に新session + Snapshot bootstrapで復旧

## Phase 4: Engineer + Reviewer

```text
Engineer PLAN
↓
Reviewer PLAN REVIEW
↓
Engineer EXECUTE
↓
Reviewer RESULT REVIEW
↓
COMPLETE
```

を実際のCodex CLIで1 Task通す。

## Phase 5: AgentScope integration

受入条件:

- Agent実行が観測できる
- Codex common eventをAgentScope側へ流せる範囲を実測
- 標準UIで見える情報と独自UIが必要な情報を確定

## Phase 6: FastAPI Control Plane

受入条件:

- Task状態表示
- Review issues表示
- diff表示
- STOP
- RESUME
- SESSION RESET
- HUMAN_REQUIREDから再開

## Phase 7: Manager / QA

ManagerとQAを追加し、複数AI社員で1つの開発Taskを完了できる状態にする。

---

# 29. MVP対象外

以下を先に実装しない。

- Designer
- Figma
- Appium
- Gmail
- Calendar
- Slack
- Qdrant / RAG
- PostgreSQL
- Docker化
- VPS / Cloud配置
- 複数PC分散
- SaaS課金
- ユーザー認証
- 高度なPermission管理
- Ollama / Qwen / Ministral実装

これらはMVPのReview Loop、自走、可視化が成立した後で追加する。

---

# 30. 本プロジェクト自身の開発ルール

このAI社員プラットフォーム自体をCodexで開発するときは、**`$方針改修レビューループ`** を必ず適用する。

## Baseline Requirements

- ワークフロー開始前にBaseline Requirementsを必ず定義する。
- 明確で具体的なユーザーのGoalが示されている場合、そのGoalをBaseline Requirementsとして扱う。
- Goalが遠い・抽象的・曖昧でレビュー基準として使える粒度でない場合、方針表示へ進む前にユーザーへBaseline Requirementsの定義・明確化を求める。
- Baseline Requirementsがない状態でレビューや改修を開始しない。

## Review Scope

- ReviewはBaseline Requirementsの範囲内だけで行う。
- Baseline Requirements違反ではないリファクタリング案、将来必要／不要になりそうという予測、一般的改善、設計上の好みは指摘しない。
- Review findingsは番号付きとする。
- severityは `HIGH` / `MEDIUM` / `LOW` の3段階だけを使用する。

## Workflow

```text
1. 方針表示
2. 方針レビュー
3. HIGH / MEDIUMがあれば1へ戻る
4. 改修開始
5. 改修結果レビュー
6. HIGH / MEDIUMがあれば1へ戻る
```

追加ルール:

- 一度の変更範囲を小さくする
- 不要なリファクタ禁止
- 依頼されていない機能を追加しない
- 設計理由を残す
- ユーザーから明示されていないGit commit / pushは禁止

---

# 31. 設計理由の記録

重要な判断について、README、設計文書、ADR等へ以下を残す。

```text
何を採用したか
なぜ採用したか
何を採用しなかったか
将来どう変更できるか
```

例:

```text
現在は品質を確認できているCodex CLIを利用する。
ただし将来ローカルLLMへ変更する可能性があるため、AgentからAIBackendを抽象化する。
```

### 理由

別のCodex sessionや別の開発者が設計意図を知らず、「単純化」と称して重要な構造を削除することを防ぐため。

---

# 32. Codexが最初に行う作業

最初はPhase 0とPhase 1の**方針提示まで**行う。

1. repository構造を確認
2. ローカルCodex CLI環境を確認
3. AgentScope 2.xの利用可能な機能を確認
4. Phase 1の実装方針を提示
5. 変更予定ファイルを列挙
6. State Machine遷移表を提示
7. Baseline Requirementsの保持・判定・不足時の遷移を提示
8. Review SchemaとReview Scopeを提示
9. restart_count / review retryの扱いを提示
10. Unit Testケースを列挙
11. ここで停止

**ユーザーから「改修開始」と指示されるまでコードを変更しないこと。**
