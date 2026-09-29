"""SQLite保存付きReview LoopのローカルHTTP APIを提供する。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.core.baseline import BaselineValidationError
from app.core.task_store import TaskAlreadyRunningError, TaskStateConflictError
from app.service import TaskService


class BaselineRequirementInput(BaseModel):
    """APIから受け取る固定Baseline Requirementを表す。"""

    requirement_id: str = Field(pattern=r"^BR-\d{3}$")
    text: str = Field(min_length=1)


class CreateTaskInput(BaseModel):
    """Task登録APIの入力を表す。"""

    goal: str = Field(min_length=1)
    baseline_requirements: list[BaselineRequirementInput] = Field(min_length=1)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """起動時にTaskを復旧し、終了時に実行中Agentを停止する。"""
    service = TaskService(Path(__file__).resolve().parents[2])
    recovered = service.startup()
    application.state.task_service = service
    if recovered:
        print(
            "RLC再起動時に確認待ちへ移したTask: "
            + ", ".join(recovered)
        )
    try:
        yield
    finally:
        await service.shutdown()


def create_app() -> FastAPI:
    """FastAPI applicationを生成する。"""
    application = FastAPI(
        title="AI社員 Review Loop Core",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.get("/health")
    async def health() -> dict[str, str]:
        """APIプロセスの応答状態を返す。"""
        return {"status": "ok"}

    @application.post("/tasks", status_code=status.HTTP_201_CREATED)
    async def create_task(
        body: CreateTaskInput, request: Request
    ) -> dict[str, object]:
        """明示Baseline付きのTaskを登録する。"""
        try:
            task_id = request.app.state.task_service.create_task(
                body.goal,
                [
                    item.model_dump()
                    for item in body.baseline_requirements
                ],
            )
        except BaselineValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error
        return request.app.state.task_service.get(task_id) or {"task_id": task_id}

    @application.get("/tasks")
    async def list_tasks(
        request: Request,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[dict[str, object]]:
        """Task一覧を更新日時の新しい順に返す。"""
        return request.app.state.task_service.list(limit)

    @application.get("/tasks/{task_id}")
    async def get_task(task_id: str, request: Request) -> dict[str, object]:
        """Task、Baseline、最新状態を返す。"""
        result = request.app.state.task_service.get(task_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Taskがありません")
        return result

    @application.get("/tasks/{task_id}/events")
    async def get_task_events(
        task_id: str, request: Request
    ) -> dict[str, object]:
        """Taskの状態遷移、レビュー、Agent利用量を時系列で返す。"""
        events = request.app.state.task_service.get_events(task_id)
        if events is None:
            raise HTTPException(status_code=404, detail="Taskがありません")
        return {"task_id": task_id, "events": events}

    @application.post("/tasks/{task_id}/run", status_code=status.HTTP_202_ACCEPTED)
    async def run_task(task_id: str, request: Request) -> dict[str, object]:
        """TASK_RECEIVEDのTaskを非同期実行する。"""
        service = request.app.state.task_service
        if service.get(task_id) is None:
            raise HTTPException(status_code=404, detail="Taskがありません")
        try:
            attempt_id = await service.start(task_id)
        except TaskAlreadyRunningError as error:
            raise HTTPException(status_code=409, detail="Taskは実行中です") from error
        except TaskStateConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {
            "task_id": task_id,
            "attempt_id": attempt_id,
            "state": "TASK_RECEIVED",
            "running": True,
        }

    @application.post(
        "/tasks/{task_id}/stop", status_code=status.HTTP_202_ACCEPTED
    )
    async def stop_task(task_id: str, request: Request) -> dict[str, object]:
        """実行中Taskを中断し、人の確認が必要な状態へ移す。"""
        service = request.app.state.task_service
        if service.get(task_id) is None:
            raise HTTPException(status_code=404, detail="Taskがありません")
        try:
            await service.stop(task_id)
        except TaskStateConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return service.get(task_id) or {"task_id": task_id}

    @application.post(
        "/tasks/{task_id}/resume", status_code=status.HTTP_202_ACCEPTED
    )
    async def resume_task(task_id: str, request: Request) -> dict[str, object]:
        """Human RequiredのTaskを新しいReview Loop実行として再開する。"""
        service = request.app.state.task_service
        if service.get(task_id) is None:
            raise HTTPException(status_code=404, detail="Taskがありません")
        try:
            attempt_id = await service.start(task_id, resume=True)
        except TaskAlreadyRunningError as error:
            raise HTTPException(status_code=409, detail="Taskは実行中です") from error
        except TaskStateConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {
            "task_id": task_id,
            "attempt_id": attempt_id,
            "state": "TASK_RECEIVED",
            "running": True,
        }

    return application


app = create_app()  # Uvicornが起動するFastAPI application
