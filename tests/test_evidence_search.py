from pathlib import Path

import pytest

from pasr.symbol_search import find_evidence

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
