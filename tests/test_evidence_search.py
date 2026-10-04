from pathlib import Path

import pytest

from pasr.symbol_search import _definitions, _reference_rank, find_evidence, find_usages

_COMMON = "\n".join(f"// server handles work item {i}" for i in range(5))
_RARE = """\
/// Unlike `is_settled`, this returns false when we are reindexing.
pub fn is_settled(&self) -> bool {
    self.done
}
"""


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    for i in range(6):
        (root / "src" / f"noise{i}.rs").write_text(_COMMON, encoding="utf-8")
    (root / "src" / "state.rs").write_text(_RARE, encoding="utf-8")
    return root


def test_a_rare_term_outranks_a_common_one(workspace: Path):
    """The point of the tool: one word in one file beats a word in every file."""
    result = find_evidence(workspace, "server work reindexing")

    assert result["term_file_counts"]["reindexing"] == 1
    assert result["term_file_counts"]["server"] == 6
    assert result["hits"][0]["provenance"].startswith("src/state.rs:")
    assert "reindexing" in result["hits"][0]["text"]  # the term it matched is in the line itself


def test_hits_carry_line_text_and_enclosing_definition(workspace: Path):
    result = find_evidence(workspace, "reindexing")
    hit = result["hits"][0]
    assert hit["text"].startswith("///")
    assert hit["in"] in {"(module level)", "function is_settled"}
    assert hit["provenance"] == "src/state.rs:1"


def test_per_file_caps_how_much_one_file_can_flood(workspace: Path):
    result = find_evidence(workspace, "server work", per_file=1)
    per_source = [hit["provenance"].rsplit(":", 1)[0] for hit in result["hits"]]
    assert len(per_source) == len(set(per_source))


def test_stopwords_only_query_is_rejected(workspace: Path):
    with pytest.raises(ValueError, match="content word"):
        find_evidence(workspace, "how is it that the")


def test_no_match_is_empty_not_an_error(workspace: Path):
    result = find_evidence(workspace, "kubernetes helm chart")
    assert result["hits"] == []
    assert result["files_scanned"] >= 6


@pytest.mark.parametrize("locate", [find_evidence, find_usages])
def test_unparsed_read_lines_cover_hits_and_clamp_to_file_edges(tmp_path: Path, locate):
    lines = ["ordinary text"] * 30
    for index in (0, 14, 29):
        lines[index] = "checkpoint " + "x" * 200
    (tmp_path / "notes.txt").write_text("\n".join(lines), encoding="utf-8")

    if locate is find_evidence:
        result = locate(tmp_path, "checkpoint", per_file=3)
    else:
        result = locate(tmp_path, "checkpoint")

    assert [(hit["provenance"], hit["read_lines"]) for hit in result["hits"]] == [
        ("notes.txt:1", "1-9"),
        ("notes.txt:15", "7-23"),
        ("notes.txt:30", "22-30"),
    ]
    for hit in result["hits"]:
        assert hit["in"] == "(module level)"
        assert hit["text"] == lines[int(hit["provenance"].rsplit(":", 1)[1]) - 1][:160]


def test_evidence_read_lines_preserve_rank_and_per_file_limit(workspace: Path):
    hits = find_evidence(workspace, "server work reindexing", top_k=3, per_file=1)["hits"]

    # The rare term still leads. The remaining two come from distinct files, but which of
    # the six byte-identical noise files they are is not a property worth pinning: they
    # differ only by a digit in the path, which similarity scoring legitimately sees.
    assert hits[0] == {**hits[0], "provenance": "src/state.rs:1", "read_lines": "1-4"}
    assert [hit["read_lines"] for hit in hits[1:]] == ["1-5", "1-5"]
    assert len({hit["provenance"].rsplit(":", 1)[0] for hit in hits}) == 3


_INACTIVITY = """\
/// Garbage collector: monitors usage and stops a worker automatically after a period of
/// inactivity, so workers do not stay running indefinitely.
pub struct Collector {
    after: u64,
}
"""
_UNRELATED = """\
/// Parses a colour name into a style. Nothing here concerns running code at all.
pub fn parse_colour(name: &str) -> u8 {
    0
}
"""


def test_similarity_promotes_the_closer_file_when_rarity_cannot_choose(tmp_path: Path):
    # Both files carry the query's rare term exactly once, so the lexical score ties and
    # rarity has nothing left to say. What breaks the tie is that one of them is about the
    # thing being asked about, in words the question never used: "inactivity" and "stops
    # automatically" against "idle" and "shuts down".
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    (root / "src" / "collector.rs").write_text("// plugin\n" + _INACTIVITY, encoding="utf-8")
    (root / "src" / "colour.rs").write_text("// plugin\n" + _UNRELATED, encoding="utf-8")

    hits = find_evidence(root, "what shuts an idle plugin down automatically")["hits"]

    assert hits[0]["provenance"].startswith("src/collector.rs:")


def test_a_decisive_rarity_win_survives_similarity(workspace: Path):
    # The counterweight, and the reason the similarity weight is 1.0 rather than higher:
    # the six noise files are collectively the better similarity match here, and must still
    # lose to the one file carrying the rare term.
    hits = find_evidence(workspace, "server work reindexing")["hits"]

    assert hits[0]["provenance"].startswith("src/state.rs:")


def test_reference_rank_lifts_what_the_relevant_files_lean_on(tmp_path: Path):
    # The unit the blend depends on: relevance flows along "api.rs names what collector.rs
    # defines". A toy corpus is too small for a ranking signal to decide anything end to
    # end -- its effect on a real repository is measured in the recorded-query replay, not
    # pinned here -- so this asserts the mechanism rather than an ordering it cannot own.
    texts = {
        "src/api.rs": "pub fn stop_idle(c: &Collector) {\n    c.sweep();\n}\n",
        "src/collector.rs": "pub struct Collector {\n    after: u64,\n}\n",
        "src/decoy.rs": "pub const IDLE_TIMEOUT: u64 = 1;\n",
    }
    definitions = {source: _definitions(source, text) for source, text in texts.items()}
    assert [d.name for d in definitions["src/collector.rs"]] == ["Collector"]

    # api.rs is where the query landed; the other two are equal strangers to it.
    rank = _reference_rank({"src/api.rs": 1.0, "src/collector.rs": 0.0, "src/decoy.rs": 0.0}, texts, definitions)

    assert rank["src/collector.rs"] > rank["src/decoy.rs"]


def test_a_long_file_does_not_win_by_mentioning_everything_somewhere(tmp_path: Path):
    # A term counts as present if it appears anywhere in the file, so a long file is far
    # likelier to contain all of a question's words somewhere than the short one that
    # answers it. Without length normalisation it scored as if that were the same evidence:
    # asked what stops an idle plugin, nushell's longest command file led on "tab stops".
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    sprawl = [f"// line {i} of an unrelated module\n" for i in range(400)]
    sprawl[10] = "// account for tab stops from an arbitrary column\n"
    sprawl[200] = "// an idle worker in a pool\n"
    sprawl[390] = "// plugin authors should read this\n"
    (root / "src" / "sprawl.rs").write_text("".join(sprawl), encoding="utf-8")
    (root / "src" / "gc.rs").write_text(
        "/// Stops an idle plugin after inactivity.\npub struct Gc {\n    after: u64,\n}\n", encoding="utf-8"
    )

    hits = find_evidence(root, "what stops an idle plugin")["hits"]

    assert hits[0]["provenance"].startswith("src/gc.rs:")


def test_a_plain_word_reaches_the_identifier_that_contains_it(tmp_path):
    """`exit` used to match only as a whole word, and `_` is a word character, so the line
    that stores LAST_EXIT_CODE was the one line a plain-words question could not surface."""
    from pasr.symbol_search import find_evidence

    (tmp_path / "stack.py").write_text(
        "def note(stack, code):\n    stack.set_last_exit_code(LAST_EXIT_CODE, code)\n", encoding="utf-8"
    )
    (tmp_path / "other.py").write_text("# nothing about the last status here\n", encoding="utf-8")
    hits = find_evidence(tmp_path, query="last exit status", top_k=5, per_file=2)["hits"]
    assert any("LAST_EXIT_CODE" in hit["text"] for hit in hits)


@pytest.mark.parametrize("scorer_name", ["", "none"])
def test_disabling_similarity_still_returns_rare_evidence(workspace: Path, monkeypatch, scorer_name: str):
    import pasr.symbol_search as search

    monkeypatch.setattr(search, "_SCORER_NAME", scorer_name)
    search._semantic_scorer.cache_clear()
    try:
        result = search.find_evidence(workspace, "server work reindexing")
    finally:
        search._semantic_scorer.cache_clear()

    assert result["hits"][0]["provenance"] == "src/state.rs:1"
    assert "reindexing" in result["hits"][0]["text"]


def test_acronym_identifier_parts_are_searchable_as_plain_words(tmp_path: Path):
    (tmp_path / "transport.py").write_text("class HTTPRequest:\n    pass\n", encoding="utf-8")

    result = find_evidence(tmp_path, "request")

    assert result["term_file_counts"] == {"request": 1}
    assert [(hit["provenance"], hit["text"]) for hit in result["hits"]] == [("transport.py:1", "class HTTPRequest:")]
