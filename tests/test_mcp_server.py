import ast
import importlib.util
import json
import re
from pathlib import Path

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from pasr.mcp.server import ALL_TOOLS, create_server


def _call(server, tool: str, arguments: dict):
    return anyio.run(lambda: server.call_tool(tool, arguments))


def _labels(payload: dict) -> list[str]:
    """The `[path:start-end]` label on every piece of a selection's context."""
    return re.findall(r"(?m)^\[([^\]\n]+:\d+(?:-\d+)?)\]$", payload["context"])


def test_lists_all_tools_with_schemas(mini_workspace: Path):
    server = create_server(mini_workspace)
    tools = {tool.name: tool for tool in anyio.run(server.list_tools)}

    # The receipt and closure tools are opt-in: across 1,413 recorded runs they drew 24
    # calls between them while costing ~400 catalogue tokens on every turn.
    assert set(tools) == {"find_files", "find_evidence", "find_symbols", "find_usages", "select_context"}
    everything = {tool.name for tool in anyio.run(create_server(mini_workspace, expose=ALL_TOOLS).list_tools)}
    assert everything == set(tools) | {
        "trace_dependencies",
        "explain_selection",
        "expand_context",
        "search_code",
        "read_code",
    }
    props = set(tools["select_context"].input_schema.get("properties", {}))
    # The model-facing surface only. Every property here is re-sent in this tool's schema
    # on every turn, and across 6,176 recorded calls the model never once passed
    # prefix_tokens, tail_tokens, recall_strategy, semantic, map_tokens, trace, pack or
    # save_as -- they live behind `advanced` now, one schema entry instead of ten.
    assert {"query", "files", "include", "budget_tokens", "outline", "advanced"} == props


def test_select_context_advertises_its_required_query(mini_workspace: Path):
    """A schema-valid omission used to fail only after the model called the tool."""
    server = create_server(mini_workspace)
    schema = next(tool.input_schema for tool in anyio.run(server.list_tools) if tool.name == "select_context")
    assert "query" in schema.get("required", [])
    with pytest.raises(ToolError, match="query"):
        _call(server, "select_context", {"files": ["api/ratelimit.py"], "outline": True})


def test_find_evidence_spends_its_budget_on_files_not_on_repeat_lines(mini_workspace: Path):
    """What a search budget buys should be breadth.

    Trimming find_evidence to fewer hits while it still returned two lines per file halved
    the distinct files it reached, and the questions whose answer is spread over several
    files lost an anchor for it. One hit is enough to name a file -- the caller reads the
    region through `read_lines` anyway -- so the budget goes to another file instead.
    """
    from pasr.mcp.server import EVIDENCE_PER_FILE, EVIDENCE_TOP_K

    assert EVIDENCE_PER_FILE == 1, "a second line from a file the caller already has says nothing new"

    server = create_server(mini_workspace)
    hits = json.loads(_call(server, "find_evidence", {"query": "rate limit retry after"}).content[0].text)["hits"]
    assert hits
    assert len(hits) <= EVIDENCE_TOP_K
    sources = [str(hit["provenance"]).rsplit(":", 1)[0] for hit in hits]
    assert len(set(sources)) == len(sources), "the default must not spend two hits on one file"


def test_merging_touching_spans_loses_no_line_and_invents_none(mini_workspace: Path):
    """A file's chunk boundaries are scoring detail, not evidence.

    A lossless slice hands a file back in scored pieces, each repeating the whole path.
    Folding the touching ones together says the same thing for a fraction of the tokens --
    but spans do not arrive in line order, and assuming they did swallowed an earlier span
    and reported its range as the later one's. The invariant is the line set.
    """
    from pasr.mcp.server import _merge_adjacent

    def lines(rows):
        covered = set()
        for row in rows:
            source, _, span = str(row["provenance"]).rpartition(":")
            start, _, end = span.partition("-")
            covered.update((source, n) for n in range(int(start), int(end or start) + 1))
        return covered

    touching = [{"provenance": "a.rs:7-12"}, {"provenance": "a.rs:13-20"}, {"provenance": "a.rs:21-30"}]
    assert _merge_adjacent(touching) == [{"provenance": "a.rs:7-30"}]

    # out of order, and far apart: nothing may be folded away
    scattered = [{"provenance": "a.rs:29"}, {"provenance": "a.rs:9"}]
    assert lines(_merge_adjacent(scattered)) == lines(scattered)
    assert len(_merge_adjacent(scattered)) == 2

    # a span that merged with nothing keeps the exact string it was given
    assert _merge_adjacent([{"provenance": "a.rs:25"}]) == [{"provenance": "a.rs:25"}]

    # different files never merge, however adjacent the numbers look
    two_files = [{"provenance": "a.rs:1-5"}, {"provenance": "b.rs:6-9"}]
    assert _merge_adjacent(two_files) == two_files

    # and on a real selection the wire still covers exactly what the receipt kept
    server = create_server(mini_workspace, expose=ALL_TOOLS)
    payload = json.loads(
        _call(server, "select_context", {"query": "rate limit", "include": ["."], "budget_tokens": 400}).content[0].text
    )
    receipt = json.loads(_call(server, "explain_selection", {"receipt_id": payload["receipt"]["id"]}).content[0].text)
    assert lines({"provenance": label} for label in _labels(payload)) == lines(receipt["kept"])


def test_the_wire_says_each_span_once_and_the_receipt_still_says_everything(mini_workspace: Path):
    """A span row is a locator, not a second copy of the selection.

    `provenance` already reads `source:line_start-line_end`, so shipping those three
    beside it -- plus per-span accounting no caller acts on, and a claim's `support`
    restating span ids the same response just listed -- costs the caller that much on
    every remaining turn. None of it is lost: the receipt keeps the full record.
    """
    server = create_server(mini_workspace, expose=ALL_TOOLS)
    payload = json.loads(
        _call(
            server,
            "select_context",
            {"query": "emit rate limit headers", "include": ["api/ratelimit.py"], "budget_tokens": 2000},
        )
        .content[0]
        .text
    )

    # Every piece of the context says where it came from, once, in place -- a lossless slice
    # included -- so a span list beside it would only say it again.
    assert _labels(payload), "a selection still has to say where its source came from"
    assert payload["context"].startswith("[api/ratelimit.py:")
    assert "spans" not in payload
    # The lexical coverage audit is not on the wire: its own number tells "has the answer"
    # from "still looking" at chance, and `advice` already says in a sentence whatever it
    # had to say. Nor is the request echoed back, or the scorer's diagnostics. The receipt
    # still carries every bit of it.
    assert set(payload) <= {"route", "token_count", "total_input_tokens", "sources", "context", "advice", "receipt"}
    assert payload["advice"]

    receipt = json.loads(_call(server, "explain_selection", {"receipt_id": payload["receipt"]["id"]}).content[0].text)
    assert {"source", "line_start", "line_end", "token_count", "selection_reasons"} <= set(receipt["kept"][0])


def test_select_context_returns_a_parseable_pack_with_a_receipt(mini_workspace: Path):
    server = create_server(mini_workspace)
    result = _call(
        server,
        "select_context",
        {"query": "emit rate limit headers on the response", "include": ["api/ratelimit.py"], "budget_tokens": 2000},
    )

    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["route"] in {"lossless", "selected"}
    assert payload["token_count"] <= 2000
    assert payload["sources"] == ["api/ratelimit.py"]
    assert all(label.startswith("api/ratelimit.py:") for label in _labels(payload))
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
        {
            "query": "throttling",
            "include": ["api/ratelimit.py"],
            "budget_tokens": 50,
            "advanced": {"prefix_tokens": 128, "tail_tokens": 128},
        },
    )
    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["route"] == "selected"
    assert any("prefix/tail window" in note for note in payload["advice"])
    assert payload["token_count"] <= 50


def test_a_source_file_gets_no_mandatory_head_or_tail(tmp_path: Path):
    """The head of a source file is its imports, and the query should decide what is read.

    On the benchmark 42 of 52 selections carried a file's opening lines whatever was asked,
    a mean 381 tokens, re-sent on every later turn and paid again by every re-selection.
    """
    body = "".join(f"import module_{n}\n" for n in range(60))
    body += "".join(f"def helper_{n}(x):\n    return x + {n}\n\n" for n in range(80))
    body += "def retry_budget(attempts):\n    return attempts * 2\n"
    (tmp_path / "service.py").write_text(body, encoding="utf-8")
    server = create_server(tmp_path)
    payload = json.loads(
        _call(server, "select_context", {"query": "retry budget", "files": ["service.py"], "budget_tokens": 300})
        .content[0]
        .text
    )
    assert payload["route"] == "selected"
    assert "def retry_budget" in payload["context"]
    assert "import module_0" not in payload["context"]


def test_select_context_is_deterministic(mini_workspace: Path):
    server = create_server(mini_workspace)
    args = {
        "query": "compromised account session",
        "include": ["."],
        "budget_tokens": 120,
        "advanced": {"block_size": 30},
    }
    a = json.loads(_call(server, "select_context", args).content[0].text)
    b = json.loads(_call(create_server(mini_workspace), "select_context", args).content[0].text)
    assert a == b


def test_trace_dependencies_returns_a_closure(trace_workspace: Path):
    server = create_server(trace_workspace, expose=ALL_TOOLS)
    result = _call(server, "trace_dependencies", {"symbol": "run_pipeline", "include": ["app"]})

    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["tool"] == "trace_dependencies"
    assert payload["found"] is True
    assert {"run_pipeline", "load", "parse"} <= {span["name"] for span in payload["spans"]}
    assert payload["token_reduction"] > 0.0


def test_trace_dependencies_missing_symbol_is_not_an_error(trace_workspace: Path):
    server = create_server(trace_workspace, expose=ALL_TOOLS)
    result = _call(server, "trace_dependencies", {"symbol": "nope", "include": ["app"]})
    assert result.is_error is False
    assert json.loads(result.content[0].text)["found"] is False


def test_trace_dependencies_callers_direction(trace_workspace: Path):
    server = create_server(trace_workspace, expose=ALL_TOOLS)
    result = _call(server, "trace_dependencies", {"symbol": "normalize", "include": ["app"], "direction": "callers"})
    payload = json.loads(result.content[0].text)
    assert payload["direction"] == "callers"
    assert "run_pipeline" in {span["name"] for span in payload["spans"]}


def test_trace_dependencies_rejects_bad_direction(trace_workspace: Path):
    server = create_server(trace_workspace, expose=ALL_TOOLS)
    with pytest.raises(Exception, match="direction"):
        _call(server, "trace_dependencies", {"symbol": "normalize", "direction": "sideways"})


def test_select_context_map_tokens_and_trace_stay_within_budget(mini_workspace: Path):
    server = create_server(mini_workspace, expose=ALL_TOOLS)
    payload = json.loads(
        _call(
            server,
            "select_context",
            {
                "query": "deduplicate near identical documents by shingle fingerprint",
                "include": ["."],
                "budget_tokens": 400,
                "block_size": 30,
                "advanced": {
                    "map_tokens": 90,
                    "trace": "deduplicate_near_identical_documents_by_shingle_fingerprint",
                },
            },
        )
        .content[0]
        .text
    )
    assert payload["route"] == "selected"
    assert payload["context"].startswith("# symbol map\n")
    assert "# dependency closure (" in payload["context"]
    assert payload["token_count"] <= 400
    receipt = json.loads(_call(server, "explain_selection", {"receipt_id": payload["receipt"]["id"]}).content[0].text)
    assert receipt["request"]["map_tokens"] == 90


def test_select_context_appends_a_ledger_row(mini_workspace: Path):
    from pasr.ledger import read_ledger

    server = create_server(mini_workspace)
    _call(server, "select_context", {"query": "rate limit headers", "include": ["."], "budget_tokens": 200})
    rows = read_ledger(mini_workspace)
    assert len(rows) == 1 and rows[0]["source"] == "mcp"


def test_explain_selection_returns_the_stored_receipt(mini_workspace: Path):
    server = create_server(mini_workspace, expose=ALL_TOOLS)
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
    assert {span["provenance"] for span in receipt["kept"]} == set(_labels(select))


def test_explain_selection_unknown_id_is_a_clean_error(mini_workspace: Path):
    server = create_server(mini_workspace, expose=ALL_TOOLS)
    with pytest.raises(Exception, match="no receipt with id"):
        _call(server, "explain_selection", {"receipt_id": "deadbeef0000"})


def test_expand_context_widens_a_prior_selection_once(mini_workspace: Path):
    server = create_server(mini_workspace, expose=ALL_TOOLS)
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
    assert payload["token_count"] <= 400
    assert payload["expanded_from"] == first["receipt"]["id"]


def test_expand_context_rejects_non_positive_budget(mini_workspace: Path):
    server = create_server(mini_workspace, expose=ALL_TOOLS)
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
                "advanced": {"save_as": "rl"},
            },
        )
        .content[0]
        .text
    )
    assert saved["saved_pack"].endswith("rl.json")
    assert (mini_workspace / ".pasr" / "packs" / "rl.json").is_file()

    loaded = json.loads(_call(server, "select_context", {"query": "", "advanced": {"pack": "rl"}}).content[0].text)
    assert loaded["from_pack"] == "rl"
    assert loaded["context"] == saved["context"]
    assert loaded["pack_stale"] == []


def test_select_context_unknown_pack_is_a_clean_error(mini_workspace: Path):
    server = create_server(mini_workspace)
    with pytest.raises(Exception, match="no pack named"):
        _call(server, "select_context", {"query": "", "advanced": {"pack": "ghost"}})


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("find_files", {"query": "session", "include": ["auth"]}),
        ("find_symbols", {"query": "session"}),
        ("find_evidence", {"query": "session"}),
        ("find_usages", {"symbol": "session"}),
    ],
)
def test_identical_search_calls_remain_usable(mini_workspace: Path, tool: str, arguments: dict):
    server = create_server(mini_workspace)
    first = json.loads(_call(server, tool, arguments).content[0].text)
    for _ in range(12):
        assert json.loads(_call(server, tool, arguments).content[0].text) == first


def test_find_symbols_returns_definition_provenance(mini_workspace: Path):
    server = create_server(mini_workspace)
    result = _call(server, "find_symbols", {"query": "rate_limit"})

    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["matches"], payload
    assert all(":" in match["provenance"] for match in payload["matches"])


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
        # Load an isolated adapter configured for this workspace.
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

    usages = locator_surface("find_usages", {"symbol": "checkpoint", "top_k": 1})
    assert usages["truncated"] is True
    assert usages["definition_count"] == 1
    assert usages["usage_count"] == 1
    assert [hit["provenance"] for hit in usages["hits"]] == ["worker.py:1"]
    assert any("top_k" in note for note in usages["advice"])


@pytest.mark.parametrize("tool", ["find_evidence", "find_usages"])
def test_only_the_leading_hits_carry_read_lines(tmp_path: Path, locator_surface, tool: str):
    body = "".join(f"def checkpoint{index}():\n    checkpoint()\n\n" for index in range(8))
    (tmp_path / "worker.py").write_text(body, encoding="utf-8")
    arguments = {"query": "checkpoint", "per_file": 8} if tool == "find_evidence" else {"symbol": "checkpoint"}

    hits = locator_surface(tool, {**arguments, "top_k": 8})["hits"]

    assert len(hits) == 8
    assert [("read_lines" in hit) for hit in hits] == [True] * 5 + [False] * 3


def test_a_host_can_publish_only_the_tools_it_will_use(mini_workspace):
    """A catalogue entry is re-sent with every request, so an unused one is never free.

    Measured over 60 runs and 558 model turns: the catalogue is 1,971 tokens and 22% of
    every prompt token spent, and trace_dependencies, expand_context and explain_selection
    drew one call between them while costing 247,752 token-turns -- about 4,100 tokens a
    run to describe tools the model never chose.
    """
    from pasr.mcp.server import ALL_TOOLS, create_server

    everything = anyio.run(create_server(mini_workspace, expose=ALL_TOOLS).list_tools)
    assert {t.name for t in everything} == set(ALL_TOOLS)

    core = ("find_files", "find_symbols", "find_evidence", "find_usages", "select_context")
    narrowed = anyio.run(create_server(mini_workspace, expose=core).list_tools)
    assert {t.name for t in narrowed} == set(core)

    with pytest.raises(ValueError, match="nope"):
        create_server(mini_workspace, expose=["find_evidence", "nope"])

    # a tool that was not published cannot be called into through the back door
    server = create_server(mini_workspace, expose=["find_evidence"])
    with pytest.raises(ToolError, match="select_context"):
        anyio.run(lambda: server.call_tool("select_context", {"query": "x", "files": ["pkg/alpha.py"]}))


def test_one_wrong_path_no_longer_sinks_the_right_ones(mini_workspace: Path):
    """A guessed path used to fail the whole call, and the turn with it.

    On the nushell holdout five runs of twelve spent a turn learning that one of the files
    they asked for did not exist -- each turn re-sending the whole conversation. The real
    files are read, the wrong one is named, and a same-named file is offered for it.
    """
    server = create_server(mini_workspace)
    payload = json.loads(
        _call(
            server,
            "select_context",
            {"query": "rate limit", "files": ["api/ratelimit.py", "core/ratelimit.py"], "budget_tokens": 2000},
        )
        .content[0]
        .text
    )
    assert payload["sources"] == ["api/ratelimit.py"]
    assert "Not found, skipped: core/ratelimit.py (did you mean api/ratelimit.py?)" in payload["advice"][0]

    with pytest.raises(Exception, match="did you mean api/ratelimit.py"):
        _call(server, "select_context", {"query": "rate limit", "files": ["lib/ratelimit.py"]})
    with pytest.raises(Exception, match="escapes workspace"):
        _call(server, "select_context", {"query": "x", "files": ["api/ratelimit.py", "../secrets.py"]})


@pytest.mark.parametrize("scope_key", ["files", "include"])
def test_independent_questions_receive_source_on_every_call(tmp_path: Path, scope_key: str):
    from pasr.tokenize import get_tokenizer

    source = "def calculate(value):\n    return value * 2\n"
    (tmp_path / "worker.py").write_text(source, encoding="utf-8")
    server = create_server(tmp_path)
    for question in range(14):
        args = {"query": f"calculate value question {question}", scope_key: ["worker.py"], "budget_tokens": 100}
        payload = json.loads(_call(server, "select_context", args).content[0].text)
        assert payload["route"] == "lossless"
        assert source.rstrip() in payload["context"]
        assert payload["token_count"] == get_tokenizer().count(payload["context"]) <= 100


def test_repeated_selection_resends_source_after_host_context_loss(tmp_path: Path):
    source = "def calculate(value):\n    return value * 2\n"
    (tmp_path / "worker.py").write_text(source, encoding="utf-8")
    server = create_server(tmp_path)
    args = {"query": "calculate", "files": ["worker.py"]}
    for _ in range(14):
        payload = json.loads(_call(server, "select_context", args).content[0].text)
        assert source.rstrip() in payload["context"]
        assert _labels(payload) == ["worker.py:1-2"]


@pytest.mark.parametrize("scope", ["engine.py:3-15", "engine.py"])
def test_overlapping_requests_preserve_the_complete_requested_scope(tmp_path: Path, scope: str):
    (tmp_path / "engine.py").write_text(
        "".join(f"VALUE_{number} = {number}\n" for number in range(1, 25)), encoding="utf-8"
    )
    server = create_server(tmp_path)
    _call(server, "select_context", {"query": "values", "files": ["engine.py:3-5", "engine.py:10-12"]})
    expected = set(range(3, 16)) if ":" in scope else set(range(1, 25))
    for _ in range(3):
        payload = json.loads(_call(server, "select_context", {"query": "values", "files": [scope]}).content[0].text)
        delivered = set()
        for label in _labels(payload):
            start, _, end = label.rsplit(":", 1)[1].partition("-")
            delivered.update(range(int(start), int(end or start) + 1))
        assert delivered == expected


def test_a_scope_that_matches_nothing_searches_everything_and_says_so(mini_workspace: Path):
    """An `include` naming directories the workspace does not have used to be searched
    faithfully -- zero files -- and the reply said the query's words appear nowhere. The
    caller believed it, hunted synonyms with find_files, and answered wrong."""
    server = create_server(mini_workspace)
    payload = json.loads(
        _call(server, "find_evidence", {"query": "rate limit", "include": ["src", "tracker", "*.rs"]}).content[0].text
    )
    assert payload["hits"], "the unscoped search should find what the question is about"
    assert "matched no file here" in payload["advice"][0]
    assert not any("appear in no file" in note for note in payload["advice"])

    scoped = json.loads(_call(server, "find_evidence", {"query": "rate limit", "include": ["api"]}).content[0].text)
    assert not any("matched no file" in note for note in scoped.get("advice", []))


def test_one_reply_carries_at_most_the_select_budget(tmp_path: Path):
    """The per-response cap includes labels, even after repeated retrieval."""
    from pasr.mcp.server import SELECT_BUDGET

    body = "".join(f"def step_{n}(state):\n    state.retry_count += {n}\n    return state\n\n" for n in range(400))
    (tmp_path / "engine.py").write_text(body, encoding="utf-8")
    server = create_server(tmp_path)
    args = {"query": "retry count", "files": ["engine.py"], "budget_tokens": 20000}
    first = json.loads(_call(server, "select_context", args).content[0].text)
    assert first["route"] == "selected"
    assert first["token_count"] <= SELECT_BUDGET
    second = json.loads(_call(server, "select_context", args).content[0].text)
    assert second["token_count"] <= SELECT_BUDGET
    assert second["context"] == first["context"]


def test_search_code_returns_the_best_source_on_repeated_calls(tmp_path: Path):
    from pasr.mcp.server import SELECT_BUDGET
    from pasr.tokenize import get_tokenizer

    for n in range(6):
        (tmp_path / f"stage_{n}.py").write_text(
            "".join(f"def retry_budget_{n}_{k}(attempts):\n    return attempts * {k}\n\n" for k in range(40)),
            encoding="utf-8",
        )
    server = create_server(tmp_path, expose=["search_code"])
    assert [t.name for t in anyio.run(server.list_tools)] == ["search_code"]

    def search(query: str) -> dict:
        return _call(server, "search_code", {"query": query}).structured_content

    first = search("retry budget attempts")
    labels = _labels(first)
    assert labels and len({label.rsplit(":", 1)[0] for label in labels}) <= 3
    assert any(note.startswith("Also matched:") for note in first["advice"])
    for _ in range(12):
        second = search("retry budget attempts")
        assert second["context"] == first["context"]
        assert get_tokenizer().count(second["context"]) <= SELECT_BUDGET


def test_read_code_pins_range_pages_despite_unrelated_query(tmp_path: Path, monkeypatch):
    from pasr.mcp import server as server_module
    from pasr.tokenize import get_tokenizer

    monkeypatch.setattr(server_module, "SELECT_BUDGET", 70)
    lines = [f"value_{i} = {i}\n" for i in range(40)]
    (tmp_path / "target.py").write_text("".join(lines), encoding="utf-8")
    (tmp_path / "other.py").write_text("distractor = 99\n", encoding="utf-8")
    server = create_server(tmp_path, expose=["read_code"])
    pending = ["target.py:3-36"]
    bodies, fingerprints = [], []
    for _ in range(40):
        payload = _call(
            server,
            "read_code",
            {
                "query": "distractor",
                "files": pending,
            },
        ).structured_content
        assert len(_labels(payload)) == 1
        assert _labels(payload)[0].startswith("target.py:")
        assert "distractor" not in payload["context"]
        assert get_tokenizer().count(payload["context"]) <= 70
        bodies.append(payload["context"].partition("\n")[2])
        fingerprints.append(payload["source_fingerprint"])
        assert not payload["continuation"]["blocked"]
        remaining = payload["continuation"]["files"]
        if not remaining:
            break
        assert remaining != pending
        pending = remaining
    else:
        pytest.fail("Range continuation did not reach the requested end")

    assert len(bodies) > 1
    assert "".join(bodies) == "".join(lines[2:36])
    assert all(value == fingerprints[0] for value in fingerprints)
    assert set(fingerprints[0]) == {"target.py"}


def test_read_code_whole_file_preserves_guard_and_excludes_other_sources(tmp_path: Path):
    source = (
        "def enforce(value, validator):\n"
        "    if validator is None:\n"
        "        return value\n"
        "    validator(value)\n"
        "    return value\n"
    )
    (tmp_path / "hooks.py").write_text(source, encoding="utf-8")
    (tmp_path / "other.py").write_text("def enforce(value):\n    return 'outside scope'\n", encoding="utf-8")
    server = create_server(tmp_path, expose=["search_code", "read_code"])
    payload = _call(
        server,
        "read_code",
        {
            "query": "enforce",
            "files": ["hooks.py"],
        },
    ).structured_content
    namespace = {}
    exec(payload["context"].partition("\n")[2], namespace)
    enforce = namespace["enforce"]
    assert enforce(7, None) == 7
    validated = []
    assert enforce(7, validated.append) == 7
    assert validated == [7]
    assert set(payload["source_fingerprint"]) == {"hooks.py"}
    assert all(label.startswith("hooks.py:") for label in _labels(payload))


@pytest.mark.parametrize("files", [[], None, ["target.py", "missing.py"], ["."], ["../outside.py"]])
def test_read_code_invalid_scope_never_falls_back_to_discovery(tmp_path: Path, files):
    (tmp_path / "target.py").write_text("distractor = 99\n", encoding="utf-8")
    server = create_server(tmp_path, expose=["search_code", "read_code"])
    with pytest.raises(ToolError):
        _call(server, "read_code", {"query": "distractor", "files": files})


@pytest.mark.parametrize(
    "scope",
    [
        {"files": []},
        {"files": None},
        {"files": ["target.py:1-1"]},
        {"include": ["target.py"]},
    ],
)
def test_search_code_rejects_scope_instead_of_silently_widening(tmp_path: Path, scope):
    (tmp_path / "target.py").write_text("needle = 42\n", encoding="utf-8")
    server = create_server(tmp_path, expose=["search_code"])
    with pytest.raises(ToolError):
        _call(server, "search_code", {"query": "needle", **scope})


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": "needle"},
        {"query": "needle", "files": ["target.py"], "include": ["."]},
    ],
)
def test_read_code_requires_explicit_scope_and_rejects_extra_scope(tmp_path: Path, arguments):
    (tmp_path / "target.py").write_text("needle = 42\n", encoding="utf-8")
    server = create_server(tmp_path, expose=["read_code"])
    with pytest.raises(ToolError):
        _call(server, "read_code", arguments)


@pytest.mark.parametrize(
    "tool,scope",
    [
        ("select_context", {"files": ["worker.py"]}),
        ("select_context", {"include": ["worker.py"]}),
        ("search_code", {}),
        ("read_code", {"files": ["worker.py:1-2"]}),
    ],
)
def test_changed_source_is_returned_on_the_same_server(tmp_path: Path, tool: str, scope: dict):
    import os

    path = tmp_path / "worker.py"
    path.write_text("def checkpoint(value):\n    return value * 2\n", encoding="utf-8")
    server = create_server(tmp_path, expose=ALL_TOOLS)
    args = {"query": "checkpoint", **scope}
    first = _call(server, tool, args).structured_content
    assert "value * 2" in first["context"]
    original_stat = path.stat()
    path.write_text("def checkpoint(value):\n    return value * 9\n", encoding="utf-8")
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    second = _call(server, tool, args).structured_content
    assert "value * 9" in second["context"]
    assert "value * 2" not in second["context"]


@pytest.mark.parametrize("invalid", [{"query": ""}, {"budget_tokens": -1}, {"advanced": {"max_files": 0}}])
def test_previous_success_does_not_bypass_request_validation(tmp_path: Path, invalid: dict):
    (tmp_path / "worker.py").write_text("VALUE = 42\n", encoding="utf-8")
    server = create_server(tmp_path)
    args = {"query": "value", "files": ["worker.py"]}
    _call(server, "select_context", args)
    with pytest.raises(ToolError):
        _call(server, "select_context", {**args, **invalid})


def test_include_resends_lines_previously_read_as_explicit_ranges(tmp_path: Path):
    (tmp_path / "worker.py").write_text("".join(f"VALUE_{n} = {n}\n" for n in range(1, 7)), encoding="utf-8")
    server = create_server(tmp_path)
    first = json.loads(_call(server, "select_context", {"query": "value", "files": ["worker.py:1-2"]}).content[0].text)
    second = json.loads(_call(server, "select_context", {"query": "value", "include": ["*.py"]}).content[0].text)
    assert _labels(first) == ["worker.py:1-2"]
    assert _labels(second) == ["worker.py:1-6"]
    assert "VALUE_1 = 1" in second["context"]
    assert "VALUE_6 = 6" in second["context"]


@pytest.mark.parametrize("budget", [50, 1500])
def test_mcp_token_count_includes_delivered_provenance_labels(tmp_path: Path, budget: int):
    from pasr.tokenize import get_tokenizer

    (tmp_path / "worker.py").write_text(
        "".join(f"def checkpoint_{n}(value):\n    return value * {n}\n\n" for n in range(20)),
        encoding="utf-8",
    )
    payload = json.loads(
        _call(
            create_server(tmp_path),
            "select_context",
            {"query": "checkpoint value", "files": ["worker.py"], "budget_tokens": budget},
        )
        .content[0]
        .text
    )
    assert payload["token_count"] == get_tokenizer().count(payload["context"])
    assert payload["token_count"] <= budget


def test_lossless_source_must_also_fit_its_mcp_labels(tmp_path: Path):
    from pasr.tokenize import get_tokenizer

    source = "VALUE = 42\n"
    (tmp_path / "worker.py").write_text(source, encoding="utf-8")
    budget = get_tokenizer().count(source)
    payload = json.loads(
        _call(
            create_server(tmp_path),
            "select_context",
            {"query": "value", "files": ["worker.py"], "budget_tokens": budget},
        )
        .content[0]
        .text
    )
    assert payload["token_count"] == get_tokenizer().count(payload["context"])
    assert payload["token_count"] <= budget


@pytest.mark.parametrize("tool", ["select_context", "trace_dependencies"])
def test_source_read_failure_does_not_poison_later_requests(tmp_path: Path, tool: str):
    path = tmp_path / "worker.py"
    path.write_bytes(b"\xff")
    server = create_server(tmp_path, expose=ALL_TOOLS)
    args = {"query": "calculate"} if tool == "select_context" else {"symbol": "calculate"}
    args["files"] = ["worker.py"]
    for _ in range(12):
        with pytest.raises(ToolError):
            _call(server, tool, args)
    source = "def calculate(value):\n    return value * 2\n"
    path.write_text(source, encoding="utf-8")
    result = json.loads(_call(server, tool, args).content[0].text)
    assert source.rstrip() in result["context"]


def test_expansion_returns_prior_source_without_context_retention(tmp_path: Path):
    from pasr.tokenize import get_tokenizer

    source = "def calculate(value):\n    return value * 2\n"
    (tmp_path / "worker.py").write_text(source, encoding="utf-8")
    server = create_server(tmp_path, expose=ALL_TOOLS)
    first = json.loads(
        _call(
            server,
            "select_context",
            {
                "query": "calculate",
                "files": ["worker.py"],
                "budget_tokens": 100,
            },
        )
        .content[0]
        .text
    )
    for _ in range(12):
        result = json.loads(
            _call(
                server,
                "expand_context",
                {
                    "receipt_id": first["receipt"]["id"],
                    "extra_budget": 100,
                },
            )
            .content[0]
            .text
        )
        assert source.rstrip() in result["context"]
        assert result["token_count"] == get_tokenizer().count(result["context"]) <= 200


@pytest.mark.parametrize(
    "tool,args",
    [
        ("find_files", {"include": ["../"]}),
        ("find_symbols", {"include": ["../"]}),
        ("find_evidence", {"include": ["../"]}),
        ("find_usages", {"symbol": "value", "include": ["../"]}),
        ("select_context", {"query": "value", "files": ["../outside.py"]}),
        ("trace_dependencies", {"symbol": "value", "files": ["../outside.py"]}),
        ("explain_selection", {"receipt_id": "../outside"}),
        ("expand_context", {"receipt_id": "../outside"}),
    ],
)
def test_tool_scopes_cannot_escape_workspace(tmp_path: Path, tool: str, args: dict):
    with pytest.raises(ToolError):
        _call(create_server(tmp_path, expose=ALL_TOOLS), tool, args)


def test_pack_load_cannot_bypass_current_response_budget(tmp_path: Path):
    (tmp_path / "worker.py").write_text("def calculate(value):\n    return value * 2\n", encoding="utf-8")
    server = create_server(tmp_path)
    _call(
        server,
        "select_context",
        {
            "query": "calculate",
            "files": ["worker.py"],
            "budget_tokens": 100,
            "advanced": {"save_as": "worker"},
        },
    )
    with pytest.raises(ToolError, match="exceeds"):
        _call(
            server,
            "select_context",
            {
                "query": "",
                "budget_tokens": 1,
                "advanced": {"pack": "worker"},
            },
        )
    result = json.loads(
        _call(
            server,
            "select_context",
            {
                "query": "",
                "budget_tokens": 100,
                "advanced": {"pack": "worker"},
            },
        )
        .content[0]
        .text
    )
    assert "return value * 2" in result["context"]


@pytest.mark.parametrize("budget", [1, 15, 100])
def test_trace_response_reports_soft_budget_overrun(tmp_path: Path, budget: int):
    from pasr.tokenize import get_tokenizer

    (tmp_path / "worker.py").write_text(
        "def helper(value):\n    return value * 2\n\ndef calculate(value):\n    return helper(value)\n",
        encoding="utf-8",
    )
    server = create_server(tmp_path, expose=ALL_TOOLS)
    result = json.loads(
        _call(
            server,
            "trace_dependencies",
            {
                "symbol": "calculate",
                "files": ["worker.py"],
                "budget_tokens": budget,
            },
        )
        .content[0]
        .text
    )
    assert result["token_count"] == get_tokenizer().count(result["context"])
    assert result["within_budget"] is (result["token_count"] <= budget)
    assert {span["name"] for span in result["spans"]} == {"calculate", "helper"}


def test_large_library_pack_cannot_bypass_mcp_hard_cap(tmp_path: Path):
    from pasr.schema import validate_select_context_request
    from pasr.select import save_pack
    from pasr.tokenize import get_tokenizer

    (tmp_path / "worker.py").write_text(
        "".join(f"VALUE_{n} = {n}\n" for n in range(500)),
        encoding="utf-8",
    )
    request = validate_select_context_request(
        {
            "query": "value",
            "files": ["worker.py"],
            "budget_tokens": 6000,
        },
        workspace_root=tmp_path,
    )
    _, pack = save_pack("large", request)
    assert get_tokenizer().count(pack["context"]) > 1500
    with pytest.raises(ToolError, match="1500-token budget"):
        _call(
            create_server(tmp_path),
            "select_context",
            {
                "query": "",
                "budget_tokens": 20000,
                "advanced": {"pack": "large"},
            },
        )


def test_combined_search_retains_identifier_hits_in_large_functions(tmp_path: Path):
    from pasr.tokenize import get_tokenizer

    source = "def needle_worker():\n" + "".join(f"    step_{i} = {i}\n" for i in range(600))
    (tmp_path / "worker.py").write_text(source, encoding="utf-8")
    assert get_tokenizer().count(source) > 1500
    server = create_server(tmp_path, expose=ALL_TOOLS)
    found = json.loads(_call(server, "find_evidence", {"query": "needle"}).content[0].text)
    assert found["hits"][0]["provenance"] == "worker.py:1"
    selected = _call(server, "search_code", {"query": "needle"}).structured_content
    assert "def needle_worker():" in selected["context"]
    assert get_tokenizer().count(selected["context"]) <= 1500


def _path_fixture(root: Path) -> None:
    for n in range(4):
        (root / f"decoy_{n}.py").write_text(
            "".join(
                f"def validate_{n}_{k}(value):\n    # assignment hook validate\n    return value\n" for k in range(30)
            ),
            encoding="utf-8",
        )
    (root / "pkg").mkdir()
    (root / "pkg" / "setters.py").write_text(
        "from . import _config\n\n\n"
        "def guard(instance, attrib, new_value):\n"
        "    if _config.enabled is False:\n"
        "        return new_value\n"
        "    return new_value\n",
        encoding="utf-8",
    )
    (root / "pkg" / "_config.py").write_text("enabled = True\n", encoding="utf-8")


@pytest.mark.parametrize("named", ["pkg/setters.py", "setters.py", "./pkg/setters.py"])
def test_search_code_reads_a_file_the_query_names_by_path(tmp_path: Path, named: str):
    """Content ranking alone never reaches a file whose lines lack the query's words."""
    _path_fixture(tmp_path)
    server = create_server(tmp_path, expose=["find_evidence", "search_code"])
    query = f"{named} validate assignment hook"
    found = json.loads(_call(server, "find_evidence", {"query": query}).content[0].text)
    assert not any(hit["provenance"].startswith("pkg/setters.py") for hit in found["hits"])
    payload = _call(server, "search_code", {"query": query}).structured_content
    assert "pkg/setters.py:" in payload["context"]
    assert "if _config.enabled is False:" in payload["context"]


def test_named_paths_require_one_unambiguous_file(tmp_path: Path):
    from pasr.mcp.server import _named_paths

    _path_fixture(tmp_path)
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "_config.py").write_text("enabled = False\n", encoding="utf-8")
    assert _named_paths(tmp_path, r"read pkg\setters.py and decoy_1.py") == ["pkg/setters.py", "decoy_1.py"]
    assert _named_paths(tmp_path, "_config.py flag") == []  # two files have that name
    assert _named_paths(tmp_path, "pkg/_config.py flag") == ["pkg/_config.py"]
    assert _named_paths(tmp_path, "setters.guard and os.path.join") == []


def test_search_code_does_not_call_a_named_file_absent(tmp_path: Path):
    _path_fixture(tmp_path)
    server = create_server(tmp_path, expose=["search_code"])
    payload = _call(server, "search_code", {"query": "pkg/_config.py enabled flag"}).structured_content
    assert "pkg/_config.py:" in payload["context"]
    assert not any("_config.py" in note for note in payload["advice"] if note.startswith("No file here contains"))


@pytest.mark.parametrize(
    "tool,args",
    [
        ("search_code", {"query": "guard new_value"}),
        ("read_code", {"query": "guard", "files": ["pkg/setters.py:1-7"]}),
    ],
)
def test_source_tools_send_source_unescaped_after_a_header(tmp_path: Path, tool: str, args: dict):
    """The text block is the structured object, with the source as itself."""
    from pasr.tokenize import get_tokenizer

    _path_fixture(tmp_path)
    result = _call(create_server(tmp_path, expose=["search_code", "read_code"]), tool, args)
    payload = result.structured_content
    header, _, body = result.content[0].text.partition("\n")
    assert body == payload["context"]
    assert "if _config.enabled is False:\n        return new_value" in body
    assert json.loads(header) == {k: v for k, v in payload.items() if k != "context" and v not in ([], None)}
    as_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    assert get_tokenizer().count(result.content[0].text) < get_tokenizer().count(as_json)
