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
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#0b1020">
  <title>MewCode 控制台 · Runtime Console</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #080b14;
      --surface: #111827;
      --surface-2: #172033;
      --surface-3: #1d2940;
      --line: #26344d;
      --line-soft: rgba(148,163,184,.16);
      --text: #edf3ff;
      --muted: #8d9ab1;
      --accent: #7c8cff;
      --accent-2: #a78bfa;
      --success: #4ade9a;
      --warning: #f6c768;
      --danger: #ff7188;
      --shadow: 0 18px 50px rgba(0,0,0,.24);
    }
    * { box-sizing: border-box; }
    body { margin:0; min-width:320px; background:radial-gradient(circle at 10% -10%,#1e2a55 0,transparent 34%),var(--bg); color:var(--text); font:14px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
    button,input,textarea,select { font:inherit; }
    button { cursor:pointer; }
    .shell { display:grid; grid-template-columns:250px minmax(0,1fr); min-height:100vh; }
    .sidebar { padding:25px 18px; border-right:1px solid var(--line-soft); background:rgba(8,11,20,.74); backdrop-filter:blur(16px); }
    .brand { display:flex; align-items:center; gap:11px; margin:0 8px 34px; font-weight:750; letter-spacing:.2px; }
    .brand-mark { display:grid; place-items:center; width:36px; height:36px; border-radius:12px; background:linear-gradient(145deg,#788bff,#a679ed); box-shadow:0 10px 22px rgba(124,140,255,.3); }
    .brand-mark svg { width:22px; height:22px; }
    .brand small { display:block; color:var(--muted); font-size:11px; font-weight:500; margin-top:1px; }
    .nav-label { color:#64748b; font-size:11px; font-weight:700; letter-spacing:.11em; margin:0 10px 9px; text-transform:uppercase; }
    .nav { display:grid; gap:5px; }
    .nav button { border:0; background:transparent; color:var(--muted); border-radius:10px; text-align:left; padding:10px 11px; display:flex; align-items:center; gap:10px; }
    .nav button:hover,.nav button.active { background:var(--surface-2); color:var(--text); }
    .nav svg { width:17px; height:17px; opacity:.86; }
    .sidebar-foot { position:fixed; bottom:22px; width:210px; border-top:1px solid var(--line-soft); padding:16px 10px 0; color:var(--muted); font-size:12px; }
    .dot { display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--success); box-shadow:0 0 0 4px rgba(74,222,154,.1); margin-right:7px; }
    .main { min-width:0; padding:28px clamp(18px,4vw,48px) 42px; }
    .topbar { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; margin-bottom:27px; }
    h1,h2,h3,p { margin:0; } h1 { font-size:25px; line-height:1.2; letter-spacing:-.035em; } h2 { font-size:15px; } h3 { font-size:14px; }
    .eyebrow { color:var(--accent-2); font-size:11px; font-weight:750; letter-spacing:.12em; text-transform:uppercase; margin-bottom:8px; }
    .sub { color:var(--muted); margin-top:7px; }
    .top-actions { display:flex; align-items:center; gap:9px; }
    .health { color:var(--muted); font-size:12px; border:1px solid var(--line-soft); background:rgba(17,24,39,.68); padding:8px 11px; border-radius:10px; }
    .icon-btn,.btn { border:1px solid var(--line); color:var(--text); background:var(--surface-2); border-radius:9px; padding:9px 13px; transition:.18s ease; }
    .icon-btn { display:grid; place-items:center; padding:9px; }
    .icon-btn svg { width:17px; height:17px; }
    .btn:hover,.icon-btn:hover { border-color:var(--accent); transform:translateY(-1px); }
    .btn.primary { border-color:#7584ff; background:linear-gradient(135deg,#6979f5,#8d72de); box-shadow:0 8px 20px rgba(106,121,245,.2); }
    .btn.danger { color:#ffd7df; border-color:rgba(255,113,136,.34); background:rgba(137,35,62,.22); }
    .btn.ghost { background:transparent; }
    .btn:disabled { opacity:.45; cursor:not-allowed; transform:none; }
    .stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-bottom:17px; }
    .stat,.panel { border:1px solid var(--line-soft); background:linear-gradient(145deg,rgba(23,32,51,.92),rgba(15,22,37,.92)); box-shadow:var(--shadow); }
    .stat { border-radius:13px; padding:15px 17px; }
    .stat-label { display:flex; justify-content:space-between; color:var(--muted); font-size:12px; }
    .stat-value { margin-top:8px; font-size:25px; font-weight:760; letter-spacing:-.035em; }
    .stat-accent { color:var(--accent); } .stat-success { color:var(--success); } .stat-warning { color:var(--warning); } .stat-danger { color:var(--danger); }
    .workspace { display:grid; grid-template-columns:minmax(300px,.82fr) minmax(420px,1.18fr); gap:15px; align-items:start; }
    .panel { border-radius:15px; overflow:hidden; }
    .panel-head { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:17px 18px 14px; border-bottom:1px solid var(--line-soft); }
    .panel-title { display:flex; align-items:center; gap:9px; } .panel-title svg { width:16px; color:var(--accent); }
    .count { color:var(--muted); font-size:12px; }
    .composer { padding:18px; }
    label { display:block; color:var(--muted); font-size:12px; font-weight:600; margin:0 0 7px; }
    textarea,input,select { width:100%; color:var(--text); background:#0b1220; border:1px solid var(--line); border-radius:9px; padding:10px 11px; outline:none; }
    textarea { min-height:125px; resize:vertical; } textarea:focus,input:focus,select:focus { border-color:var(--accent); box-shadow:0 0 0 3px rgba(124,140,255,.12); }
    .field { margin-bottom:14px; } .field-row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .hint { color:#71809a; font-size:11px; margin-top:6px; }
    .form-actions { display:flex; align-items:center; gap:10px; margin-top:17px; } .message { color:var(--muted); font-size:12px; }
    .list-tools { padding:13px 15px 11px; border-bottom:1px solid var(--line-soft); }
    .search { position:relative; } .search svg { position:absolute; left:10px; top:10px; width:16px; color:#71809a; } .search input { padding-left:34px; }
    .filters { display:flex; gap:6px; overflow:auto; margin-top:10px; scrollbar-width:none; } .filters::-webkit-scrollbar { display:none; }
    .filter { white-space:nowrap; border:1px solid transparent; color:var(--muted); background:transparent; border-radius:8px; padding:6px 9px; font-size:12px; }
    .filter:hover,.filter.active { color:var(--text); background:var(--surface-3); border-color:var(--line); }
    .runs { max-height:520px; overflow:auto; padding:7px; } .empty { color:var(--muted); text-align:center; padding:43px 18px; }
    .run { position:relative; padding:13px 12px; border:1px solid transparent; border-radius:11px; cursor:pointer; }
    .run + .run { margin-top:3px; } .run:hover { background:rgba(38,52,77,.36); border-color:var(--line-soft); } .run.selected { background:linear-gradient(90deg,rgba(92,107,232,.18),rgba(92,107,232,.04)); border-color:rgba(124,140,255,.55); }
    .run-top { display:flex; align-items:center; justify-content:space-between; gap:8px; } .run-title { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-weight:620; }
    .run-time { color:#697994; font-size:11px; flex:0 0 auto; } .run-meta { display:flex; align-items:center; justify-content:space-between; gap:8px; color:var(--muted); font-size:11px; margin-top:7px; }
    .badge { display:inline-flex; align-items:center; gap:5px; border-radius:999px; padding:3px 8px; font-size:11px; font-weight:700; background:rgba(141,154,177,.13); color:#b5c1d8; }
    .badge::before { content:""; width:6px; height:6px; border-radius:50%; background:currentColor; } .badge.running,.badge.pending { color:var(--warning); background:rgba(246,199,104,.12); } .badge.completed { color:var(--success); background:rgba(74,222,154,.11); } .badge.failed,.badge.cancelled { color:var(--danger); background:rgba(255,113,136,.11); }
    .detail { grid-column:2; grid-row:1 / span 2; min-height:570px; }
    .detail-head { padding:18px 20px; } .detail-id { color:var(--muted); font:11px ui-monospace,SFMono-Regular,Consolas,monospace; margin-top:5px; }
    .detail-actions { display:flex; gap:8px; }
    .detail-body { padding:20px; } .detail-task { font-size:17px; line-height:1.45; letter-spacing:-.015em; margin-bottom:16px; }
    .chat { display:flex; flex-direction:column; gap:14px; }
    .chat-message { max-width:92%; border-radius:13px; padding:11px 13px; white-space:pre-wrap; word-break:break-word; }
    .chat-message.user { align-self:flex-end; background:linear-gradient(135deg,#5968d8,#7561bd); color:#f7f8ff; border-bottom-right-radius:4px; }
    .chat-message.assistant { align-self:flex-start; background:#0b1220; border:1px solid var(--line-soft); border-bottom-left-radius:4px; color:#dce5f5; }
    .chat-message.assistant.error { border-color:rgba(255,113,136,.42); color:#ffd7df; }
    .chat-label { color:var(--muted); font-size:10px; font-weight:750; letter-spacing:.08em; text-transform:uppercase; margin-bottom:5px; }
    .chat-actions { display:flex; flex-direction:column; gap:7px; margin-left:10px; }
    .action-card { border:1px solid rgba(124,140,255,.22); background:rgba(42,52,93,.24); border-radius:10px; padding:9px 11px; }
    .action-card.result { border-color:var(--line-soft); background:rgba(11,18,32,.62); }
    .action-head { display:flex; align-items:center; gap:7px; color:#cbd5ff; font-size:12px; font-weight:700; }
    .action-head .action-icon { color:var(--accent); }
    .action-card.result .action-head { color:var(--muted); }
    .action-detail { margin-top:5px; color:var(--muted); font:11px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace; white-space:pre-wrap; word-break:break-word; max-height:150px; overflow:auto; }
    .meta-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:9px; margin-bottom:19px; } .meta { border:1px solid var(--line-soft); background:rgba(11,18,32,.65); border-radius:10px; padding:10px; } .meta span { display:block; color:var(--muted); font-size:11px; } .meta b { display:block; margin-top:4px; font-size:13px; }
    .section-label { display:flex; align-items:center; justify-content:space-between; color:var(--muted); font-size:12px; font-weight:700; margin:18px 0 8px; }
    pre { margin:0; max-height:230px; overflow:auto; white-space:pre-wrap; word-break:break-word; color:#cdd8ea; background:#090f1b; border:1px solid var(--line-soft); border-radius:10px; padding:13px; font:12px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace; }
    .events { grid-column:1 / -1; } .events-body { padding:0 18px 18px; } .event-status { color:var(--muted); font-size:11px; } .event-status.connected { color:var(--success); }
    .event-stream { max-height:260px; overflow:auto; padding-top:11px; } .event { display:grid; grid-template-columns:70px 1fr; gap:10px; padding:10px 0; border-bottom:1px solid var(--line-soft); } .event:last-child { border-bottom:0; } .event-time { color:#6e7d97; font:11px ui-monospace,SFMono-Regular,Consolas,monospace; } .event-name { color:#dce5f5; font-weight:650; font-size:12px; } .event-payload { color:var(--muted); font:11px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace; white-space:pre-wrap; word-break:break-word; margin-top:3px; }
    .toast { position:fixed; right:22px; bottom:22px; z-index:5; max-width:340px; padding:12px 15px; border:1px solid var(--line); background:#18233a; border-radius:10px; box-shadow:var(--shadow); color:var(--text); opacity:0; transform:translateY(10px); pointer-events:none; transition:.2s ease; } .toast.show { opacity:1; transform:none; } .toast.error { border-color:rgba(255,113,136,.5); }
    @media (max-width:980px) { .shell { grid-template-columns:72px minmax(0,1fr); } .sidebar { padding:20px 10px; } .brand { margin:0 8px 30px; } .brand-copy,.nav-label,.nav button span,.sidebar-foot { display:none; } .nav button { justify-content:center; } .detail { grid-column:1 / -1; grid-row:auto; } }
    @media (max-width:700px) { .shell { display:block; } .sidebar { display:none; } .main { padding:20px 13px 30px; } .topbar { display:block; } .top-actions { margin-top:17px; justify-content:space-between; } .stats { grid-template-columns:repeat(2,1fr); } .workspace { display:flex; flex-direction:column; } .panel,.detail,.events { width:100%; } .detail { min-height:0; } .meta-grid { grid-template-columns:1fr 1fr; } }
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark"><svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8"><path d="M5.5 14.5V8.8L8 6l4 2 4-2 2.5 2.8v5.7a6.5 6.5 0 0 1-13 0Z"/><path d="M8 4.5 9.5 7M16 4.5 14.5 7M9 14h.01M15 14h.01M9.5 17c1.4 1 3.6 1 5 0"/></svg></div><div class="brand-copy">MewCode<small>Agent Runtime</small></div></div>
      <div class="nav-label">Workspace</div>
      <nav class="nav"><button class="active" type="button"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg><span>运行概览</span></button><button type="button" onclick="focusComposer()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 5v14M5 12h14"/></svg><span>新建任务</span></button></nav>
      <div class="sidebar-foot"><span class="dot"></span>本地运行时在线</div>
    </aside>
    <main class="main">
      <header class="topbar"><div><div class="eyebrow">Runtime workspace</div><h1>运行概览</h1><p class="sub">提交任务、跟踪进度，并在一个地方查看完整事件链。</p></div><div class="top-actions"><span class="health" id="health">检查服务中…</span><button class="icon-btn" id="refresh" title="刷新运行列表" aria-label="刷新运行列表"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 11a8.1 8.1 0 0 0-14.9-4L3 10"/><path d="M3 5v5h5M4 13a8.1 8.1 0 0 0 14.9 4L21 14"/><path d="M21 19v-5h-5"/></svg></button></div></header>
      <section class="stats" aria-label="运行统计"><div class="stat"><div class="stat-label"><span>全部运行</span><span>◌</span></div><div class="stat-value stat-accent" id="stat-total">0</div></div><div class="stat"><div class="stat-label"><span>运行中</span><span>↗</span></div><div class="stat-value stat-warning" id="stat-running">0</div></div><div class="stat"><div class="stat-label"><span>已完成</span><span>✓</span></div><div class="stat-value stat-success" id="stat-completed">0</div></div><div class="stat"><div class="stat-label"><span>需关注</span><span>!</span></div><div class="stat-value stat-danger" id="stat-failed">0</div></div></section>
      <div class="workspace">
        <section class="panel composer" id="composer"><div class="panel-title" style="justify-content:space-between;margin-bottom:17px"><div class="panel-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 5v14M5 12h14"/></svg><h2>与 LLM 对话</h2></div><button class="btn ghost" type="button" onclick="focusComposer(true)">新会话</button></div><form id="submit-form"><div class="field"><label for="task">消息</label><textarea id="task" required placeholder="输入你的问题或开发任务，例如：分析 runtime 模块并补充测试"></textarea><div class="hint">同一会话会保留上下文；发送后可继续追问，右侧会显示回答和工具操作。</div></div><div class="field-row"><div class="field"><label for="attempts">最大尝试次数</label><input id="attempts" type="number" min="1" max="5" value="1"></div><div class="field"><label for="timeout">超时（秒）</label><input id="timeout" type="number" min="1" placeholder="不限制"></div></div><div class="form-actions"><button class="btn primary" type="submit">发送消息</button><span id="submit-message" class="message"></span></div></form></section>
        <section class="panel runs-panel"><div class="panel-head"><div class="panel-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 6h16M4 12h16M4 18h10"/></svg><h2>运行历史</h2></div><span class="count" id="run-count">0 个任务</span></div><div class="list-tools"><div class="search"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="6"/><path d="m16 16 4 4"/></svg><input id="search" type="search" placeholder="搜索任务或运行 ID"></div><div class="filters" id="filters"><button class="filter active" data-filter="all">全部</button><button class="filter" data-filter="running">运行中</button><button class="filter" data-filter="completed">已完成</button><button class="filter" data-filter="failed">失败</button><button class="filter" data-filter="cancelled">已取消</button></div></div><div class="runs" id="runs"><div class="empty">正在加载运行记录…</div></div></section>
        <section class="panel detail" id="detail-panel"><div class="panel-head detail-head"><div><div class="panel-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 5h16v14H4zM8 9h8M8 13h5"/></svg><h2>对话与操作</h2></div><div class="detail-id" id="detail-id">尚未选择任务</div></div><div class="detail-actions"><button class="btn danger" id="cancel" disabled>取消</button><button class="btn" id="retry" disabled>重试</button></div></div><div class="detail-body" id="detail"><div class="empty">发送消息或从左侧选择一个任务查看对话</div></div></section>
        <section class="panel events"><div class="panel-head"><div class="panel-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 3h12v18H6zM9 7h6M9 11h6M9 15h4"/></svg><h2>实时事件</h2></div><span class="event-status" id="event-status">未连接</span></div><div class="events-body"><div class="event-stream" id="events"><div class="empty">选择运行后，事件会在这里实时显示。</div></div></div></section>
      </div>
    </main>
  </div>
  <div class="toast" id="toast" role="status"></div>
<script>
  const newSessionId = () => (crypto.randomUUID ? crypto.randomUUID() : `web-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  const state = { runs: [], selected: null, sessionId: newSessionId(), filter: 'all', query: '', source: null, lastEventId: 0, eventCount: 0, toastTimer: null };
  const $ = id => document.getElementById(id);
  const labels = {pending:'排队中',running:'运行中',waiting_approval:'等待审批',completed:'已完成',failed:'失败',cancelled:'已取消'};
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const time = stamp => stamp ? new Date(stamp * 1000).toLocaleString() : '-';
  const shortTime = stamp => stamp ? new Date(stamp * 1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : '-';
  async function api(path, options) { const response = await fetch(path, options); const data = await response.json().catch(() => ({})); if (!response.ok) throw new Error(data.detail || data.error?.message || response.statusText); return data; }
  function notify(message, error = false) { const toast = $('toast'); toast.textContent = message; toast.className = `toast show${error ? ' error' : ''}`; clearTimeout(state.toastTimer); state.toastTimer = setTimeout(() => toast.className = 'toast', 3200); }
  function updateStats() { const count = status => state.runs.filter(r => r.status === status).length; $('stat-total').textContent = state.runs.length; $('stat-running').textContent = count('running') + count('pending'); $('stat-completed').textContent = count('completed'); $('stat-failed').textContent = count('failed') + count('cancelled'); }
  function visibleRuns() { const query = state.query.trim().toLowerCase(); return state.runs.filter(run => (state.filter === 'all' || run.status === state.filter) && (!query || `${run.id} ${run.task}`.toLowerCase().includes(query))); }
  function renderRuns() { const runs = visibleRuns(); $('run-count').textContent = `${runs.length}/${state.runs.length} 个任务`; $('runs').innerHTML = runs.length ? runs.map(run => `<article class="run ${run.id === state.selected ? 'selected' : ''}" data-id="${esc(run.id)}"><div class="run-top"><div class="run-title">${esc(run.task)}</div><span class="run-time">${esc(shortTime(run.created_at))}</span></div><div class="run-meta"><span class="badge ${esc(run.status)}">${esc(labels[run.status] || run.status)}</span><span>尝试 ${esc(run.attempt)}/${esc(run.max_attempts)}</span></div></article>`).join('') : '<div class="empty">没有符合条件的运行</div>'; document.querySelectorAll('.run').forEach(el => el.onclick = () => selectRun(el.dataset.id)); updateStats(); }
  function renderDetail(run) { if (!run) { $('detail-id').textContent = '尚未选择任务'; $('detail').innerHTML = '<div class="empty">发送消息或从左侧选择一个任务查看对话</div>'; $('cancel').disabled = $('retry').disabled = true; return; } const terminal = ['completed','failed','cancelled'].includes(run.status); state.sessionId = run.session_id || state.sessionId; $('detail-id').textContent = `${run.id} · ${time(run.created_at)} · 会话 ${state.sessionId.slice(0, 8)}`; $('detail').innerHTML = `<div class="meta-grid"><div class="meta"><span>状态</span><b><span class="badge ${esc(run.status)}">${esc(labels[run.status] || run.status)}</span></b></div><div class="meta"><span>尝试次数</span><b>${esc(run.attempt)} / ${esc(run.max_attempts)}</b></div><div class="meta"><span>会话</span><b>${esc(state.sessionId.slice(0, 12))}</b></div></div><div class="chat" id="chat"><div class="chat-message user"><div class="chat-label">你</div>${esc(run.task)}</div><div class="chat-message assistant" id="assistant-message"><div class="chat-label">MewCode</div><span class="assistant-text">${esc(run.result || run.error || '正在思考…')}</span></div><div class="chat-actions" id="chat-actions"></div></div>`; if (run.status === 'failed' && run.error) $('assistant-message').classList.add('error'); $('cancel').disabled = terminal; $('retry').disabled = !['failed','cancelled'].includes(run.status); }
  function appendConversationEvent(event) { const assistant = $('assistant-message'); const actions = $('chat-actions'); if (!assistant || !actions) return; if (event.event_type === 'stream_text') { assistant.querySelector('.assistant-text').textContent = event.payload?.text || ''; } else if (event.event_type === 'tool_use') { const args = event.payload?.args; actions.insertAdjacentHTML('beforeend', `<div class="action-card"><div class="action-head"><span class="action-icon">⚙</span>正在操作 · ${esc(event.payload?.toolName || 'tool')}</div><div class="action-detail">${esc(typeof args === 'string' ? args : JSON.stringify(args || {}, null, 2))}</div></div>`); } else if (event.event_type === 'tool_result') { const output = event.payload?.output || ''; const error = event.payload?.is_error; actions.insertAdjacentHTML('beforeend', `<div class="action-card result"><div class="action-head"><span class="action-icon">${error ? '!' : '✓'}</span>${error ? '操作失败' : '操作完成'} · ${esc(event.payload?.toolName || 'tool')}</div><div class="action-detail">${esc(output)}</div></div>`); } else if (event.event_type === 'run_failed') { assistant.querySelector('.assistant-text').textContent = event.payload?.error || '运行失败'; assistant.classList.add('error'); } else if (event.event_type === 'run_completed' && assistant.querySelector('.assistant-text').textContent === '正在思考…') { assistant.querySelector('.assistant-text').textContent = event.payload?.result || ''; } }
  function appendEvent(event) { state.lastEventId = Math.max(state.lastEventId, Number(event.sequence || 0)); state.eventCount += 1; const stream = $('events'); if (state.eventCount === 1) stream.innerHTML = ''; const payload = Object.keys(event.payload || {}).length ? `\n${esc(JSON.stringify(event.payload, null, 2))}` : ''; stream.insertAdjacentHTML('beforeend', `<div class="event"><div class="event-time">${esc(shortTime(event.timestamp))}</div><div><div class="event-name">${esc(event.event_type)} <span style="color:#62708a">#${esc(event.sequence)}</span></div><div class="event-payload">${payload}</div></div></div>`); stream.scrollTop = stream.scrollHeight; }
  function setEventStatus(text, connected = false) { $('event-status').textContent = text; $('event-status').className = `event-status${connected ? ' connected' : ''}`; }
  function watch(run, after = 0) { if (state.source) state.source.close(); if (!after) { state.lastEventId = 0; state.eventCount = 0; $('events').innerHTML = '<div class="empty">正在连接事件流…</div>'; } setEventStatus('连接中…'); const source = state.source = new EventSource(`/v1/runs/${encodeURIComponent(run.id)}/events?after=${state.lastEventId}`); const types = ['run_created','run_started','run_completed','run_failed','run_cancelled','run_timeout','run_retrying','run_recovered','agent_event','stream_text','tool_use','tool_result','usage']; const consume = event => { try { const parsed = JSON.parse(event.data); appendEvent(parsed); appendConversationEvent(parsed); } catch (_) { return; } setEventStatus('实时连接', true); refresh(false); if (['run_completed','run_failed','run_cancelled'].includes(event.type)) { source.close(); state.source = null; setEventStatus('运行结束', true); } }; types.forEach(type => source.addEventListener(type, consume)); source.onopen = () => setEventStatus('实时连接', true); source.onerror = () => { if (state.source !== source) return; source.close(); state.source = null; const current = state.runs.find(item => item.id === run.id); if (current && !['completed','failed','cancelled'].includes(current.status)) { setEventStatus('连接断开，自动重试…'); window.setTimeout(() => { if (state.selected === run.id) watch(run, state.lastEventId); }, 1200); } else { setEventStatus('运行结束', true); } }; }
  async function refresh(showToast = true) { try { const data = await api('/v1/runs?limit=100'); state.runs = data.runs || []; renderRuns(); if (state.selected) { const current = state.runs.find(r => r.id === state.selected); if (current) renderDetail(current); } if (showToast) notify('运行列表已刷新'); } catch (error) { $('runs').innerHTML = `<div class="empty">加载失败：${esc(error.message)}</div>`; if (showToast) notify(error.message, true); } }
  async function selectRun(id) { state.selected = id; renderRuns(); try { const run = await api(`/v1/runs/${encodeURIComponent(id)}`); renderDetail(run); watch(run); $('detail-panel').scrollIntoView({behavior:'smooth', block:'nearest'}); } catch (error) { notify(error.message, true); } }
  async function health() { try { const result = await api('/health'); $('health').innerHTML = '<span class="dot"></span>服务在线'; $('health').title = `${result.runs ?? 0} 个运行记录`; } catch (_) { $('health').textContent = '服务检查失败'; } }
  function focusComposer(newSession = false) { if (newSession) { if (state.source) state.source.close(); state.source = null; state.sessionId = newSessionId(); state.selected = null; state.eventCount = 0; setEventStatus('未连接'); renderRuns(); renderDetail(null); notify('已创建新会话'); } $('task').focus(); $('composer').scrollIntoView({behavior:'smooth', block:'center'}); }
  $('refresh').onclick = () => refresh(true); $('search').oninput = event => { state.query = event.target.value; renderRuns(); }; document.querySelectorAll('.filter').forEach(button => button.onclick = () => { document.querySelectorAll('.filter').forEach(item => item.classList.remove('active')); button.classList.add('active'); state.filter = button.dataset.filter; renderRuns(); });
  $('submit-form').onsubmit = async event => { event.preventDefault(); const message = $('submit-message'); message.textContent = '发送中…'; try { const payload = {task:$('task').value.trim(), session_id:state.sessionId, max_attempts:Number($('attempts').value)}; if ($('timeout').value) payload.timeout_seconds = Number($('timeout').value); const run = await api('/v1/runs', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)}); $('task').value = ''; message.textContent = `已发送 · ${run.id}`; notify('消息已发送'); await refresh(false); await selectRun(run.id); } catch (error) { message.textContent = `发送失败：${error.message}`; notify(error.message, true); } };
  $('cancel').onclick = async () => { if (!state.selected) return; $('cancel').disabled = true; try { await api(`/v1/runs/${encodeURIComponent(state.selected)}/cancel`, {method:'POST'}); notify('已发送取消请求'); await refresh(false); await selectRun(state.selected); } catch (error) { notify(error.message, true); } };
  $('retry').onclick = async () => { if (!state.selected) return; $('retry').disabled = true; try { const run = await api(`/v1/runs/${encodeURIComponent(state.selected)}/retry`, {method:'POST'}); notify('已创建重试任务'); await refresh(false); await selectRun(run.id); } catch (error) { notify(error.message, true); } };
  refresh(false); health();
</script>
</body>
</html>"""
