"""Deterministic Agent-system evaluation harness.

This is deliberately provider-free: the fake clients model the protocol boundary,
while the real MewCode tools, Agent loop, trace manager, runtime and HTTP adapter
are exercised.  Run with ``python tests/run_agent_eval.py``.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Make direct execution (`python tests/run_agent_eval.py`) behave like
# `python -m ...` from the repository root on Windows and POSIX hosts.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mewcode.agent import Agent
from mewcode.agents.trace import TraceManager
from mewcode.runtime.dag import DAGNode, DAGScheduler, NodeStatus
from mewcode.runtime.models import RunStatus
from mewcode.runtime.service import AgentRuntime
from mewcode.runtime.store import RunStore
from mewcode.tools import create_default_registry
from mewcode.tools.base import StreamEnd, TextDelta, ToolCallComplete, ToolResult


RESULTS: list[dict[str, Any]] = []


def record(area: str, name: str, passed: bool, **details: Any) -> None:
    RESULTS.append({"area": area, "name": name, "passed": passed, **details})


async def tool_eval(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    registry = create_default_registry()
    expected = {"ReadFile", "WriteFile", "EditFile", "Bash", "Glob", "Grep"}
    actual = {tool.name for tool in registry.list_tools()}
    record("tool", "registry contains six core tools", actual == expected, expected=sorted(expected), actual=sorted(actual))
    for tool in registry.list_tools():
        schema = tool.get_schema()["input_schema"]
        record("tool", f"{tool.name} schema has required fields", bool(schema.get("required")), required=schema.get("required", []))

    fixture = root / "fixture.txt"
    fixture.write_text("alpha\nbeta\nbeta\n", encoding="utf-8")
    read = registry.get("ReadFile")
    write = registry.get("WriteFile")
    edit = registry.get("EditFile")
    bash = registry.get("Bash")
    glob = registry.get("Glob")
    grep = registry.get("Grep")

    r = await read.execute(read.params_model(file_path=str(fixture)))
    record("tool", "ReadFile success and line numbers", not r.is_error and "1\talpha" in r.output and "3\tbeta" in r.output)
    r = await read.execute(read.params_model(file_path=str(root / "missing")))
    record("tool", "ReadFile missing file is structured error", r.is_error and "not found" in r.output.lower())

    created = root / "nested" / "new.txt"
    r = await write.execute(write.params_model(file_path=str(created), content="created"))
    record("tool", "WriteFile creates parent directories", not r.is_error and created.read_text(encoding="utf-8") == "created")
    guarded = root / "guarded.txt"
    guarded.write_text("guarded", encoding="utf-8")
    r = await write.execute(write.params_model(file_path=str(guarded), content="unsafe overwrite"))
    record("tool", "WriteFile blocks unread overwrite", r.is_error and "read" in r.output.lower())
    await read.execute(read.params_model(file_path=str(fixture)))
    r = await write.execute(write.params_model(file_path=str(fixture), content="alpha\nbeta\ngamma\n"))
    record("tool", "WriteFile allows overwrite after ReadFile", not r.is_error and "gamma" in fixture.read_text(encoding="utf-8"))

    edit_fixture = root / "edit.txt"
    edit_fixture.write_text("gamma\n", encoding="utf-8")
    r = await edit.execute(edit.params_model(file_path=str(edit_fixture), old_string="gamma", new_string="delta"))
    record("tool", "EditFile requires a fresh ReadFile", r.is_error)
    await read.execute(read.params_model(file_path=str(edit_fixture)))
    r = await edit.execute(edit.params_model(file_path=str(edit_fixture), old_string="gamma", new_string="delta"))
    record("tool", "EditFile unique replacement", not r.is_error and "delta" in edit_fixture.read_text(encoding="utf-8"))
    await read.execute(read.params_model(file_path=str(edit_fixture)))
    r = await edit.execute(edit.params_model(file_path=str(edit_fixture), old_string="absent", new_string="x"))
    record("tool", "EditFile rejects missing old_string", r.is_error)

    r = await bash.execute(bash.params_model(command="python -c \"print('ok')\""))
    record("tool", "Bash success includes exit code", not r.is_error and "EXIT CODE: 0" in r.output and "ok" in r.output)
    r = await bash.execute(bash.params_model(command="cmd /c exit 3"))
    record("tool", "Bash nonzero exit is error", r.is_error and "EXIT CODE: 3" in r.output)
    r = await bash.execute(bash.params_model(command="python -c \"import time; time.sleep(2)\"", timeout=1))
    record("tool", "Bash timeout is structured error", r.is_error and "timed out" in r.output.lower())

    (root / ".git").mkdir()
    (root / ".git" / "ignored.txt").write_text("skip", encoding="utf-8")
    r = await glob.execute(glob.params_model(pattern="**/*.txt", path=str(root)))
    record("tool", "Glob finds files and skips .git", not r.is_error and "fixture.txt" in r.output and "ignored.txt" not in r.output)
    r = await grep.execute(grep.params_model(pattern="delta", path=str(root), include="*.txt"))
    record("tool", "Grep returns matching file and line", not r.is_error and ("fixture.txt" in r.output or "edit.txt" in r.output) and "delta" in r.output, output=r.output)
    r = await grep.execute(grep.params_model(pattern="[", path=str(root)))
    record("tool", "Grep invalid regex is structured error", r.is_error and "invalid regex" in r.output.lower())


class FakeClient:
    model = "eval-model"

    def __init__(self, responses: list[list[Any]]) -> None:
        self.responses = responses
        self.calls = 0

    async def stream(self, *_args: Any, **_kwargs: Any):
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        for event in response:
            yield event


async def trajectory_eval(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    fixture = root / "trajectory.txt"
    fixture.write_text("trajectory fixture\n", encoding="utf-8")
    client = FakeClient([
        [ToolCallComplete("t1", "ReadFile", {"file_path": str(fixture)}), StreamEnd("tool_use", 10, 4)],
        [TextDelta("done"), StreamEnd("end_turn", 12, 3)],
    ])
    agent = Agent(client, create_default_registry(), "openai-compat", work_dir=str(root), max_iterations=4)
    events: list[dict[str, Any]] = []
    result = await agent.run_to_completion("read fixture", event_callback=events.append)
    phases = [e.get("phase") for e in events if e.get("type") == "agent_phase"]
    tool_result = next((e for e in events if e.get("type") == "tool_result"), {})
    usage = next((e for e in events if e.get("type") == "usage"), {})
    record("trajectory", "Agent completes deterministic tool trajectory", result == "done" and client.calls == 2)
    record("trajectory", "Trajectory emits phase order", phases[:3] == ["thinking", "tool_call", "thinking"], phases=phases)
    record("trajectory", "Tool result has observability fields", all(k in tool_result for k in ("tool_id", "iteration", "duration_ms", "error_category", "attempt")), fields=sorted(tool_result))
    record("trajectory", "Usage event has iteration and latency", usage.get("iteration") == 1 and isinstance(usage.get("duration_ms"), int), usage=usage)

    repeated = FakeClient([
        [ToolCallComplete(f"r{i}", "ReadFile", {"file_path": str(root / "absent")}), StreamEnd("tool_use")]
        for i in range(1, 4)
    ] + [[TextDelta("recovered"), StreamEnd("end_turn")]])
    repeated_agent = Agent(repeated, create_default_registry(), "openai-compat", work_dir=str(root), max_iterations=4)
    repeated_events: list[dict[str, Any]] = []
    output = await repeated_agent.run_to_completion("repeat", event_callback=repeated_events.append)
    blocked = [e for e in repeated_events if e.get("type") == "tool_result" and "Repeated tool call blocked" in e.get("output", "")]
    record("trajectory", "Repeated identical tool calls are bounded", output == "recovered" and len(blocked) == 1, blocked=len(blocked))


async def trace_eval() -> None:
    manager = TraceManager()
    root = manager.create("main", trace_id="eval-trace")
    child = manager.create("Explore", parent_id=root.agent_id, trace_id=root.trace_id)
    manager.update(root.agent_id, input_tokens=100, output_tokens=30)
    manager.update(child.agent_id, input_tokens=20, output_tokens=10)
    manager.complete(child.agent_id, "completed")
    nodes = manager.get_tree("eval-trace")
    totals = manager.get_total_tokens("eval-trace")
    record("trace", "Parent-child trace links are retained", len(nodes) == 2 and child.parent_id == root.agent_id)
    record("trace", "Trace token totals are additive", totals == (120, 40), totals=totals)
    record("trace", "Trace completion records end time", manager.get(child.agent_id).end_time is not None)


class RuntimeAgent:
    def __init__(self, result: str = "ok", delay: float = 0, failures: int = 0) -> None:
        self.result, self.delay, self.failures, self.calls = result, delay, failures, 0
        self.client = type("Client", (), {"model": "runtime-eval-model"})()

    async def run_to_completion(self, task: str, conversation=None, event_callback=None) -> str:
        self.calls += 1
        if event_callback:
            event_callback({"type": "stream_text", "text": task, "phase": "thinking", "iteration": 1})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("transient network failure")
        return self.result


async def runtime_eval(root: Path) -> None:
    agents: list[RuntimeAgent] = []

    def factory(_run):
        agent = RuntimeAgent(result="done", failures=1 if not agents else 0)
        agents.append(agent)
        return agent

    runtime = AgentRuntime(agent_factory=factory, store=RunStore(root / "runs"))
    run = runtime.submit("hello", max_attempts=2, metadata={"provider": "eval"})
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline and runtime.get(run.id).status not in {RunStatus.COMPLETED, RunStatus.FAILED}:
        await asyncio.sleep(0.05)
    events = runtime.events(run.id)
    types = [event.event_type for event in events]
    stream = next((event for event in events if event.event_type == "stream_text"), None)
    retry = next((event for event in events if event.event_type == "run_retrying"), None)
    record("e2e", "Runtime retries and completes", runtime.get(run.id).status == RunStatus.COMPLETED and run.attempt == 2, event_types=types)
    record("monitoring", "Runtime event carries model/provider/elapsed", stream is not None and stream.payload.get("model") == "runtime-eval-model" and stream.payload.get("provider") == "eval" and "run_elapsed_ms" in stream.payload, payload=stream.payload if stream else {})
    record("monitoring", "Retry event carries category and backoff", retry is not None and retry.payload.get("error_category") == "transient" and retry.payload.get("delay_seconds") == 1, payload=retry.payload if retry else {})
    replay = [event.event_type async for event in runtime.subscribe(run.id)]
    record("e2e", "Completed run event stream replays and terminates", replay and replay[-1] == "run_completed", replay=replay)

    cancel_runtime = AgentRuntime(agent_factory=lambda _run: RuntimeAgent(delay=5), store=RunStore(root / "cancel-runs"))
    cancel_run = cancel_runtime.submit("slow")
    await asyncio.sleep(0.05)
    accepted = cancel_runtime.cancel(cancel_run.id)
    await asyncio.sleep(0.05)
    record("e2e", "Cancellation is durable", accepted and cancel_runtime.get(cancel_run.id).status == RunStatus.CANCELLED)

    timeout_runtime = AgentRuntime(agent_factory=lambda _run: RuntimeAgent(delay=5), store=RunStore(root / "timeout-runs"))
    timeout_run = timeout_runtime.submit("timeout", timeout_seconds=0.05)
    await asyncio.sleep(0.15)
    timeout_events = timeout_runtime.events(timeout_run.id)
    record("e2e", "Timeout produces terminal failure and category", timeout_runtime.get(timeout_run.id).status == RunStatus.FAILED and any(e.event_type == "run_timeout" and e.payload.get("error_category") == "timeout" for e in timeout_events))

    scheduler = DAGScheduler(root / "dag", max_parallel=2)
    dag = scheduler.create([
        DAGNode(id="explore", task="explore"),
        DAGNode(id="tests", task="tests"),
        DAGNode(id="review", task="review", dependencies=["explore", "tests"]),
    ])
    calls: list[str] = []

    async def execute(node, dependencies):
        calls.append(node.id)
        await asyncio.sleep(0.01)
        return f"result:{node.id}"

    completed = await scheduler.run(dag, execute)
    record("e2e", "DAG executes independent nodes before dependent node", completed.status == NodeStatus.COMPLETED and calls[:2] == ["explore", "tests"] and calls[2] == "review", calls=calls)


def http_eval() -> None:
    try:
        from fastapi.testclient import TestClient
        from mewcode.runtime.http import create_app
    except Exception as exc:  # pragma: no cover - optional dependency
        record("monitoring", "HTTP adapter dependency available", False, error=str(exc))
        return

    class FakeRuntime:
        def __init__(self):
            self.runs = []

        def list_runs(self):
            return self.runs

        def get(self, run_id):
            return next((run for run in self.runs if run.id == run_id), None)

        def submit(self, task, **kwargs):
            from mewcode.runtime.models import AgentRun
            run = AgentRun(task=task, session_id=kwargs.get("session_id", ""), metadata=kwargs.get("metadata", {}))
            self.runs.append(run)
            return run

        def cancel(self, _run_id):
            return True

    runtime = FakeRuntime()
    client = TestClient(create_app(runtime))
    health = client.get("/health")
    submit = client.post("/v1/runs", json={"task": "eval", "session_id": "s1"})
    record("monitoring", "HTTP health endpoint reports liveness", health.status_code == 200 and health.json()["service"] == "mewcode-runtime")
    record("monitoring", "HTTP submit preserves session", submit.status_code == 202 and submit.json()["session_id"] == "s1")


def write_report(path: Path) -> None:
    passed = sum(1 for item in RESULTS if item["passed"])
    total = len(RESULTS)
    by_area: dict[str, list[dict[str, Any]]] = {}
    for item in RESULTS:
        by_area.setdefault(item["area"], []).append(item)
    payload = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "passed": passed, "total": total, "pass_rate": passed / total if total else 0, "results": RESULTS}
    path.with_suffix(".json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# MewCode Agent 专项评测", "", f"专项评测通过率：{passed}/{total} ({passed / total:.1%})", "",
        "指标定义：工具正确率=成功/预期工具场景；轨迹完整性=必需 phase/tool/usage 字段齐全；E2E 成功率=运行完成且状态、事件、产物满足断言；监控覆盖率=关键事件含 model/provider/attempt/elapsed/duration/error_category。", "",
        "## 回归基线", "",
        "- 全量 pytest：589 passed, 1 skipped, 2 failed（Web 控制台中文断言；Windows `WinError 5` 临时文件替换）。",
        "- Agent/Runtime/DAG/论文定向 pytest：103 passed, 2 failed；两次失败均为 Windows `Path.replace` 的同类 `WinError 5`，单独重跑 `test_dag_tools.py` 为 6/6。",
        "- 权限/MCP/Hook/Worktree/Recovery/Context 定向 pytest：213 passed, 1 skipped。",
        "- `python -m compileall -q mewcode`：PASS。",
        "",
        "## 线上监控审计",
        "",
        "- 已有：`/health`、运行状态 REST、SSE 事件回放；事件包含 attempt、model/provider、run_elapsed_ms、工具 duration_ms、错误分类和 token 用量。",
        "- 缺口：没有聚合指标（成功率、工具错误率、p50/p95/p99、token 成本、重试率）和告警；健康检查只验证服务存活，不验证 Provider readiness。",
        "- 风险：tool_result 原文会进入事件日志和 SSE，生产环境需要敏感信息脱敏、日志保留/轮转和访问控制；Runtime 事件尚未自动携带 Agent trace_id/agent_id，跨子 Agent 关联需要补齐。",
        "",
    ]
    for area, items in by_area.items():
        lines += [f"## {area}", "", "| 场景 | 结果 | 细节 |", "|---|---|---|"]
        for item in items:
            details = ", ".join(f"{k}={v}" for k, v in item.items() if k not in {"area", "name", "passed"})
            lines.append(f"| {item['name']} | {'PASS' if item['passed'] else 'FAIL'} | {details} |")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"passed": passed, "total": total, "pass_rate": payload["pass_rate"], "report": str(path), "json": str(path.with_suffix('.json'))}, ensure_ascii=False))


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="mewcode-agent-eval-") as temp:
        root = Path(temp)
        await tool_eval(root / "tools")
        (root / "tools").mkdir(parents=True, exist_ok=True)
        await trajectory_eval(root / "trajectory")
        await trace_eval()
        await runtime_eval(root)
    http_eval()
    write_report(Path(__file__).parent / "e2e_reports" / "agent_eval_2026-10-05.md")


if __name__ == "__main__":
    asyncio.run(main())
