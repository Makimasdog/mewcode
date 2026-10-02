from __future__ import annotations

import asyncio
from pathlib import Path

from mewcode.tools.base import ToolResult
from mewcode.tools.dag_tools import DAGCreateParams, DAGCreateTool, DAGNodeInput


def test_dag_nodes_force_foreground_results(tmp_path: Path) -> None:
    calls = []

    class FakeAgentTool:
        async def execute(self, params):
            calls.append(params)
            if params.subagent_type == "Verification":
                return ToolResult(
                    output="COMMAND: python run.py\nEXIT CODE: 0\nFILES: run.py exists\nVERDICT: PASS"
                )
            return ToolResult(output=f"result:{params.description}")

    tool = DAGCreateTool(FakeAgentTool(), work_dir=str(tmp_path))
    params = DAGCreateParams(
        name="paper",
        max_parallel=1,
        nodes=[
            DAGNodeInput(id="study", prompt="study", subagent_type="PaperStudy"),
            DAGNodeInput(
                id="verify",
                prompt="verify",
                subagent_type="Verification",
                depends_on=["study"],
            ),
        ],
    )

    result = asyncio.run(tool.execute(params))

    assert not result.is_error
    assert len(calls) == 2
    assert all(call.force_foreground is True for call in calls)
    assert all(call.run_in_background is False for call in calls)


def test_paper_study_is_blocked_without_algorithm_evidence(tmp_path: Path) -> None:
    calls = []

    class FakeAgentTool:
        async def execute(self, params):
            calls.append(params)
            if params.subagent_type == "digest":
                return ToolResult(output="No protocol or algorithmic content was provided.")
            return ToolResult(output="should not run")

    tool = DAGCreateTool(FakeAgentTool(), work_dir=str(tmp_path))
    params = DAGCreateParams(
        name="paper-evidence-gate",
        max_parallel=1,
        nodes=[
            DAGNodeInput(id="digest", prompt="digest", subagent_type="digest"),
            DAGNodeInput(
                id="reproduce",
                prompt="reproduce",
                subagent_type="PaperStudy",
                depends_on=["digest"],
            ),
        ],
    )

    result = asyncio.run(tool.execute(params))

    assert result.is_error
    assert len(calls) == 1
    assert "insufficient" in result.output.lower()


def test_verification_pass_requires_command_evidence(tmp_path: Path) -> None:
    class FakeAgentTool:
        async def execute(self, params):
            if params.subagent_type == "reproduce":
                return ToolResult(output="implementation completed")
            return ToolResult(output="VERDICT: PASS; exit code 0; files exist")

    tool = DAGCreateTool(FakeAgentTool(), work_dir=str(tmp_path))
    params = DAGCreateParams(
        name="paper-verification-gate",
        max_parallel=1,
        nodes=[
            DAGNodeInput(id="reproduce", prompt="reproduce", subagent_type="reproduce"),
            DAGNodeInput(
                id="verify",
                prompt="verify",
                subagent_type="Verification",
                depends_on=["reproduce"],
            ),
        ],
    )

    result = asyncio.run(tool.execute(params))

    assert result.is_error
    assert "command/exit code" in result.output.lower()
