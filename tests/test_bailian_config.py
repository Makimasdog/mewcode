"""The shipped Bailian example must resolve its key and use Chat Completions."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mewcode.client import AuthenticationError, OpenAICompatClient, create_client
from mewcode.config import load_config
from mewcode.tools.agent_tool import AgentTool, AgentToolParams


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "paper-study-config.yaml"


def test_bailian_example_uses_compatible_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "example-only-key")

    provider = load_config(EXAMPLE).providers[0]
    client = create_client(provider)

    assert provider.name == "bailian"
    assert provider.protocol == "openai-compat"
    assert provider.model
    assert provider.resolve_api_key() == "example-only-key"
    assert isinstance(client, OpenAICompatClient)
    assert str(client._client.base_url) == "https://dashscope.aliyuncs.com/compatible-mode/v1/"


def test_bailian_example_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    provider = load_config(EXAMPLE).providers[0]

    assert provider.resolve_api_key() == ""
    with pytest.raises(AuthenticationError):
        create_client(provider)


def test_anthropic_model_alias_inherits_bailian_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "example-only-key")
    provider = load_config(EXAMPLE).providers[0]
    parent = MagicMock()
    tool = AgentTool(
        agent_loader=MagicMock(),
        task_manager=MagicMock(),
        trace_manager=MagicMock(),
        parent_agent=parent,
        provider_config=provider,
    )

    for alias in ("haiku", "sonnet", "opus"):
        params = AgentToolParams(prompt="search", description="paper", model=alias)
        assert tool._select_llm(params, MagicMock(model="inherit")) is parent.client
