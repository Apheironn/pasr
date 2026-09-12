from pathlib import Path

import pytest

from pasr.symbol_search import find_symbols

_RUST = """\
//! A tiny module.
use std::sync::Arc;

pub struct ConnectionTable {
    deadline: u64,
}

impl ConnectionTable {
    pub fn is_quiescent(&self) -> bool {
        self.deadline == 0
    }

    pub fn is_verbose(&self) -> bool {
        false
    }
}

pub trait Sweeper {
    fn sweep(&self);
}

pub enum Progress {
    Begin,
    End,
}
"""


@pytest.fixture
def rust_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "net").mkdir(parents=True)
    (root / "net" / "table.rs").write_text(_RUST, encoding="utf-8")
    return root


def test_finds_python_definitions_with_provenance(mini_workspace: Path):
    result = find_symbols(mini_workspace, query="rate_limit")

    assert result["files_indexed"] >= 4
    assert result["matches"], "expected at least one definition"
    assert all(":" in match["provenance"] for match in result["matches"])


def test_exact_name_match_is_returned_alone(rust_workspace: Path):
    result = find_symbols(rust_workspace, query="is_quiescent")

    assert [m["name"] for m in result["matches"]] == ["is_quiescent"]
    assert result["matches"][0]["kind"] == "function"
    assert result["matches"][0]["provenance"] == "net/table.rs:9-11"
    assert result["matches"][0]["exact_name_match"] is True


def test_stopword_parts_do_not_drag_in_namesakes(rust_workspace: Path):
    """``is_quiescent`` must not match ``is_verbose`` on the strength of "is"."""
    result = find_symbols(rust_workspace, query="quiescent")

    assert [m["name"] for m in result["matches"]] == ["is_quiescent"]


def test_kind_filter_and_rust_struct_trait_enum(rust_workspace: Path):
    kinds = {m["kind"] for m in find_symbols(rust_workspace, query="ConnectionTable Sweeper Progress")["matches"]}
    assert {"struct", "trait", "enum"} <= kinds

    only_traits = find_symbols(rust_workspace, query="ConnectionTable Sweeper Progress", kinds=["trait"])
    assert [m["kind"] for m in only_traits["matches"]] == ["trait"]


def test_reports_unindexed_extensions_rather_than_silently_dropping(mini_workspace: Path):
    result = find_symbols(mini_workspace, query="deployment")

    assert ".md" in result["unparsed_extensions"]


def test_top_k_must_be_positive(mini_workspace: Path):
    with pytest.raises(ValueError, match="top_k"):
        find_symbols(mini_workspace, query="session", top_k=0)
