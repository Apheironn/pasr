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
    assert result["exact_match"] is True


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


def test_kind_aliases_are_accepted(rust_workspace: Path):
    """A caller guessing "func" or "fn" should not get a silent empty result."""
    for alias in ("func", "fn", "method"):
        assert [m["name"] for m in find_symbols(rust_workspace, query="is_quiescent", kinds=[alias])["matches"]] == [
            "is_quiescent"
        ]


def test_a_kind_filter_that_hides_a_real_match_says_so(rust_workspace: Path):
    result = find_symbols(rust_workspace, query="is_quiescent", kinds=["struct"])

    assert result["matches"] == []
    assert result["kinds_filtered_out"] == 1
    assert result["kinds_available"] == ["function"]


_NAMESAKES = """\
pub struct Signals {
    inner: bool,
}

impl Signals {
    pub fn check(&self) -> bool {
        self.inner
    }
}

pub struct Context {
    flag: bool,
}

impl Context {
    pub fn signals(&self) -> bool {
        self.flag
    }
}

pub const IDLE_TIMEOUT: u64 = 30;
"""


@pytest.fixture
def namesake_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "core").mkdir(parents=True)
    (root / "core" / "signals.rs").write_text(_NAMESAKES, encoding="utf-8")
    return root


def test_case_exact_declaration_outranks_its_lowercase_namesake(namesake_workspace: Path):
    # `Signals` used to return the `signals()` accessor: case-folded matching made every
    # namesake equally "exact", and the type the caller asked for lost on path order.
    names = [(m["kind"], m["name"]) for m in find_symbols(namesake_workspace, "Signals")["matches"]]

    assert names[0] == ("struct", "Signals")
    assert ("function", "signals") in names  # still found, just not first


def test_lowercase_query_still_prefers_the_accessor(namesake_workspace: Path):
    names = [(m["kind"], m["name"]) for m in find_symbols(namesake_workspace, "signals")["matches"]]

    assert names[0] == ("function", "signals")


def test_declaration_outranks_the_impl_block_carrying_its_name(namesake_workspace: Path):
    matches = find_symbols(namesake_workspace, "Signals", kinds=["struct", "impl"])["matches"]

    assert [(m["kind"], m["name"]) for m in matches][:2] == [("struct", "Signals"), ("impl", "Signals")]


def test_one_generic_word_does_not_suppress_a_multiword_query(namesake_workspace: Path):
    # "Context session idle timeout": IDLE_TIMEOUT matches `timeout` exactly, and that
    # alone used to discard every partial match -- including the type being asked about.
    names = [m["name"] for m in find_symbols(namesake_workspace, "Context session idle timeout")["matches"]]

    assert "IDLE_TIMEOUT" in names
    assert "Context" in names


def test_single_name_query_stays_decisive(namesake_workspace: Path):
    matches = find_symbols(namesake_workspace, "Context")["matches"]

    assert {m["name"] for m in matches} == {"Context"}
