"""
http.py — FastAPI HTTP 适配器
=============================================================

【这个模块做什么】
将 AgentRuntime 包装为 RESTful HTTP API：
- POST /v1/runs: 提交运行
- GET /v1/runs/{id}: 查询运行状态
- POST /v1/runs/{id}/cancel: 取消运行
- GET /v1/runs/{id}/events: SSE 事件流

【设计亮点】
- 延迟导入: FastAPI 是可选依赖，未安装时不影响 CLI
- SSE 流式传输: 实时推送运行事件给客户端
- Pydantic 验证: 请求参数自动校验
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from mewcode.runtime.service import AgentRuntime


class RunRequest(BaseModel):
    """运行请求参数"""
    task: str = Field(min_length=1)  # 任务描述
    session_id: str = ""  # 会话 ID
    max_attempts: int = Field(default=1, ge=1, le=5)  # 最大重试次数 (1-5)
    timeout_seconds: float | None = Field(default=None, gt=0)  # 超时时间
    metadata: dict[str, Any] = Field(default_factory=dict)  # 扩展元数据


def create_app(runtime: AgentRuntime):
    """
    创建 FastAPI 应用。
    
    FastAPI 延迟导入，未安装时抛出明确错误提示。
    安装方式: pip install mewcode[server]
    """
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import StreamingResponse
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "FastAPI is optional. Install with `pip install mewcode[server]`."
        ) from exc

    app = FastAPI(title="MewCode Agent Runtime", version="0.2.0")

    @app.post("/v1/runs", status_code=202)
    async def submit_run(request: RunRequest):
        """提交新的 Agent 运行"""
        try:
            run = runtime.submit(
                request.task,
                session_id=request.session_id,
                max_attempts=request.max_attempts,
                timeout_seconds=request.timeout_seconds,
                metadata=request.metadata,
            )
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return run.to_dict()

    @app.get("/v1/runs/{run_id}")
    async def get_run(run_id: str):
        """查询运行状态"""
        run = runtime.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run.to_dict()

    @app.post("/v1/runs/{run_id}/cancel")
    async def cancel_run(run_id: str):
        """取消运行"""
        if runtime.get(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {"run_id": run_id, "cancelled": runtime.cancel(run_id)}

    @app.get("/v1/runs/{run_id}/events")
    async def stream_events(run_id: str, after: int = 0):
        """
        SSE 事件流。
        
        先回放已持久化的事件，然后实时跟随新事件。
        客户端可通过 after 参数指定从哪个序号开始。
        """
        if runtime.get(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")

        async def event_stream():
            async for event in runtime.subscribe(run_id, after=after):
                payload = json.dumps(event.to_dict(), ensure_ascii=False)
                # SSE 格式: id + event + data
                yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {payload}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    return app
