from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from mewcode.runtime.service import AgentRuntime


class RunRequest(BaseModel):
    task: str = Field(min_length=1)
    session_id: str = ""
    max_attempts: int = Field(default=1, ge=1, le=5)
    timeout_seconds: float | None = Field(default=None, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


def create_app(runtime: AgentRuntime):
    """Create an optional FastAPI adapter around ``AgentRuntime``.

    FastAPI is intentionally imported lazily so the CLI remains lightweight;
    install the ``server`` extra before importing this function.
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
        run = runtime.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run.to_dict()

    @app.post("/v1/runs/{run_id}/cancel")
    async def cancel_run(run_id: str):
        if runtime.get(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {"run_id": run_id, "cancelled": runtime.cancel(run_id)}

    @app.get("/v1/runs/{run_id}/events")
    async def stream_events(run_id: str, after: int = 0):
        if runtime.get(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")

        async def event_stream():
            async for event in runtime.subscribe(run_id, after=after):
                payload = json.dumps(event.to_dict(), ensure_ascii=False)
                yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {payload}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    return app
