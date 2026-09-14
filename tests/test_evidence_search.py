from pathlib import Path

import pytest

from pasr.symbol_search import find_evidence, find_usages

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
    assert result["hits"][0]["source"] == "src/state.rs"
    assert "reindexing" in result["hits"][0]["matched_terms"]


def test_hits_carry_line_text_and_enclosing_definition(workspace: Path):
    result = find_evidence(workspace, "reindexing")
    hit = result["hits"][0]
    assert hit["text"].startswith("///")
    assert hit["in"] in {"(module level)", "function is_settled"}
    assert hit["provenance"] == "src/state.rs:1"


def test_per_file_caps_how_much_one_file_can_flood(workspace: Path):
    result = find_evidence(workspace, "server work", per_file=1)
    per_source = [hit["source"] for hit in result["hits"]]
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

    assert [(hit["line"], hit["read_lines"]) for hit in result["hits"]] == [
        (1, "1-9"),
        (15, "7-23"),
        (30, "22-30"),
    ]
    for hit in result["hits"]:
        assert hit["in"] == "(module level)"
        assert hit["text"] == lines[hit["line"] - 1][:160]


def test_evidence_read_lines_preserve_rank_and_per_file_limit(workspace: Path):
    hits = find_evidence(workspace, "server work reindexing", top_k=3, per_file=1)["hits"]

    assert [(hit["provenance"], hit["read_lines"]) for hit in hits] == [
        ("src/state.rs:1", "1-4"),
        ("src/noise0.rs:1", "1-5"),
        ("src/noise1.rs:1", "1-5"),
    ]
