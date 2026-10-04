from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from mewcode.kmeans_check import compare, make_datasets, reference, verify
from mewcode.paper_workflow import build_dag
from mewcode.tools.base import ToolResult
from mewcode.tools.dag_tools import DAGCreateParams, DAGCreateTool, DAGNodeInput


def test_online_reference_hand_calculated_tie_and_counts():
    actual = reference([[0.0], [2.0], [1.0]], 2)
    assert actual == {
        "centroids": [[0.5], [2.0]], "counts": [2, 1], "stream_labels": [0, 1, 0],
        "assignments": [0, 1, 0], "inertia": 0.5, "distance_calculations": 2, "data_rows": 3,
    }
    duplicate = reference([[0.0], [0.0], [4.0], [8.0]], 2)
    assert duplicate["centroids"] == [[4.0], [0.0]]
    assert duplicate["stream_labels"] == [0, 1, 0, 0]
    assert duplicate["assignments"] == [1, 1, 0, 0]
    assert duplicate["inertia"] == 16.0


def test_scramble_preserves_marginals_and_ring_distribution():
    data = make_datasets()
    points = data["datasets"]["original"]
    assert len(points) == 150
    assert all(30 <= max(map(abs, row)) <= 50 for row in points)
    assert len(data["datasets"]) == 20
    for scrambled in data["datasets"].values():
        for j in range(2):
            assert sorted(row[j] for row in scrambled) == sorted(row[j] for row in points)


def test_checker_rejects_fabricated_metrics_and_wrong_implementation(tmp_path):
    data = make_datasets()
    (tmp_path / "data.json").write_text(json.dumps(data), encoding="utf-8")
    results = {"runs": {name: reference(points, 12) for name, points in data["datasets"].items()}}
    results["runs"]["original"]["inertia"] = -1.0
    result_path = tmp_path / "results.json"
    result_path.write_text(json.dumps(results), encoding="utf-8")
    with pytest.raises(ValueError, match="original.inertia"):
        verify(tmp_path)
    results["runs"]["original"] = reference(data["datasets"]["original"], 12)
    result_path.write_text(json.dumps(results), encoding="utf-8")
    (tmp_path / "run.py").write_text("def online_kmeans(points, k):\n    return {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fixture 0"):
        verify(tmp_path)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_checker_rejects_nonfinite_numbers(value):
    with pytest.raises(ValueError):
        compare(value, 1.0, "metric")


def test_preset_has_all_four_stages_and_exact_dependency_chain(tmp_path):
    dag = build_dag(tmp_path)
    assert [node.id for node in dag.nodes] == ["search", "protocol", "study", "verification"]
    assert [node.depends_on for node in dag.nodes] == [[], ["search"], ["protocol"], ["study"]]
    assert dag.artifact_dir == tmp_path.as_posix()
    assert dag.max_parallel == 1


def test_protocol_mutation_blocks_downstream_verification(tmp_path: Path):
    root = tmp_path / "experiment"
    root.mkdir()
    calls = []

    class Worker:
        async def execute(self, params):
            calls.append(params.subagent_type)
            (root / "protocol.md").write_text(params.subagent_type, encoding="utf-8")
            return ToolResult("Done")

    tool = DAGCreateTool(Worker(), work_dir=str(tmp_path))
    result = asyncio.run(tool.execute(DAGCreateParams(artifact_dir="experiment", nodes=[
        DAGNodeInput(id="protocol", prompt="protocol", subagent_type="PaperProtocol"),
        DAGNodeInput(id="study", prompt="study", subagent_type="PaperStudy", depends_on=["protocol"]),
        DAGNodeInput(id="verify", prompt="verify", subagent_type="Verification", depends_on=["study"]),
    ])))
    assert result.is_error
    assert "Protocol changed" in result.output
    assert calls == ["PaperProtocol", "PaperStudy"]


def test_pass_prose_does_not_override_nonzero_exit(tmp_path):
    class Worker:
        async def execute(self, params):
            return ToolResult("COMMAND: python bad.py\nEXIT CODE: 1\nVERDICT: PASS")

    tool = DAGCreateTool(Worker(), work_dir=str(tmp_path))
    result = asyncio.run(tool.execute(DAGCreateParams(nodes=[
        DAGNodeInput(id="verify", prompt="verify", subagent_type="Verification"),
    ])))
    assert result.is_error
    assert "nonzero EXIT CODE" in result.output


def test_explicit_artifact_root_ignores_newer_unrelated_protocol(tmp_path):
    selected = tmp_path / "selected"
    selected.mkdir()
    (selected / "protocol.md").write_text("selected protocol", encoding="utf-8")
    unrelated = tmp_path / "paper_repro" / "unrelated"
    unrelated.mkdir(parents=True)
    (unrelated / "protocol.md").write_text("unrelated protocol", encoding="utf-8")
    tool = DAGCreateTool(object(), work_dir=str(tmp_path))
    context = tool._protocol_context("PaperStudy", selected)
    assert str(selected / "protocol.md") in context
    assert str(unrelated) not in context


def test_iteration_exhaustion_is_failure_not_a_successful_partial_answer(tmp_path):
    from mewcode.agent import Agent
    from mewcode.tools import create_default_registry
    from mewcode.tools.base import StreamEnd, ToolCallComplete, TextDelta

    class EndlessClient:
        async def stream(self, *args, **kwargs):
            yield TextDelta("Still working")
            yield ToolCallComplete("t", "ReadFile", {"file_path": str(tmp_path / "missing")})
            yield StreamEnd("tool_use")

    agent = Agent(EndlessClient(), create_default_registry(), "openai-compat",
                  work_dir=str(tmp_path), max_iterations=2)
    with pytest.raises(RuntimeError, match="exceeded 2 iterations"):
        asyncio.run(agent.run_to_completion("Loop"))


def test_resume_rejects_changed_inputs_before_any_api_call(tmp_path, monkeypatch):
    from mewcode.paper_workflow import MODEL, run_workflow
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")
    (tmp_path / "data.json").write_text("changed", encoding="utf-8")
    (tmp_path / "checkpoint.json").write_text(json.dumps({
        "model": MODEL, "input_hashes": {"data.json": "original-hash"},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="Immutable input changed"):
        asyncio.run(run_workflow(tmp_path, MODEL, "https://unused.invalid", resume=True))


def test_programmatic_verification_rejects_nonzero_even_with_pass_text(tmp_path):
    from mewcode.paper_workflow import digest, verify_execution
    (tmp_path / "protocol.md").write_text("protocol", encoding="utf-8")
    (tmp_path / "run.py").write_text("print('VERDICT: PASS')\nraise SystemExit(2)\n", encoding="utf-8")
    checkpoint = {"input_hashes": {}, "protocol_sha256": digest(tmp_path / "protocol.md")}
    with pytest.raises(ValueError, match="Command failed \\(2\\)"):
        asyncio.run(verify_execution(tmp_path, checkpoint))
    evidence = json.loads((tmp_path / "execution.json").read_text(encoding="utf-8"))
    assert evidence[0]["exit_code"] == 2


def test_audit_reads_nested_experiment_results_and_requires_metrics(tmp_path):
    from mewcode.paper_audit import audit_paper_artifacts
    (tmp_path / "protocol.md").write_text("distance_calculations = 2", encoding="utf-8")
    (tmp_path / "source.json").write_text('{"http_status":200}', encoding="utf-8")
    report = audit_paper_artifacts(tmp_path, artifact_root=tmp_path)
    assert not report.passed
    assert "NO_RESULTS" in report.render()
    result = reference([[0.0], [2.0], [1.0]], 2)
    result["counts"] = [2, 2]
    (tmp_path / "results.json").write_text(json.dumps({"runs": {"test": result}}), encoding="utf-8")
    report = audit_paper_artifacts(tmp_path, artifact_root=tmp_path)
    assert "COUNT_MISMATCH" in report.render()
