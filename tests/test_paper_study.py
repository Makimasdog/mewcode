from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from mewcode.agent import Agent
from mewcode.agents.loader import AgentLoader
from mewcode.agents.tool_filter import resolve_agent_tools
from mewcode.tools import create_default_registry
from mewcode.tools.bash import Bash, Params as BashParams
from mewcode.tools.agent_tool import AgentTool


def test_paper_workers_can_run_their_stages(tmp_path: Path) -> None:
    loader = AgentLoader(str(tmp_path), enable_verification=True)
    agents = loader.load_all()
    parent_registry = create_default_registry()

    expected = {
        "PaperSearch": (16, {"ReadFile", "Bash"}, {"WriteFile", "EditFile"}),
        "PaperProtocol": (8, {"WriteFile", "Bash"}, {"EditFile"}),
        "PaperStudy": (40, {"ReadFile", "WriteFile", "EditFile", "Bash"}, set()),
        "Verification": (24, {"ReadFile", "Bash"}, {"WriteFile", "EditFile"}),
    }
    for name, (turns, required, excluded) in expected.items():
        definition = agents[name]
        assert definition.background is True
        assert definition.permission_mode == "dontAsk"
        assert definition.max_turns == turns
        assert definition.isolation == ""
        tools = {
            tool.name
            for tool in resolve_agent_tools(parent_registry, definition, is_background=True).list_tools()
        }
        assert required <= tools
        assert excluded.isdisjoint(tools)


def test_concurrent_agents_bind_bash_to_their_own_work_dirs(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()

    async def run() -> tuple[str, str]:
        parent = create_default_registry()
        left_registry = resolve_agent_tools(
            parent, AgentLoader(str(tmp_path)).load_all()["PaperSearch"], is_background=True
        )
        right_registry = resolve_agent_tools(
            parent, AgentLoader(str(tmp_path)).load_all()["PaperSearch"], is_background=True
        )
        Agent(object(), left_registry, "anthropic", work_dir=str(left))
        Agent(object(), right_registry, "anthropic", work_dir=str(right))
        left_bash = left_registry.get("Bash")
        right_bash = right_registry.get("Bash")
        assert isinstance(left_bash, Bash)
        assert isinstance(right_bash, Bash)
        assert left_bash is not right_bash
        command = f'"{sys.executable}" -c "import os; print(os.path.basename(os.getcwd()))"'
        results = await asyncio.gather(
            left_bash.execute(BashParams(command=command)),
            right_bash.execute(BashParams(command=command)),
        )
        assert all(not result.is_error for result in results)
        return results[0].output, results[1].output

    left_output, right_output = asyncio.run(run())
    assert "STDOUT:\nleft" in left_output
    assert "STDOUT:\nright" in right_output


def test_paper_stages_wait_for_successful_prerequisites() -> None:
    parent = MagicMock(coordinator_mode=True)
    manager = MagicMock()
    tool = AgentTool(MagicMock(), manager, MagicMock(), parent)

    assert tool._paper_stage_block("PaperSearch") is None
    assert tool._paper_stage_block("Verification") is None
    assert tool._paper_stage_block("PaperProtocol").is_error

    tool._paper_stage_tasks["PaperSearch"] = ["search-1"]
    manager.get.return_value = SimpleNamespace(status="running")
    assert tool._paper_stage_block("PaperProtocol").is_error
    manager.get.return_value = SimpleNamespace(status="failed")
    assert tool._paper_stage_block("PaperProtocol").is_error
    manager.get.return_value = SimpleNamespace(status="completed")
    assert tool._paper_stage_block("PaperProtocol") is None

    assert tool._paper_stage_block("PaperStudy").is_error
    tool._paper_stage_tasks["PaperProtocol"] = ["protocol-1"]
    assert tool._paper_stage_block("PaperStudy") is None
    assert tool._paper_stage_block("Verification").is_error
    tool._paper_stage_tasks["PaperStudy"] = ["study-1"]
    assert tool._paper_stage_block("Verification") is None
