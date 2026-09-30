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
  <title>MewCode 控制台</title>
  <style>
    :root { color-scheme: dark; --bg:#10131a; --panel:#181d27; --line:#2b3444; --text:#e8edf5; --muted:#93a0b5; --accent:#67b7ff; --danger:#ff7b86; --ok:#62d69b; }
    * { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--text); font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
    header { padding:22px max(20px, calc((100vw - 1180px)/2)); border-bottom:1px solid var(--line); display:flex; justify-content:space-between; align-items:center; gap:16px; }
    h1,h2,p { margin:0; } h1 { font-size:22px; } h2 { font-size:16px; margin-bottom:12px; } .muted { color:var(--muted); }
    main { max-width:1180px; margin:24px auto; padding:0 20px; display:grid; grid-template-columns:minmax(280px, .8fr) minmax(420px, 1.2fr); gap:18px; }
    .panel { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:18px; min-width:0; } .wide { grid-column:1/-1; }
    textarea,input,button { font:inherit; } textarea,input { width:100%; background:#0f131b; color:var(--text); border:1px solid var(--line); border-radius:6px; padding:10px; }
    textarea { min-height:110px; resize:vertical; } label { display:block; color:var(--muted); margin:10px 0 6px; } .row { display:flex; gap:8px; align-items:center; }
    button { border:1px solid var(--line); color:var(--text); background:#202938; padding:8px 12px; border-radius:6px; cursor:pointer; } button:hover { border-color:var(--accent); } button.primary { background:#1768a7; border-color:#2d8ed7; }
    button.danger { color:#ffd6d9; border-color:#74313a; background:#3a2026; } button:disabled { opacity:.5; cursor:not-allowed; }
    #runs { display:flex; flex-direction:column; gap:8px; max-height:520px; overflow:auto; } .run { padding:11px; border:1px solid var(--line); border-radius:7px; cursor:pointer; } .run:hover,.run.selected { border-color:var(--accent); }
    .run-title { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; } .run-meta { display:flex; justify-content:space-between; gap:10px; margin-top:5px; color:var(--muted); font-size:12px; }
    .status { font-weight:600; } .status.completed { color:var(--ok); } .status.failed,.status.cancelled { color:var(--danger); } .status.running,.status.pending { color:#ffd36b; }
    pre { margin:0; white-space:pre-wrap; word-break:break-word; background:#0c1016; border-radius:6px; padding:12px; max-height:360px; overflow:auto; color:#c9d4e5; } #events { min-height:150px; }
    .empty { padding:28px 8px; text-align:center; color:var(--muted); } .toolbar { display:flex; gap:8px; align-items:center; justify-content:space-between; margin-bottom:10px; }
    @media (max-width:800px) { main { grid-template-columns:1fr; } .wide { grid-column:auto; } }
  </style>
</head>
<body>
  <header><div><h1>🐱 MewCode 控制台</h1><p class="muted">Agent Runtime · REST + SSE</p></div><button id="refresh">刷新任务</button></header>
  <main>
    <section class="panel"><h2>提交任务</h2><form id="submit-form"><label for="task">任务描述</label><textarea id="task" required placeholder="例如：分析 runtime 模块并补充测试"></textarea><label for="attempts">最大尝试次数</label><input id="attempts" type="number" min="1" max="5" value="1"><div class="row" style="margin-top:14px"><button class="primary" type="submit">提交任务</button><span id="submit-message" class="muted"></span></div></form></section>
    <section class="panel"><div class="toolbar"><h2>运行历史</h2><span id="run-count" class="muted"></span></div><div id="runs"><div class="empty">正在加载…</div></div></section>
    <section class="panel wide"><div class="toolbar"><h2>任务详情 <span id="detail-status" class="status"></span></h2><div class="row"><button id="cancel" class="danger" disabled>取消</button><button id="retry" disabled>重试</button></div></div><div id="detail" class="empty">选择一个任务查看详情</div></section>
    <section class="panel wide"><h2>实时事件</h2><pre id="events">选择运行中的任务后，事件会实时显示在这里。</pre></section>
  </main>
<script>
  const state = { runs: [], selected: null, source: null };
  const $ = (id) => document.getElementById(id);
  const labels = {pending:'排队中',running:'运行中',waiting_approval:'等待审批',completed:'已完成',failed:'失败',cancelled:'已取消'};
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const time = (stamp) => stamp ? new Date(stamp * 1000).toLocaleString() : '-';
  async function api(path, options) { const response = await fetch(path, options); const data = await response.json().catch(() => ({})); if (!response.ok) throw new Error(data.detail || response.statusText); return data; }
  function renderRuns() { $('run-count').textContent = `${state.runs.length} 个任务`; $('runs').innerHTML = state.runs.length ? state.runs.map(r => `<div class="run ${r.id === state.selected ? 'selected' : ''}" data-id="${esc(r.id)}"><div class="run-title">${esc(r.task)}</div><div class="run-meta"><span class="status ${esc(r.status)}">${esc(labels[r.status] || r.status)}</span><span>${esc(time(r.created_at))}</span></div></div>`).join('') : '<div class="empty">还没有运行记录</div>'; document.querySelectorAll('.run').forEach(el => el.onclick = () => selectRun(el.dataset.id)); }
  function renderDetail(run) { if (!run) { $('detail').innerHTML = '<div class="empty">选择一个任务查看详情</div>'; return; } const terminal = ['completed','failed','cancelled'].includes(run.status); $('detail-status').textContent = labels[run.status] || run.status; $('detail-status').className = `status ${run.status}`; $('detail').innerHTML = `<p><b>${esc(run.id)}</b> · 创建于 ${esc(time(run.created_at))}</p><p class="muted" style="margin:6px 0">会话：${esc(run.session_id || '-')} · 尝试：${esc(run.attempt)}/${esc(run.max_attempts)}</p><pre>${esc(run.result || run.error || '暂无结果')}</pre>`; $('cancel').disabled = terminal; $('retry').disabled = !['failed','cancelled'].includes(run.status); }
  function appendEvent(event) { const line = `[${new Date((event.timestamp || Date.now()/1000)*1000).toLocaleTimeString()}] ${event.event_type}\n${JSON.stringify(event.payload || {}, null, 2)}\n\n`; $('events').textContent += line; $('events').scrollTop = $('events').scrollHeight; }
  function watch(run) { if (state.source) state.source.close(); $('events').textContent = ''; state.source = new EventSource(`/v1/runs/${encodeURIComponent(run.id)}/events`); const consume = e => { appendEvent(JSON.parse(e.data)); refresh(); }; state.source.onmessage = consume; ['run_created','run_started','run_completed','run_failed','run_cancelled','run_timeout','run_retrying','run_recovered','agent_event','stream_text','tool_use','usage'].forEach(type => state.source.addEventListener(type, consume)); state.source.onerror = () => { state.source.close(); state.source = null; }; }
  async function refresh() { try { const data = await api('/v1/runs?limit=100'); state.runs = data.runs || []; renderRuns(); if (state.selected) { const current = state.runs.find(r => r.id === state.selected); if (current) renderDetail(current); } } catch (e) { $('runs').innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`; } }
  async function selectRun(id) { state.selected = id; renderRuns(); try { const run = await api(`/v1/runs/${encodeURIComponent(id)}`); renderDetail(run); watch(run); } catch (e) { $('detail').textContent = e.message; } }
  $('refresh').onclick = refresh;
  $('submit-form').onsubmit = async (e) => { e.preventDefault(); $('submit-message').textContent = '提交中…'; try { const run = await api('/v1/runs', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({task:$('task').value, max_attempts:Number($('attempts').value)})}); $('task').value = ''; $('submit-message').textContent = `已提交 ${run.id}`; await refresh(); await selectRun(run.id); } catch (err) { $('submit-message').textContent = `提交失败：${err.message}`; } };
  $('cancel').onclick = async () => { if (!state.selected) return; try { await api(`/v1/runs/${encodeURIComponent(state.selected)}/cancel`, {method:'POST'}); await refresh(); await selectRun(state.selected); } catch (e) { alert(e.message); } };
  $('retry').onclick = async () => { if (!state.selected) return; try { const run = await api(`/v1/runs/${encodeURIComponent(state.selected)}/retry`, {method:'POST'}); await refresh(); await selectRun(run.id); } catch (e) { alert(e.message); } };
  refresh();
</script>
</body></html>"""
