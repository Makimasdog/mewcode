from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mewcode.tools.base import ToolResult
from mewcode.runtime.dag import DAGNode
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


def test_verification_pass_is_rejected_by_artifact_audit(tmp_path: Path) -> None:
    paper = tmp_path / "paper_repro" / "demo"
    (paper / "results").mkdir(parents=True)
    (paper / "protocol.md").write_text(
        "exactly 1000 distance calculations\n", encoding="utf-8"
    )
    (paper / "results" / "result.json").write_text(
        json.dumps(
            {
                "data_rows": 1000,
                "counts": [500, 503],
                "distance_calculations": 3000,
                "algorithm_compliance": True,
            }
        ),
        encoding="utf-8",
    )

    class FakeAgentTool:
        async def execute(self, params):
            return ToolResult(
                output="COMMAND: python verify.py\nEXIT CODE: 0\nFILES: results/result.json exists\nVERDICT: PASS"
            )

    tool = DAGCreateTool(FakeAgentTool(), work_dir=str(tmp_path))
    params = DAGCreateParams(
        name="paper-audit",
        nodes=[DAGNodeInput(id="verify", prompt="verify", subagent_type="Verification")],
    )

    result = asyncio.run(tool.execute(params))

    assert result.is_error
    assert "distance_mismatch" in result.output.lower()


def test_missing_optional_paper_section_does_not_block_protocol() -> None:
    DAGCreateTool._validate_dependency_evidence(
        DAGNode(id="protocol", task="", agent_type="PaperProtocol"),
        {"search": "HTTP STATUS: 200\nSECTION 3.4 EXCERPT: NOT FOUND"},
    )


def test_paper_workers_receive_protocol_fingerprint(tmp_path: Path) -> None:
    paper = tmp_path / "paper_repro" / "demo"
    paper.mkdir(parents=True)
    (paper / "protocol.md").write_text("protocol\n", encoding="utf-8")

    tool = DAGCreateTool(object(), work_dir=str(tmp_path))
    context = tool._protocol_context("PaperStudy")

    assert "ACTIVE PROTOCOL" in context
    assert "PROTOCOL SHA-256:" in context
    assert tool._protocol_context("general-purpose") == ""
