from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from mewcode.tools.agent_tool import AgentTool


def _tool(coordinator: bool = True) -> AgentTool:
    tool = object.__new__(AgentTool)
    tool._parent_agent = SimpleNamespace(coordinator_mode=coordinator)
    tool._task_manager = MagicMock()
    tool._paper_stage_tasks = {}
    return tool


def test_coordinator_blocks_paper_stages_until_prerequisite_completes() -> None:
    tool = _tool()

    blocked = tool._paper_stage_block("PaperProtocol")

    assert blocked is not None and blocked.is_error
    assert "PaperSearch" in blocked.output


def test_coordinator_allows_stage_after_successful_notification() -> None:
    tool = _tool()
    tool._paper_stage_tasks["PaperSearch"] = ["search-1"]
    tool._task_manager.get.return_value = SimpleNamespace(status="completed")

    assert tool._paper_stage_block("PaperProtocol") is None


def test_non_coordinator_verification_is_unaffected() -> None:
    tool = _tool(coordinator=False)

    assert tool._paper_stage_block("PaperProtocol") is None
