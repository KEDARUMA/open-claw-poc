"""既存OpenClaw社員をRLCのWorkerとReviewerへ接続する。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import shutil
from pathlib import Path
from typing import Any

from app.agents.base import ReviewerError, WorkerError
from app.core.models import AgentMetrics, AgentResult, ExecutionResult, Plan, Task
from app.core.review_models import ReviewIssue, ReviewResult


class OpenClawError(RuntimeError):
    """OpenClaw CLIの起動・応答異常を表す。"""


class OpenClawClient:
    """プロジェクト用CLIラッパーを介して社員を呼び出す。"""

    def __init__(self, project_root: Path) -> None:
        """リポジトリとOpenClaw CLIラッパーの場所を設定する。"""
        self.project_root = project_root.resolve()
        self.wrapper_path = self.project_root / "scripts" / "openclaw-control.ps1"

    async def ask(self, agent_id: str, task: Task, prompt: str) -> AgentResult[str]:
        """指定社員へ依頼し、本文とOpenClaw利用量を返す。"""
        if not self.wrapper_path.is_file():
            raise OpenClawError("OPENCLAW_WRAPPER_NOT_FOUND")
        powershell = (
            shutil.which("powershell.exe")
            or shutil.which("powershell")
            or shutil.which("pwsh")
            or "powershell.exe"
        )
        session_key = self._session_key(task.task_id)
        command = [
            powershell, "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(self.wrapper_path), "cli", "agent", "--agent", agent_id,
            "--session-key", session_key, "--message-file", "-", "--timeout",
            "1800", "--json",
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self.project_root,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            raise OpenClawError("OPENCLAW_CLI_START_FAILED") from error

        try:
            stdout, _ = await process.communicate(prompt.encode("utf-8"))
        except asyncio.CancelledError:
            await self._terminate_process(process)
            await process.communicate()
            raise
        except OSError as error:
            await self._terminate_process(process)
            await process.communicate()
            raise OpenClawError("OPENCLAW_CLI_IO_FAILED") from error

        if process.returncode != 0:
            raise OpenClawError("OPENCLAW_AGENT_CALL_FAILED")
        envelope = self._parse_envelope(stdout)
        if envelope.get("ok") is False or envelope.get("status") in {"error", "in_flight"}:
            raise OpenClawError("OPENCLAW_AGENT_RETURNED_ERROR")
        text = self._response_text(envelope)
        if not text.strip():
            raise OpenClawError("OPENCLAW_AGENT_RETURNED_EMPTY")
        return AgentResult(text, self._metrics(envelope, session_key))

    @staticmethod
    async def _terminate_process(process: asyncio.subprocess.Process) -> None:
        """停止要求時にCLIとその子プロセスを終了する。"""
        if os.name == "nt":
            taskkill = shutil.which("taskkill.exe")
            if taskkill:
                try:
                    killer = await asyncio.create_subprocess_exec(
                        taskkill,
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await asyncio.wait_for(killer.wait(), timeout=10)
                except (OSError, asyncio.TimeoutError):
                    pass
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()

    @staticmethod
    def _session_key(task_id: str) -> str:
        """Taskごとに推測困難で安定したOpenClaw session keyを作る。"""
        digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:24]
        return f"rlc-{digest}"

    @staticmethod
    def _parse_envelope(stdout: bytes) -> dict[str, Any]:
        """OpenClawのJSON応答を読み取る。"""
        try:
            value = json.loads(stdout.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OpenClawError("OPENCLAW_JSON_INVALID") from error
        if not isinstance(value, dict):
            raise OpenClawError("OPENCLAW_JSON_INVALID")
        return value

    @staticmethod
    def _response_text(envelope: dict[str, Any]) -> str:
        """JSON envelopeから最終的な社員応答本文を取り出す。"""
        payloads = envelope.get("payloads")
        if isinstance(payloads, list):
            texts = [
                item["text"]
                for item in payloads
                if isinstance(item, dict)
                and isinstance(item.get("text"), str)
                and item["text"].strip()
            ]
            if texts:
                return "\n".join(texts)
        for key in ("final", "text", "response", "result"):
            value = envelope.get(key)
            if isinstance(value, str) and value.strip():
                return value
        raise OpenClawError("OPENCLAW_RESPONSE_TEXT_MISSING")

    @staticmethod
    def _metrics(envelope: dict[str, Any], session_key: str) -> AgentMetrics:
        """CLI envelopeからturn数、tool数、session、費用を得る。"""
        meta = envelope.get("meta")
        meta = meta if isinstance(meta, dict) else {}
        agent_meta = meta.get("agentMeta")
        agent_meta = agent_meta if isinstance(agent_meta, dict) else {}
        tool_summary = meta.get("toolSummary")
        tool_summary = tool_summary if isinstance(tool_summary, dict) else {}
        turns = agent_meta.get("assistantTurns", envelope.get("assistantTurns", 1))
        tool_calls = tool_summary.get("calls", envelope.get("toolCalls", 0))
        session_id = (
            meta.get("sessionId")
            or envelope.get("sessionId")
            or agent_meta.get("sessionId")
            or session_key
        )
        cost = agent_meta.get("costUsd", envelope.get("costUsd"))
        try:
            normalized_cost = float(cost) if cost is not None else None
            normalized_turns = int(turns)
            normalized_tool_calls = int(tool_calls)
        except (TypeError, ValueError) as error:
            raise OpenClawError("OPENCLAW_METRICS_INVALID") from error
        if normalized_cost is not None and (
            not math.isfinite(normalized_cost) or normalized_cost < 0
        ):
            raise OpenClawError("OPENCLAW_METRICS_INVALID")
        return AgentMetrics(
            turns=normalized_turns,
            tool_calls=normalized_tool_calls,
            session_id=str(session_id),
            cost_usd=normalized_cost,
        )


class OpenClawWorkerAgent:
    """既存engineer社員をWorker契約へ適合させる。"""

    agent_id = "engineer"  # RLC Workerに使う既存社員

    def __init__(self, client: OpenClawClient, project_root: Path) -> None:
        """OpenClaw呼び出し元と作業対象リポジトリを設定する。"""
        self.client = client
        self.project_root = project_root.resolve()

    async def create_plan(self, task: Task) -> AgentResult[Plan]:
        """Baselineに限定したPlan作成をengineerへ依頼する。"""
        prompt = (
            "以下のTaskについて、実装前のPlanだけを作成してください。\n"
            f"作業対象リポジトリ: {self.project_root}\n"
            f"Goal:\n{task.goal}\n"
            f"Baseline Requirements:\n{self._baseline_text(task)}\n"
            "PlanではBaselineを追加・削除・言い換えず、各要件を満たす作業手順を示してください。"
            "この呼び出しではファイルを変更しないでください。"
        )
        try:
            result = await self.client.ask(self.agent_id, task, prompt)
        except OpenClawError as error:
            raise WorkerError(str(error)) from error
        return AgentResult(Plan(result.value), result.metrics)

    async def execute(self, task: Task, plan: Plan) -> AgentResult[ExecutionResult]:
        """承認済みPlanに沿ってengineerへ実装を依頼する。"""
        prompt = (
            "以下のTaskについて、レビュー済みPlanを実行してください。\n"
            f"作業対象リポジトリ: {self.project_root}\n"
            f"Goal:\n{task.goal}\n"
            f"Baseline Requirements:\n{self._baseline_text(task)}\n"
            f"承認済みPlan:\n{plan.content}\n"
            "Baseline外の変更を追加せず、Planの範囲で作業してください。\n"
            "実際に変更したファイルを確認し、漏れなく相対パスで列挙してください。"
            "応答はコードフェンスを付けず、次のJSONだけを返してください: "
            '{"summary":"実施内容","changed_files":["変更した相対パス"]}'
        )
        try:
            result = await self.client.ask(self.agent_id, task, prompt)
        except OpenClawError as error:
            raise WorkerError(str(error)) from error
        try:
            payload = json.loads(result.value)
            summary = payload["summary"]
            changed_files = payload["changed_files"]
            if (
                not isinstance(summary, str)
                or not isinstance(changed_files, list)
                or any(not isinstance(path, str) for path in changed_files)
            ):
                raise ValueError
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise WorkerError(
                "WORKER_EXECUTION_OUTPUT_INVALID", result.metrics
            ) from error
        return AgentResult(ExecutionResult(summary, tuple(changed_files)), result.metrics)

    @staticmethod
    def _baseline_text(task: Task) -> str:
        """固定Baseline Requirementsを入力順のまま文字列化する。"""
        return "\n".join(
            f"{item.requirement_id}: {item.text}"
            for item in task.baseline_requirements
        )


class OpenClawReviewerAgent:
    """既存reviewer社員をReviewer契約へ適合させる。"""

    agent_id = "reviewer"  # RLC Reviewerに使う既存社員

    def __init__(self, client: OpenClawClient, project_root: Path) -> None:
        """OpenClaw呼び出し元とレビュー対象リポジトリを設定する。"""
        self.client = client
        self.project_root = project_root.resolve()

    async def review_plan(
        self, task: Task, plan: Plan, prompt: str
    ) -> AgentResult[ReviewResult]:
        """PlanをBaselineと固定Review Scopeに照らして確認する。"""
        request = (
            f"Review target repository: {self.project_root}\n"
            f"{prompt}\n\nReview target content:\n{plan.content}\n\n"
            f"{self._json_contract()}"
        )
        return await self._review(task, request)

    async def review_result(
        self, task: Task, plan: Plan, result: ExecutionResult, prompt: str
    ) -> AgentResult[ReviewResult]:
        """実装結果をBaselineと固定Review Scopeに照らして確認する。"""
        request = (
            f"Review target repository: {self.project_root}\n"
            f"{prompt}\n\nApproved plan:\n{plan.content}\n\n"
            f"Execution result:\n{result.content}\n"
            f"Changed files:\n{json.dumps(result.changed_files, ensure_ascii=False)}\n\n"
            "Review the actual changes in the target repository and report only "
            "Baseline Requirements issues.\n"
            f"{self._json_contract()}"
        )
        return await self._review(task, request)

    async def _review(self, task: Task, prompt: str) -> AgentResult[ReviewResult]:
        """reviewerを呼び出し、JSON出力をReviewResultへ変換する。"""
        try:
            response = await self.client.ask(self.agent_id, task, prompt)
        except OpenClawError as error:
            raise ReviewerError(str(error)) from error
        try:
            payload = self._parse_json(response.value)
            issues = tuple(
                ReviewIssue(
                    number=issue["number"],
                    severity=issue["severity"],
                    baseline_requirement_ids=tuple(
                        issue["baseline_requirement_ids"]
                    ),
                    category=issue["category"],
                    problem=issue["problem"],
                    evidence=tuple(issue["evidence"]),
                    required_action=issue["required_action"],
                )
                for issue in payload["issues"]
            )
            review = ReviewResult(
                summary=payload["summary"],
                confidence=payload["confidence"],
                issues=issues,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ReviewerError("REVIEW_OUTPUT_INVALID", response.metrics) from error
        return AgentResult(review, response.metrics)

    @staticmethod
    def _parse_json(value: str) -> dict[str, Any]:
        """Review応答をJSON objectとして読み取る。"""
        normalized = value.strip()
        fence = chr(96) * 3
        if normalized.startswith(fence) and normalized.endswith(fence):
            lines = normalized.splitlines()
            normalized = "\n".join(lines[1:-1]).strip()
        parsed = json.loads(normalized)
        if not isinstance(parsed, dict):
            raise ValueError("Review JSONはobjectである必要があります")
        return parsed

    @staticmethod
    def _json_contract() -> str:
        """Reviewerに要求する機械処理可能なJSON形式を返す。"""
        return (
            "ReviewResultを次の形式のJSON objectだけで返してください。"
            "issuesが空なら高・中の問題はありません。各IssueはBaseline Requirement IDだけを参照し、"
            "要件違反でない改善や将来要件は含めないでください。\n"
            '{"summary":"判定要約","confidence":0.9,"issues":['
            '{"number":1,"severity":"HIGH|MEDIUM|LOW",'
            '"baseline_requirement_ids":["BR-001"],'
            '"category":"REQUIREMENT|DESIGN|IMPLEMENTATION|TEST|SECURITY|PERFORMANCE|OPERABILITY|OTHER",'
            '"problem":"問題","evidence":["根拠"],"required_action":"要件を満たす最小限の対応"}]}'
        )
