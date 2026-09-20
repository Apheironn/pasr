import ast
import importlib.util
import json
from pathlib import Path

import anyio
import pytest

from pasr.mcp.server import create_server


def _call(server, tool: str, arguments: dict):
    return anyio.run(lambda: server.call_tool(tool, arguments))


def test_lists_all_tools_with_schemas(mini_workspace: Path):
    server = create_server(mini_workspace)
    tools = {tool.name: tool for tool in anyio.run(server.list_tools)}

    assert set(tools) == {
        "find_files",
        "find_evidence",
        "find_symbols",
        "find_usages",
        "select_context",
        "trace_dependencies",
        "explain_selection",
        "expand_context",
    }
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


def test_trace_dependencies_callers_direction(trace_workspace: Path):
    server = create_server(trace_workspace)
    result = _call(server, "trace_dependencies", {"symbol": "normalize", "include": ["app"], "direction": "callers"})
    payload = json.loads(result.content[0].text)
    assert payload["direction"] == "callers"
    assert "run_pipeline" in {span["name"] for span in payload["spans"]}


def test_trace_dependencies_rejects_bad_direction(trace_workspace: Path):
    server = create_server(trace_workspace)
    with pytest.raises(Exception, match="direction"):
        _call(server, "trace_dependencies", {"symbol": "normalize", "direction": "sideways"})


def test_select_context_map_tokens_and_trace_stay_within_budget(mini_workspace: Path):
    server = create_server(mini_workspace)
    payload = json.loads(
        _call(
            server,
            "select_context",
            {
                "query": "deduplicate near identical documents by shingle fingerprint",
                "include": ["."],
                "budget_tokens": 400,
                "block_size": 30,
                "map_tokens": 90,
                "trace": "deduplicate_near_identical_documents_by_shingle_fingerprint",
            },
        )
        .content[0]
        .text
    )
    assert payload["route"] == "selected"
    assert payload["context"].startswith("# symbol map\n")
    assert "# dependency closure (" in payload["context"]
    assert payload["token_count"] <= 400
    assert payload["diagnostics"]["symbol_map"]["header_tokens"] > 0
    assert payload["diagnostics"]["trace"]["found"] is True


def test_select_context_appends_a_ledger_row(mini_workspace: Path):
    from pasr.ledger import read_ledger

    server = create_server(mini_workspace)
    _call(server, "select_context", {"query": "rate limit headers", "include": ["."], "budget_tokens": 200})
    rows = read_ledger(mini_workspace)
    assert len(rows) == 1 and rows[0]["source"] == "mcp"


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


def test_expand_context_widens_a_prior_selection_once(mini_workspace: Path):
    server = create_server(mini_workspace)
    first = json.loads(
        _call(
            server,
            "select_context",
            {"query": "rate limit headers", "include": ["."], "budget_tokens": 100, "block_size": 30},
        )
        .content[0]
        .text
    )
    result = _call(server, "expand_context", {"receipt_id": first["receipt"]["id"], "extra_budget": 300})
    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["budget_tokens"] == 400
    assert payload["token_count"] <= 400
    assert payload["expanded_from"] == first["receipt"]["id"]


def test_expand_context_rejects_non_positive_budget(mini_workspace: Path):
    server = create_server(mini_workspace)
    with pytest.raises(Exception, match="extra_budget"):
        _call(server, "expand_context", {"receipt_id": "deadbeef0000", "extra_budget": 0})


def test_select_context_saves_and_loads_a_pack(mini_workspace: Path):
    server = create_server(mini_workspace)
    saved = json.loads(
        _call(
            server,
            "select_context",
            {
                "query": "emit rate limit headers on the response",
                "include": ["api/ratelimit.py"],
                "budget_tokens": 2000,
                "save_as": "rl",
            },
        )
        .content[0]
        .text
    )
    assert saved["saved_pack"].endswith("rl.json")
    assert (mini_workspace / ".pasr" / "packs" / "rl.json").is_file()

    loaded = json.loads(_call(server, "select_context", {"query": "", "pack": "rl"}).content[0].text)
    assert loaded["from_pack"] == "rl"
    assert loaded["context"] == saved["context"]
    assert loaded["pack_stale"] == []


def test_select_context_unknown_pack_is_a_clean_error(mini_workspace: Path):
    server = create_server(mini_workspace)
    with pytest.raises(Exception, match="no pack named"):
        _call(server, "select_context", {"query": "", "pack": "ghost"})


def test_identical_calls_stay_deterministic_then_stop(mini_workspace: Path):
    """Repeats return the same bytes (receipts stay reproducible) until the loop rule fires."""
    server = create_server(mini_workspace)
    args = {"query": "session cookie rotation", "include": ["auth"], "budget_tokens": 400}

    first = json.loads(_call(server, "select_context", args).content[0].text)
    second = json.loads(_call(server, "select_context", args).content[0].text)
    assert first == second, "identical calls must stay byte-identical while allowed"

    with pytest.raises(Exception, match="cannot add evidence"):
        _call(server, "select_context", args)


def test_find_symbols_returns_definition_provenance(mini_workspace: Path):
    server = create_server(mini_workspace)
    result = _call(server, "find_symbols", {"query": "rate_limit"})

    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["matches"], payload
    assert all(":" in match["provenance"] for match in payload["matches"])


def test_reworded_queries_over_the_same_spans_stop_too(mini_workspace: Path):
    """The expensive loop is the paraphrased one: new wording, same spans, new receipt id."""
    server = create_server(mini_workspace)
    base = {"include": ["api/ratelimit.py"], "budget_tokens": 3000}

    first = json.loads(_call(server, "select_context", {"query": "rate limit headers", **base}).content[0].text)
    assert first["spans"], "fixture should return spans"

    # Different query strings, so the byte-identical guard never fires -- but the same
    # file fits the budget losslessly, so no call after the first adds any evidence.
    _call(server, "select_context", {"query": "throttling behaviour on responses", **base})
    with pytest.raises(Exception, match="Refused") as refusal:
        _call(server, "select_context", {"query": "how are 429s emitted", **base})
    # The refusal has to say what the caller already holds, or it is just a wall.
    assert "line(s) of source across" in str(refusal.value)


def test_novel_spans_reset_the_stopping_rule(mini_workspace: Path):
    server = create_server(mini_workspace)
    _call(server, "select_context", {"query": "rate limit", "include": ["api/ratelimit.py"], "budget_tokens": 3000})
    _call(server, "select_context", {"query": "rate limits", "include": ["api/ratelimit.py"], "budget_tokens": 3000})

    # A different file is new evidence: the counter resets instead of refusing.
    result = _call(
        server, "select_context", {"query": "session", "include": ["auth/session.py"], "budget_tokens": 3000}
    )
    assert result.is_error is False


def test_a_mostly_repeated_slice_counts_as_no_progress(mini_workspace: Path):
    """Re-reading a file at a nudged budget returns a few unseen lines; that is not progress."""
    server = create_server(mini_workspace)
    base = {"include": ["api/ratelimit.py"]}

    _call(server, "select_context", {"query": "rate limit headers", "budget_tokens": 2000, **base})
    _call(server, "select_context", {"query": "throttling responses", "budget_tokens": 2100, **base})
    with pytest.raises(Exception, match="already"):
        _call(server, "select_context", {"query": "429 emission", "budget_tokens": 2200, **base})


def test_find_evidence_names_the_words_that_appear_nowhere(mini_workspace: Path):
    """Knowing a word is absent bounds the search; without it an agent tries synonyms forever."""
    server = create_server(mini_workspace)
    result = _call(server, "find_evidence", {"query": "ratelimit kubernetes helm"})

    payload = json.loads(result.content[0].text)
    assert payload["term_file_counts"]["kubernetes"] == 0
    assert any("kubernetes" in line for line in payload["advice"])
    assert payload["hits"], "the real term should still return hits"


@pytest.fixture(params=["mcp", "benchmark"])
def locator_surface(request, tmp_path: Path):
    if request.param == "mcp":
        server = create_server(tmp_path)

        def call(name, arguments):
            result = _call(server, name, arguments)
            assert not result.is_error
            return json.loads(result.content[0].text)

    else:
        # Load a fresh benchmark session so its repetition guard cannot leak between tests.
        path = Path(__file__).parents[1] / "eval" / "agent_bench" / "tools_pasr.py"
        spec = importlib.util.spec_from_file_location("locator_benchmark", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.WORKSPACE = tmp_path

        def call(name, arguments):
            return json.loads(module.run_pasr(name, arguments))

    return call


def test_exact_symbol_advice_executes_a_definition_only_read(tmp_path: Path, locator_surface):
    definition = "def calculate(value):\n    doubled = value * 2\n    return doubled\n"
    (tmp_path / "worker.py").write_text(
        "UNRELATED_PREFIX = 1\n\n" + definition + "\nUNRELATED_SUFFIX = 2\n", encoding="utf-8"
    )

    found = locator_surface("find_symbols", {"query": "calculate"})
    advice = next(note for note in found["advice"] if "select_context(" in note)
    expression = "select_context(" + advice.partition("select_context(")[2].rsplit(").", 1)[0] + ")"
    call = ast.parse(expression, mode="eval").body
    arguments = {keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords}

    selected = locator_surface("select_context", arguments)

    assert definition.rstrip() in selected["context"]
    assert "UNRELATED_PREFIX" not in selected["context"]
    assert "UNRELATED_SUFFIX" not in selected["context"]


@pytest.mark.parametrize("tool", ["find_evidence", "find_usages"])
def test_locator_read_lines_fetch_complete_small_function(tmp_path: Path, locator_surface, tool: str):
    definition = "def calculate(value):\n    checkpoint(value)\n    return value * 2\n"
    (tmp_path / "worker.py").write_text(
        "UNRELATED_PREFIX = 1\n\n" + definition + "\nUNRELATED_SUFFIX = 2\n", encoding="utf-8"
    )
    arguments = {"query": "checkpoint"} if tool == "find_evidence" else {"symbol": "checkpoint"}

    found = locator_surface(tool, arguments)
    hit = found["hits"][0]
    selector = f"{hit['provenance'].rsplit(':', 1)[0]}:{hit['read_lines']}"
    selected = locator_surface("select_context", {"query": "checkpoint", "files": [selector]})

    assert definition.rstrip() in selected["context"]
    assert "UNRELATED_PREFIX" not in selected["context"]
    assert "UNRELATED_SUFFIX" not in selected["context"]


def test_read_lines_guidance_preserves_absence_and_truncation_warnings(tmp_path: Path, locator_surface):
    (tmp_path / "worker.py").write_text("def checkpoint():\n    return 1\n\ncheckpoint()\n", encoding="utf-8")

    evidence = locator_surface("find_evidence", {"query": "checkpoint absentmarker"})
    assert evidence["term_file_counts"]["absentmarker"] == 0
    assert any("absentmarker" in note for note in evidence["advice"])
    assert evidence["hits"][0]["read_lines"] == "1-2"
    # One composed example the caller can copy, rather than a rule to apply per hit.
    assert any('files=["worker.py:1-2"]' in note for note in evidence["advice"])

    usages = locator_surface("find_usages", {"symbol": "checkpoint", "top_k": 1})
    assert usages["truncated"] is True
    assert usages["definition_count"] == 1
    assert usages["usage_count"] == 1
    assert [hit["provenance"] for hit in usages["hits"]] == ["worker.py:1"]
    assert any("top_k" in note for note in usages["advice"])
    # The read hint lives in the tool description, sent once -- not in every result.
    assert not any("read_lines" in note for note in usages["advice"])


@pytest.mark.parametrize("tool", ["find_evidence", "find_usages"])
def test_only_the_leading_hits_carry_read_lines(tmp_path: Path, locator_surface, tool: str):
    body = "".join(f"def checkpoint{index}():\n    checkpoint()\n\n" for index in range(8))
    (tmp_path / "worker.py").write_text(body, encoding="utf-8")
    arguments = {"query": "checkpoint", "per_file": 8} if tool == "find_evidence" else {"symbol": "checkpoint"}

    hits = locator_surface(tool, {**arguments, "top_k": 8})["hits"]

    assert len(hits) == 8
    assert [("read_lines" in hit) for hit in hits] == [True] * 5 + [False] * 3


def test_a_reread_inside_lines_already_held_is_caught(mini_workspace: Path):
    """Overlapping ranges are different strings and almost the same evidence."""
    server = create_server(mini_workspace)
    first = json.loads(
        _call(server, "select_context", {"query": "rate limit", "include": ["."], "budget_tokens": 3000})
        .content[0]
        .text
    )
    held = [span["provenance"] for span in first["spans"]]
    assert held, "fixture should return spans"

    # Ask again for lines strictly inside what was already delivered, under new wording and
    # a new receipt id each time. Counting provenance strings called these wholly new.
    inner = [p.rsplit(":", 1)[0] + ":" + str(int(p.rsplit(":", 1)[1].split("-")[0]) + 1) for p in held[:2]]
    _call(server, "select_context", {"query": "throttle behaviour", "files": inner, "budget_tokens": 3000})
    with pytest.raises(Exception, match="already hold"):
        _call(server, "select_context", {"query": "429 emission", "files": inner, "budget_tokens": 3000})


def test_a_session_is_told_what_it_holds_before_it_is_refused(mini_workspace: Path):
    server = create_server(mini_workspace)
    server_call = lambda q, inc: json.loads(  # noqa: E731
        _call(server, "select_context", {"query": q, "include": inc, "budget_tokens": 400}).content[0].text
    )
    first = server_call("rate limit headers", ["api/ratelimit.py"])
    # Nothing to boast about after one file.
    assert not any("You now hold" in note for note in first.get("advice", []))

    second = server_call("session compromise", ["."])
    assert any("line(s) of source across" in note for note in second.get("advice", []))
