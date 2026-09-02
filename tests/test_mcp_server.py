import json
from pathlib import Path

import anyio
import pytest

from pasr.mcp.server import create_server


def _call(server, tool: str, arguments: dict):
    return anyio.run(lambda: server.call_tool(tool, arguments))


def test_lists_all_three_tools_with_schemas(mini_workspace: Path):
    server = create_server(mini_workspace)
    tools = {tool.name: tool for tool in anyio.run(server.list_tools)}

    assert set(tools) == {"select_context", "trace_dependencies", "explain_selection"}
    props = set(tools["select_context"].input_schema.get("properties", {}))
    assert {"query", "files", "include", "budget_tokens", "prefix_tokens", "tail_tokens"} <= props


def test_select_context_returns_a_parseable_pack_with_a_receipt(mini_workspace: Path):
    server = create_server(mini_workspace)
    result = _call(
        server,
        "select_context",
        {"query": "emit rate limit headers on the response", "include": ["api/ratelimit.py"], "budget_tokens": 2000},
    )

    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["tool"] == "select_context"
    assert payload["route"] in {"lossless", "selected"}
    assert payload["token_count"] <= payload["budget_tokens"]
    assert payload["sources"] == ["api/ratelimit.py"]
    assert all(span["provenance"] for span in payload["spans"])
    assert (mini_workspace / ".pasr" / "receipts" / f"{payload['receipt']['id']}.json").is_file()


def test_workspace_escape_is_a_clean_tool_error(mini_workspace: Path):
    server = create_server(mini_workspace)
    with pytest.raises(Exception, match="escapes workspace"):
        _call(server, "select_context", {"query": "x", "files": ["../secrets.py"]})


def test_tiny_budget_does_not_crash_and_drops_the_window(mini_workspace: Path):
    server = create_server(mini_workspace)
    result = _call(
        server,
        "select_context",
        {"query": "throttling", "include": ["api/ratelimit.py"], "budget_tokens": 50, "block_size": 400},
    )
    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["route"] == "selected"
    assert payload["diagnostics"]["active_window"] is False
    assert "active_window_dropped" in payload["diagnostics"]
    assert payload["token_count"] <= 50


def test_select_context_is_deterministic(mini_workspace: Path):
    server = create_server(mini_workspace)
    args = {"query": "compromised account session", "include": ["."], "budget_tokens": 120, "block_size": 30}
    a = json.loads(_call(server, "select_context", args).content[0].text)
    b = json.loads(_call(server, "select_context", args).content[0].text)
    assert a == b


def test_trace_dependencies_returns_a_closure(trace_workspace: Path):
    server = create_server(trace_workspace)
    result = _call(server, "trace_dependencies", {"symbol": "run_pipeline", "include": ["app"]})

    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["tool"] == "trace_dependencies"
    assert payload["found"] is True
    assert {"run_pipeline", "load", "parse"} <= {span["name"] for span in payload["spans"]}
    assert payload["token_reduction"] > 0.0


def test_trace_dependencies_missing_symbol_is_not_an_error(trace_workspace: Path):
    server = create_server(trace_workspace)
    result = _call(server, "trace_dependencies", {"symbol": "nope", "include": ["app"]})
    assert result.is_error is False
    assert json.loads(result.content[0].text)["found"] is False


def test_explain_selection_returns_the_stored_receipt(mini_workspace: Path):
    server = create_server(mini_workspace)
    select = json.loads(
        _call(
            server,
            "select_context",
            {"query": "rate limit headers", "include": ["."], "budget_tokens": 120, "block_size": 30},
        )
        .content[0]
        .text
    )
    receipt_id = select["receipt"]["id"]

    result = _call(server, "explain_selection", {"receipt_id": receipt_id})
    assert result.is_error is False
    receipt = json.loads(result.content[0].text)
    assert receipt["id"] == receipt_id
    assert "kept" in receipt and "dropped" in receipt
    assert {span["provenance"] for span in receipt["kept"]} == {span["provenance"] for span in select["spans"]}


def test_explain_selection_unknown_id_is_a_clean_error(mini_workspace: Path):
    server = create_server(mini_workspace)
    with pytest.raises(Exception, match="no receipt with id"):
        _call(server, "explain_selection", {"receipt_id": "deadbeef0000"})
