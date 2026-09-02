import json
from pathlib import Path

import anyio
import pytest

from pasr.mcp.server import create_server

MINI_REPO = Path(__file__).parent / "fixtures" / "mini_repo"


def _call(server, arguments: dict):
    return anyio.run(lambda: server.call_tool("select_context", arguments))


def test_lists_the_select_context_tool_with_its_schema():
    server = create_server(MINI_REPO)
    tools = {tool.name: tool for tool in anyio.run(server.list_tools)}

    assert set(tools) == {"select_context", "trace_dependencies"}
    props = set(tools["select_context"].input_schema.get("properties", {}))
    assert {"query", "files", "include", "budget_tokens", "prefix_tokens", "tail_tokens"} <= props


def test_call_tool_returns_a_parseable_context_pack():
    server = create_server(MINI_REPO)
    result = _call(
        server,
        {"query": "emit rate limit headers on the response", "include": ["api/ratelimit.py"], "budget_tokens": 2000},
    )

    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["tool"] == "select_context"
    assert payload["route"] in {"lossless", "selected"}
    assert payload["token_count"] <= payload["budget_tokens"]
    assert payload["sources"] == ["api/ratelimit.py"]
    assert payload["spans"]
    assert all(span["provenance"] for span in payload["spans"])


def test_workspace_escape_is_a_clean_tool_error():
    server = create_server(MINI_REPO)
    with pytest.raises(Exception, match="escapes workspace"):
        _call(server, {"query": "x", "files": ["../secrets.py"]})


def test_tiny_budget_does_not_crash_and_drops_the_window():
    server = create_server(MINI_REPO)
    result = _call(
        server,
        {"query": "throttling", "include": ["api/ratelimit.py"], "budget_tokens": 50, "block_size": 400},
    )

    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["route"] == "selected"
    assert payload["diagnostics"]["active_window"] is False
    assert "active_window_dropped" in payload["diagnostics"]
    assert payload["token_count"] <= 50


def test_call_is_deterministic():
    server = create_server(MINI_REPO)
    args = {"query": "compromised account session", "include": ["."], "budget_tokens": 120, "block_size": 30}
    assert json.loads(_call(server, args).content[0].text) == json.loads(_call(server, args).content[0].text)


TRACE_REPO = Path(__file__).parent / "fixtures" / "trace_repo"


def test_trace_dependencies_tool_is_listed_and_returns_a_closure():
    server = create_server(TRACE_REPO)
    tools = anyio.run(server.list_tools)
    assert {"select_context", "trace_dependencies"} == {tool.name for tool in tools}

    result = anyio.run(lambda: server.call_tool("trace_dependencies", {"symbol": "run_pipeline", "include": ["app"]}))
    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["tool"] == "trace_dependencies"
    assert payload["found"] is True
    names = {span["name"] for span in payload["spans"]}
    assert {"run_pipeline", "load", "parse"} <= names
    assert payload["token_reduction"] > 0.0


def test_trace_dependencies_missing_symbol_is_not_an_error():
    server = create_server(TRACE_REPO)
    result = anyio.run(lambda: server.call_tool("trace_dependencies", {"symbol": "nope", "include": ["app"]}))
    assert result.is_error is False
    assert json.loads(result.content[0].text)["found"] is False
