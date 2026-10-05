"""
http.py — FastAPI HTTP 适配器
=============================================================

【这个模块做什么】
将 AgentRuntime 包装为 RESTful HTTP API：
- GET /: 轻量 Web 控制台
- POST /v1/runs: 提交运行
- GET /v1/runs: 查询运行列表
- GET /v1/runs/{id}: 查询运行状态
- POST /v1/runs/{id}/cancel: 取消运行
- POST /v1/runs/{id}/retry: 重试失败或取消的运行
- GET /v1/runs/{id}/events: SSE 事件流

【设计亮点】
- 延迟导入: FastAPI 是可选依赖，未安装时不影响 CLI
- SSE 流式传输: 实时推送运行事件给客户端
- Pydantic 验证: 请求参数自动校验
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from mewcode.config import ProviderConfig
from mewcode.runtime.service import AgentRuntime


PROVIDER_CATALOG = [
    {
        "id": "openai",
        "label": "OpenAI",
        "protocol": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "env_var": "OPENAI_API_KEY",
        "kind": "官方",
    },
    {
        "id": "anthropic",
        "label": "Anthropic",
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-6",
        "env_var": "ANTHROPIC_API_KEY",
        "kind": "官方",
    },
    {
        "id": "bailian",
        "label": "阿里云百炼",
        "protocol": "openai-compat",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.7-flash-2026-07-15",
        "env_var": "DASHSCOPE_API_KEY",
        "kind": "官方兼容",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "protocol": "openai-compat",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "env_var": "DEEPSEEK_API_KEY",
        "kind": "官方兼容",
    },
    {
        "id": "moonshot",
        "label": "Moonshot / Kimi",
        "protocol": "openai-compat",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "kimi-k2.5",
        "env_var": "MOONSHOT_API_KEY",
        "kind": "官方兼容",
    },
    {
        "id": "zhipu",
        "label": "智谱 GLM",
        "protocol": "openai-compat",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4.5-flash",
        "env_var": "ZHIPUAI_API_KEY",
        "kind": "官方兼容",
    },
    {
        "id": "siliconflow",
        "label": "SiliconFlow",
        "protocol": "openai-compat",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V3",
        "env_var": "SILICONFLOW_API_KEY",
        "kind": "第三方聚合",
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "protocol": "openai-compat",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4.1-mini",
        "env_var": "OPENROUTER_API_KEY",
        "kind": "第三方聚合",
    },
    {
        "id": "custom",
        "label": "自定义中转站",
        "protocol": "openai-compat",
        "base_url": "http://localhost:3000/v1",
        "model": "your-model",
        "env_var": "OPENAI_API_KEY",
        "kind": "OneAPI / New API / 其他兼容站",
    },
]


def _provider_public(provider: ProviderConfig, active: bool = False) -> dict[str, Any]:
    """Return provider metadata without ever exposing an API key."""
    return {
        "name": provider.name,
        "protocol": provider.protocol,
        "base_url": provider.base_url,
        "model": provider.model,
        "thinking": provider.thinking,
        "max_output_tokens": provider.max_output_tokens,
        "api_key_configured": bool(provider.resolve_api_key()),
        "active": active,
    }


def _persist_provider_profiles(runtime: AgentRuntime) -> None:
    """Persist profiles to ignored project-local config without other settings."""
    root = Path(getattr(runtime, "config_root", Path.cwd()))
    config_dir = root / ".mewcode"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "config.local.yaml"
    try:
        import yaml

        existing = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(existing, dict):
            existing = {}
        existing["providers"] = [
            {
                "name": provider.name,
                "protocol": provider.protocol,
                "base_url": provider.base_url,
                "model": provider.model,
                "api_key": provider.api_key,
                "thinking": provider.thinking,
                "max_output_tokens": provider.max_output_tokens,
            }
            for provider in getattr(runtime, "provider_configs", {}).values()
        ]
        path.write_text(
            yaml.safe_dump(existing, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    except (OSError, ValueError, TypeError):
        # The in-memory profile remains usable when local persistence fails.
        return


class RunRequest(BaseModel):
    """运行请求参数"""
    task: str = Field(min_length=1)  # 任务描述
    session_id: str = ""  # 会话 ID
    max_attempts: int = Field(default=1, ge=1, le=5)  # 最大重试次数 (1-5)
    timeout_seconds: float | None = Field(default=None, gt=0)  # 超时时间
    metadata: dict[str, Any] = Field(default_factory=dict)  # 扩展元数据


class ProviderRequest(BaseModel):
    """Provider profile submitted by the local settings panel."""

    name: str = Field(min_length=1, max_length=64)
    protocol: str = Field(default="openai-compat", min_length=3, max_length=32)
    base_url: str = Field(min_length=8, max_length=512)
    model: str = Field(min_length=1, max_length=160)
    api_key: str = Field(default="", max_length=512)
    thinking: bool = False
    max_output_tokens: int = Field(default=0, ge=0, le=200000)
    make_active: bool = False
    persist: bool = True


def create_app(runtime: AgentRuntime):
    """
    创建 FastAPI 应用。
    
    FastAPI 延迟导入，未安装时抛出明确错误提示。
    安装方式: pip install mewcode[server]
    """
    try:
        from fastapi import FastAPI, HTTPException, Query
        from fastapi.responses import HTMLResponse, StreamingResponse
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "FastAPI is optional. Install with `pip install mewcode[server]`."
        ) from exc

    app = FastAPI(title="MewCode Agent Runtime", version="0.2.0")

    @app.get("/health")
    async def health():
        """Return a small liveness payload for the console and local scripts."""
        runs = runtime.list_runs()
        return {
            "status": "ok",
            "service": "mewcode-runtime",
            "runs": len(runs),
        }

    @app.get("/v1/providers")
    async def list_providers():
        """List configured model profiles and safe preset metadata."""
        profiles = getattr(runtime, "provider_configs", {})
        active = getattr(runtime, "provider_state", {}).get("active", "")
        return {
            "providers": [
                _provider_public(provider, provider.name == active)
                for provider in profiles.values()
            ],
            "catalog": PROVIDER_CATALOG,
            "active": active,
        }

    @app.post("/v1/providers")
    async def configure_provider(request: ProviderRequest):
        """Add or replace a local provider profile for future runs."""
        if request.protocol not in {"anthropic", "openai", "openai-compat"}:
            raise HTTPException(
                status_code=422,
                detail="protocol must be anthropic, openai, or openai-compat",
            )
        profiles = getattr(runtime, "provider_configs", None)
        state = getattr(runtime, "provider_state", None)
        if profiles is None or state is None:
            raise HTTPException(status_code=503, detail="provider management unavailable")
        previous = profiles.get(request.name)
        api_key = request.api_key or (previous.api_key if previous else "")
        profiles[request.name] = ProviderConfig(
            name=request.name,
            protocol=request.protocol,
            base_url=request.base_url.rstrip("/"),
            model=request.model,
            api_key=api_key,
            thinking=request.thinking,
            max_output_tokens=request.max_output_tokens,
        )
        if request.make_active or not state.get("active"):
            state["active"] = request.name
        if request.persist:
            _persist_provider_profiles(runtime)
        return _provider_public(profiles[request.name], profiles[request.name].name == state["active"])

    @app.post("/v1/providers/{provider_name}/activate")
    async def activate_provider(provider_name: str):
        profiles = getattr(runtime, "provider_configs", {})
        state = getattr(runtime, "provider_state", None)
        if state is None or provider_name not in profiles:
            raise HTTPException(status_code=404, detail="provider not found")
        state["active"] = provider_name
        return _provider_public(profiles[provider_name], True)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def console():
        """Serve the dependency-free browser console."""
        return HTMLResponse(CONSOLE_HTML)

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

    @app.get("/v1/runs")
    async def list_runs(
        status: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ):
        """List recent runs for the console and API clients."""
        runs = runtime.list_runs()
        if status:
            runs = [run for run in runs if run.status.value == status]
        runs.sort(key=lambda run: run.created_at, reverse=True)
        return {"runs": [run.to_dict() for run in runs[:limit]]}

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

    @app.post("/v1/runs/{run_id}/retry", status_code=202)
    async def retry_run(run_id: str):
        """Retry a finished run as a new run, preserving its session context."""
        previous = runtime.get(run_id)
        if previous is None:
            raise HTTPException(status_code=404, detail="run not found")
        if previous.status.value not in {"failed", "cancelled"}:
            raise HTTPException(
                status_code=409,
                detail="only failed or cancelled runs can be retried",
            )
        metadata = dict(previous.metadata)
        metadata["retry_of"] = previous.id
        try:
            run = runtime.submit(
                previous.task,
                session_id=previous.session_id,
                max_attempts=previous.max_attempts,
                timeout_seconds=previous.timeout_seconds,
                metadata=metadata,
            )
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return run.to_dict()

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


# Kept inline on purpose: the server remains a single-command, single-package
# install and does not need a frontend build step. The UI talks only to the
# public REST/SSE endpoints above, so it is also easy to replace later.
CONSOLE_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#f5f5f7"><title>MewCode · 工作台</title>
<style>
:root{color-scheme:light;--bg:#f5f5f7;--sidebar:#f8f8fae8;--card:#ffffffd9;--solid:#fff;--ink:#1d1d1f;--muted:#86868b;--line:#d2d2d7;--line-soft:#e7e7eb;--blue:#0071e3;--blue-soft:#e8f2ff;--green:#198754;--orange:#bf7000;--red:#d93852;--purple:#7454d8;--shadow:0 15px 42px #1d1d1f0f}*{box-sizing:border-box}body{margin:0;min-width:900px;background:radial-gradient(circle at 80% -15%,#e5edff,transparent 34%),var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","Segoe UI",sans-serif;letter-spacing:-.01em}button,input,textarea,select{font:inherit}button{cursor:pointer;border:0}.app{display:grid;grid-template-columns:248px minmax(0,1fr);min-height:100vh}.sidebar{background:var(--sidebar);border-right:1px solid #0000000d;padding:28px 16px;backdrop-filter:blur(24px);display:flex;flex-direction:column}.brand{display:flex;align-items:center;gap:10px;padding:0 11px 32px;font-size:18px;font-weight:720;letter-spacing:-.04em}.mark{width:32px;height:32px;border-radius:10px;display:grid;place-items:center;background:linear-gradient(140deg,#262626,#757575);color:#fff;box-shadow:0 5px 14px #0002}.mark svg{width:20px}.brand small{display:block;color:var(--muted);font-size:10px;font-weight:500;letter-spacing:0;margin-top:2px}.section-label{padding:0 11px 8px;color:var(--muted);font-size:11px;font-weight:650}.nav{display:grid;gap:3px}.nav button{display:flex;align-items:center;gap:11px;width:100%;padding:10px 11px;border-radius:9px;background:transparent;color:#626267;text-align:left}.nav button:hover,.nav button.active{background:#00000008;color:var(--ink)}.nav button.active{font-weight:650}.nav svg{width:17px;height:17px;stroke:currentColor;fill:none;stroke-width:1.7}.side-provider{margin-top:auto;border-top:1px solid var(--line-soft);padding:17px 10px 0}.side-provider button{display:flex;align-items:center;gap:8px;padding:0;background:transparent;color:var(--ink);text-align:left}.provider-dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px #19875418}.side-provider small{display:block;color:var(--muted);font-size:11px;margin-top:5px;padding-left:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.main{min-width:0;padding:30px clamp(24px,4vw,60px) 50px}.topbar{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;margin-bottom:25px}.eyebrow{color:var(--blue);font-size:11px;font-weight:750;letter-spacing:.12em;text-transform:uppercase}.topbar h1{font-size:29px;letter-spacing:-.055em;margin:5px 0 4px}.topbar p{color:var(--muted);margin:0}.top-actions{display:flex;align-items:center;gap:9px}.health{border:1px solid var(--line);border-radius:20px;padding:7px 11px;color:var(--muted);font-size:12px;background:var(--card)}.health .dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--green);margin-right:6px}.icon{display:grid;place-items:center;width:34px;height:34px;border:1px solid var(--line);border-radius:50%;background:var(--solid);color:var(--ink)}.icon:hover,.text-btn:hover{border-color:var(--blue);color:var(--blue)}.icon svg{width:16px}.layout{display:grid;grid-template-columns:minmax(0,1fr) 310px;gap:17px}.card{border:1px solid #0000000a;border-radius:17px;background:var(--card);box-shadow:var(--shadow);backdrop-filter:blur(24px);overflow:hidden}.chat-card{min-height:685px;display:flex;flex-direction:column}.card-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:19px 21px;border-bottom:1px solid var(--line-soft)}.card-head h2{font-size:15px;margin:0;letter-spacing:-.025em}.muted{color:var(--muted)}.text-btn{border:1px solid transparent;background:transparent;color:var(--blue);padding:6px 8px;border-radius:8px}.chat{display:flex;flex-direction:column;gap:13px;flex:1;overflow:auto;padding:24px 22px}.chat-empty{text-align:center;color:var(--muted);padding:80px 20px}.bubble{max-width:86%;padding:12px 14px;border-radius:15px;white-space:pre-wrap;word-break:break-word}.bubble.user{align-self:flex-end;background:#0071e3;color:#fff;border-bottom-right-radius:5px}.bubble.assistant{align-self:flex-start;background:#f0f0f2;border-bottom-left-radius:5px}.bubble.error{color:var(--red);background:#fff0f2}.bubble-label{font-size:10px;font-weight:700;color:#ffffffb8;margin-bottom:5px;text-transform:uppercase;letter-spacing:.08em}.assistant .bubble-label{color:var(--muted)}.chat-actions{display:flex;flex-direction:column;gap:7px;margin-left:10px}.action{border-left:2px solid var(--blue);padding:8px 11px;background:var(--blue-soft);border-radius:8px;color:#385074;font-size:12px}.action.result{border-left-color:#c4c4c8;background:#f6f6f8;color:#727277}.action b{display:block;color:var(--ink);font-size:12px;margin-bottom:3px}.action pre{max-height:110px;margin:0;white-space:pre-wrap;word-break:break-word;color:inherit;font:11px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace}.composer{border-top:1px solid var(--line-soft);padding:15px 18px 17px}.composer-box{display:flex;align-items:flex-end;gap:10px;border:1px solid var(--line);border-radius:14px;padding:9px;background:var(--solid);transition:.18s}.composer-box:focus-within{border-color:var(--blue);box-shadow:0 0 0 3px #0071e31a}.composer textarea{flex:1;min-height:54px;max-height:150px;border:0;outline:0;resize:vertical;color:var(--ink);background:transparent;padding:3px 5px}.send{width:34px;height:34px;border-radius:50%;background:var(--blue);color:#fff;display:grid;place-items:center}.send:hover{background:#0077ed;transform:scale(1.03)}.send:disabled{opacity:.45;transform:none}.composer-foot{display:flex;justify-content:space-between;align-items:center;padding:8px 4px 0;color:var(--muted);font-size:11px}.model-pill{display:inline-flex;align-items:center;gap:6px;max-width:260px;border:1px solid var(--line);background:var(--solid);border-radius:20px;padding:7px 10px;color:var(--ink);font-size:12px}.model-pill:hover{border-color:var(--blue)}.model-pill span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.inspector{display:flex;flex-direction:column;gap:15px}.mini-card{padding:18px}.mini-card h3{font-size:13px;margin:0 0 13px}.provider-select{width:100%;padding:10px 11px;border:1px solid var(--line);border-radius:10px;background:var(--solid);color:var(--ink);outline:0}.provider-select:focus{border-color:var(--blue)}.provider-meta{display:flex;justify-content:space-between;gap:8px;margin-top:10px;color:var(--muted);font-size:11px}.key-ok{color:var(--green)}.runs{max-height:365px;overflow:auto}.run{display:block;width:100%;padding:10px 0;border-bottom:1px solid var(--line-soft);background:transparent;text-align:left}.run:last-child{border-bottom:0}.run:hover{color:var(--blue)}.run-title{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:600}.run-meta{display:flex;justify-content:space-between;color:var(--muted);font-size:11px;margin-top:4px}.badge{display:inline-flex;align-items:center;gap:5px;font-size:11px}.badge:before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}.running,.pending{color:var(--orange)}.completed{color:var(--green)}.failed,.cancelled{color:var(--red)}.activity{max-height:300px;overflow:auto}.event{padding:9px 0;border-bottom:1px solid var(--line-soft);font-size:11px}.event:last-child{border:0}.event-top{display:flex;justify-content:space-between;color:var(--muted)}.event-name{color:var(--ink);font-weight:650}.event-detail{margin-top:4px;color:var(--muted);white-space:pre-wrap;word-break:break-word;font:11px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace}.modal{position:fixed;inset:0;z-index:5;display:none;background:#0003;backdrop-filter:blur(9px);align-items:flex-end;justify-content:flex-end}.modal.open{display:flex}.sheet{width:min(570px,100%);height:100%;background:var(--solid);border-left:1px solid var(--line);box-shadow:-18px 0 50px #0002;padding:28px 28px 35px;overflow:auto}.sheet-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:22px}.sheet h2{font-size:23px;letter-spacing:-.045em;margin:0 0 5px}.sheet p{color:var(--muted);font-size:13px;margin:0}.close{width:30px;height:30px;border-radius:50%;background:#00000008;color:var(--muted);font-size:18px}.catalog{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin:12px 0 20px}.catalog button{padding:10px;border:1px solid var(--line);border-radius:10px;background:var(--bg);text-align:left;color:var(--ink)}.catalog button:hover,.catalog button.selected{border-color:var(--blue);background:var(--blue-soft)}.catalog b{display:block;font-size:12px}.catalog small{color:var(--muted);font-size:10px}.field{margin:13px 0}.field label{display:block;color:var(--muted);font-size:11px;font-weight:650;margin-bottom:6px}.field input,.field select{width:100%;padding:10px 11px;border:1px solid var(--line);border-radius:9px;background:var(--solid);color:var(--ink);outline:0}.field input:focus,.field select:focus{border-color:var(--blue);box-shadow:0 0 0 3px #0071e31a}.sheet-actions{display:flex;gap:9px;margin-top:22px}.primary{background:var(--blue);color:#fff;padding:10px 15px;border-radius:10px}.secondary{background:var(--bg);color:var(--ink);padding:10px 15px;border-radius:10px}.toast{position:fixed;z-index:8;left:50%;bottom:28px;transform:translate(-50%,12px);opacity:0;pointer-events:none;background:#1d1d1fee;color:#fff;padding:10px 15px;border-radius:11px;box-shadow:var(--shadow);transition:.2s}.toast.show{opacity:1;transform:translate(-50%,0)}@media(max-width:1120px){.app{grid-template-columns:80px 1fr}.sidebar{padding:25px 10px}.brand{padding:0 10px 32px}.brand-copy,.section-label,.nav span,.side-provider{display:none}.nav button{justify-content:center}.layout{grid-template-columns:1fr 270px}}@media(max-width:760px){body{min-width:320px}.app{display:block}.sidebar{display:none}.main{padding:20px 13px}.topbar{display:block}.top-actions{margin-top:15px}.layout{display:block}.inspector{margin-top:15px}.chat-card{min-height:620px}.bubble{max-width:94%}.modal{align-items:stretch}.sheet{width:100%;height:100%;border:0}}
.dark{color-scheme:dark;--bg:#161617;--sidebar:#1c1c1ee8;--card:#242426e6;--solid:#2c2c2ee8;--ink:#f5f5f7;--muted:#98989d;--line:#4a4a4f;--line-soft:#ffffff13;--blue:#2997ff;--blue-soft:#153451;--shadow:0 18px 45px #0003}.dark .bubble.assistant{background:#303034}.dark .action{color:#bbd8fa}.dark .action.result{background:#303034;color:#b9b9bf}.dark .action b{color:var(--ink)}.dark .side-provider small{color:var(--muted)}
</style></head><body><div class="app"><aside class="sidebar"><div class="brand"><div class="mark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M5 14V8l3-3 4 2 4-2 3 3v6a7 7 0 0 1-14 0Z"/><path d="M8 4.5 9.5 7M16 4.5 14.5 7M9 14h.01M15 14h.01M9.5 17c1.5 1 3.5 1 5 0"/></svg></div><div class="brand-copy">MewCode<small>AI coding workspace</small></div></div><div class="section-label">WORKSPACE</div><nav class="nav"><button class="active" type="button" onclick="showView('chat')"><svg viewBox="0 0 24 24"><path d="M5 5h14v11H8l-3 3V5Z"/><path d="M8 9h8M8 12h5"/></svg><span>对话</span></button><button type="button" onclick="focusRuns()"><svg viewBox="0 0 24 24"><path d="M5 6h14M5 12h14M5 18h9"/></svg><span>运行记录</span></button><button type="button" onclick="openProviderSheet()"><svg viewBox="0 0 24 24"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/><circle cx="12" cy="12" r="4"/></svg><span>模型与连接</span></button></nav><div class="side-provider"><button type="button" onclick="openProviderSheet()"><i class="provider-dot"></i><span id="side-provider-name">加载模型中</span></button><small id="side-provider-model">—</small></div></aside><main class="main"><header class="topbar"><div><div class="eyebrow">MewCode workspace</div><h1>运行概览</h1><p>与模型协作，查看每一步操作，并保持工作上下文。</p></div><span id="stat-total" style="display:none">0</span><div class="top-actions"><span class="health" id="health">检查服务中…</span><button class="icon" title="切换外观" onclick="toggleTheme()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M20 15.5A8.5 8.5 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5Z"/></svg></button><button class="icon" title="刷新" id="refresh"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M20 11a8 8 0 0 0-15-3M4 5v4h4M4 13a8 8 0 0 0 15 3M20 19v-4h-4"/></svg></button></div></header><div class="layout"><section class="card chat-card" id="chat-view"><div class="card-head"><div><h2>与 LLM 对话</h2><span class="muted" id="session-label">新会话</span></div><div><button class="text-btn" type="button" onclick="newSession()">新会话</button><button class="text-btn" type="button" onclick="openProviderSheet()">模型设置</button></div></div><div class="chat" id="chat"><div class="chat-empty">从一句问题开始。模型的回答、工具调用和结果会按时间顺序显示在这里。</div></div><form class="composer" id="submit-form"><div class="composer-box"><textarea id="task" required placeholder="给 MewCode 一个任务…" aria-label="消息"></textarea><button class="send" id="send" type="submit" aria-label="发送"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m5 12 14-7-3 14-4-5-7-2Z"/><path d="M12 14 19 5"/></svg></button></div><div class="composer-foot"><button class="model-pill" id="model-pill" type="button" onclick="openProviderSheet()"><i class="provider-dot"></i><span>加载模型中</span></button><span id="submit-message">Enter 发送 · Shift+Enter 换行</span></div></form></section><aside class="inspector"><section class="card mini-card"><h3>当前模型</h3><select class="provider-select" id="provider-select" onchange="activateProvider(this.value)"><option>加载中…</option></select><div class="provider-meta"><span id="provider-protocol">—</span><span id="provider-key" class="key-ok">—</span></div></section><section class="card mini-card" id="runs-panel"><h3>最近运行 <span class="muted" id="run-count"></span></h3><input id="run-search" class="provider-select" style="margin-bottom:10px" placeholder="搜索任务或运行 ID"><div class="runs" id="runs"><div class="muted">正在加载…</div></div><button class="text-btn" type="button" onclick="focusRuns()">查看全部运行</button></section><section class="card mini-card"><div style="display:flex;justify-content:space-between;align-items:center"><h3>活动</h3><span class="muted" id="event-status">未连接</span></div><div class="activity" id="events"><div class="muted">选择一个运行查看活动。</div></div></section></aside></div></main></div><div class="modal" id="provider-modal" onclick="if(event.target===this)closeProviderSheet()"><section class="sheet"><div class="sheet-head"><div><h2>模型与连接</h2><p>选择供应商，或配置一个 OpenAI-compatible 中转站。</p></div><button class="close" type="button" onclick="closeProviderSheet()">×</button></div><h3 style="font-size:13px">快速选择</h3><div class="catalog" id="catalog"></div><form id="provider-form"><div class="field"><label>显示名称</label><input id="provider-name" required placeholder="例如：我的百炼"></div><div class="field"><label>协议</label><select id="provider-protocol"><option value="openai-compat">OpenAI-compatible</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option></select></div><div class="field"><label>Base URL</label><input id="provider-base" required placeholder="https://api.example.com/v1"></div><div class="field"><label>模型名称</label><input id="provider-model" required placeholder="qwen3.7-flash-2026-07-15"></div><div class="field"><label>API Key 或环境变量占位符</label><input id="provider-key-input" type="password" placeholder="${DASHSCOPE_API_KEY} 或直接输入密钥"><small class="muted">列表只显示是否配置，不会回显密钥；直接输入的密钥只保存在本机 ignored 配置。</small></div><div class="sheet-actions"><button class="primary" type="submit">保存并使用</button><button class="secondary" type="button" onclick="closeProviderSheet()">取消</button></div></form></section></div><div class="toast" id="toast"></div><script>
const $=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),short=t=>t?new Date(t*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):'-',newId=()=>crypto.randomUUID?crypto.randomUUID():`web-${Date.now()}`;const state={runs:[],selected:null,providers:[],active:'',session:newId(),source:null,lastEvent:0,eventCount:0,filter:'all',query:''};
async function api(path,opt){const r=await fetch(path,opt),d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||d.error?.message||r.statusText);return d}function toast(msg){const t=$('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2800)}function toggleTheme(){document.documentElement.classList.toggle('dark');localStorage.setItem('mew-theme',document.documentElement.classList.contains('dark')?'dark':'light')}if(localStorage.getItem('mew-theme')==='dark')document.documentElement.classList.add('dark');
function openProviderSheet(){renderCatalog();$('provider-modal').classList.add('open')}function closeProviderSheet(){$('provider-modal').classList.remove('open')}function fillProvider(p){$('provider-name').value=p.label||p.name||'';$('provider-protocol').value=p.protocol||'openai-compat';$('provider-base').value=p.base_url||'';$('provider-model').value=p.model||'';$('provider-key-input').value='';document.querySelectorAll('.catalog button').forEach(b=>b.classList.toggle('selected',b.dataset.id===p.id))}function renderCatalog(){const catalog=state.catalog||[];$('catalog').innerHTML=catalog.map(p=>`<button type="button" data-id="${esc(p.id)}" onclick='fillProvider(${JSON.stringify(p).replace(/'/g,"&#39;")})'><b>${esc(p.label)}</b><small>${esc(p.kind)} · ${esc(p.env_var)}</small></button>`).join('')}async function loadProviders(){try{const d=await api('/v1/providers');state.providers=d.providers||[];state.catalog=d.catalog||[];state.active=d.active||state.providers[0]?.name||'';renderProviders();renderCatalog()}catch(e){toast(e.message)}}function renderProviders(){const select=$('provider-select');select.innerHTML=state.providers.length?state.providers.map(p=>`<option value="${esc(p.name)}" ${p.name===state.active?'selected':''}>${esc(p.name)} · ${esc(p.model)}</option>`).join(''):'<option>未配置模型</option>';const p=state.providers.find(x=>x.name===state.active);if(p){$('provider-protocol').textContent=`${p.protocol} · ${p.base_url}`;$('provider-key').textContent=p.api_key_configured?'密钥已配置':'未配置密钥';$('provider-key').className=p.api_key_configured?'key-ok':'';$('side-provider-name').textContent=p.name;$('side-provider-model').textContent=p.model;document.querySelector('#model-pill span').textContent=`${p.name} · ${p.model}`;$('session-label').textContent=`会话 ${state.session.slice(0,8)}`}}async function activateProvider(name){try{const p=await api(`/v1/providers/${encodeURIComponent(name)}/activate`,{method:'POST'});state.active=p.name;renderProviders();toast(`已切换到 ${p.name}`)}catch(e){toast(e.message)}}
function renderRuns(){const q=state.query.trim().toLowerCase();const runs=state.runs.filter(r=>!q||`${r.id} ${r.task}`.toLowerCase().includes(q)).slice(0,8);$('run-count').textContent=`${runs.length}/${state.runs.length}`;$('stat-total').textContent=state.runs.length;$('runs').innerHTML=runs.length?runs.map(r=>`<button class="run" data-id="${esc(r.id)}"><div class="run-title">${esc(r.task)}</div><div class="run-meta"><span class="badge ${esc(r.status)}">${esc({pending:'排队中',running:'运行中',completed:'已完成',failed:'失败',cancelled:'已取消'}[r.status]||r.status)}</span><span>${esc(short(r.created_at))}</span></div></button>`).join(''):'<div class="muted">暂无运行记录</div>';document.querySelectorAll('.run').forEach(x=>x.onclick=()=>selectRun(x.dataset.id))}async function refresh(){try{const d=await api('/v1/runs?limit=100');state.runs=d.runs||[];renderRuns()}catch(e){toast(e.message)}}
function renderChat(run){if(!run){$('chat').innerHTML='<div class="chat-empty">从一句问题开始。模型的回答、工具调用和结果会按时间顺序显示在这里。</div>';return}$('chat').innerHTML=`<div class="bubble user"><div class="bubble-label">你</div>${esc(run.task)}</div><div class="bubble assistant" id="assistant"><div class="bubble-label">MewCode · ${esc(state.active)}</div><span>${esc(run.result||run.error||'正在思考…')}</span></div><div class="chat-actions" id="chat-actions"></div>`}function appendEvent(e){state.lastEvent=Math.max(state.lastEvent,Number(e.sequence||0));state.eventCount++;const box=$('events');if(state.eventCount===1)box.innerHTML='';box.insertAdjacentHTML('beforeend',`<div class="event"><div class="event-top"><span class="event-name">${esc(e.event_type)}</span><span>${esc(short(e.timestamp))}</span></div><div class="event-detail">${esc(JSON.stringify(e.payload||{},null,2))}</div></div>`);box.scrollTop=box.scrollHeight}function appendChatEvent(e){const a=$('assistant'),actions=$('chat-actions');if(!a||!actions)return;if(e.event_type==='stream_text')a.querySelector('span').textContent=e.payload?.text||'';if(e.event_type==='tool_use'||e.event_type==='tool_result'){const done=e.event_type==='tool_result',bad=e.payload?.is_error;actions.insertAdjacentHTML('beforeend',`<div class="action ${done?'result':''}"><b>${done?(bad?'操作失败':'操作完成'):'正在操作'} · ${esc(e.payload?.toolName||'tool')}</b><pre>${esc(JSON.stringify(done?e.payload?.output:e.payload?.args||{},null,2))}</pre></div>`)}if(e.event_type==='run_failed'){a.classList.add('error');a.querySelector('span').textContent=e.payload?.error||'运行失败'}}function watch(run){if(state.source)state.source.close();state.lastEvent=0;state.eventCount=0;$('events').innerHTML='';$('event-status').textContent='连接中…';renderChat(run);const source=state.source=new EventSource(`/v1/runs/${encodeURIComponent(run.id)}/events?after=0`);['run_created','run_started','run_completed','run_failed','run_cancelled','run_timeout','run_retrying','run_recovered','agent_event','stream_text','tool_use','tool_result','usage'].forEach(type=>source.addEventListener(type,e=>{try{const x=JSON.parse(e.data);appendEvent(x);appendChatEvent(x);$('event-status').textContent='实时';refresh()}catch(_){}}));source.onopen=()=>$('event-status').textContent='实时';source.onerror=()=>$('event-status').textContent='连接重试中…'}async function selectRun(id){state.selected=id;try{const r=await api(`/v1/runs/${encodeURIComponent(id)}`);state.session=r.session_id||state.session;watch(r)}catch(e){toast(e.message)}}
function newSession(){if(state.source)state.source.close();state.source=null;state.session=newId();state.selected=null;state.eventCount=0;$('session-label').textContent=`会话 ${state.session.slice(0,8)}`;renderChat(null);$('events').innerHTML='<div class="muted">选择一个运行查看活动。</div>';toast('已创建新会话');$('task').focus()}function focusComposer(){ $('task').focus();$('chat-view').scrollIntoView({behavior:'smooth'})}function focusRuns(){$('runs-panel').scrollIntoView({behavior:'smooth'})}function showView(view){if(view==='chat')focusComposer();else focusRuns()}
$('run-search').oninput=e=>{state.query=e.target.value;renderRuns()};$('submit-form').onsubmit=async e=>{e.preventDefault();const task=$('task').value.trim();if(!task)return;const send=$('send');send.disabled=true;$('submit-message').textContent='正在发送…';try{const run=await api('/v1/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task,session_id:state.session,max_attempts:1,metadata:{provider:state.active}})});$('task').value='';$('submit-message').textContent='Enter 发送 · Shift+Enter 换行';await refresh();await selectRun(run.id)}catch(e){toast(e.message);$('submit-message').textContent=e.message}finally{send.disabled=false}};$('task').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('submit-form').requestSubmit()}});$('refresh').onclick=()=>{refresh();loadProviders()};
$('provider-form').onsubmit=async e=>{e.preventDefault();try{const p=await api('/v1/providers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('provider-name').value.trim(),protocol:$('provider-protocol').value,base_url:$('provider-base').value.trim(),model:$('provider-model').value.trim(),api_key:$('provider-key-input').value,make_active:true,persist:true})});await loadProviders();state.active=p.name;renderProviders();closeProviderSheet();toast(`已保存并使用 ${p.name}`)}catch(e){toast(e.message)}};loadProviders();refresh();api('/health').then(x=>$('health').innerHTML='<span class="dot"></span>服务在线').catch(()=>$('health').textContent='服务检查失败');
</script></body></html>"""
