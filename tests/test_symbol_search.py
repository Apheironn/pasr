from pathlib import Path

import pytest

from pasr.symbol_search import find_symbols, find_usages

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


def test_a_path_that_cannot_hold_an_implementation_is_ranked_below_one_that_can():
    """A parser fixture matches a question's words as readily as the code does.

    Pointed at a whole checkout rather than a clean src tree, rust-analyzer spent 7 of its
    top 20 hits on docs and test_data for the one question PASR lost worst -- a third of
    the retrieval budget on files that cannot contain the mechanism. Across four corpora
    and eight questions the demotion removed 13 of 15 such hits and cost no anchor.
    Prose is demoted gently: a design note can be the answer, a snapshot never is.
    """
    from pasr.symbol_search import _path_prior

    assert _path_prior("crates/rust-analyzer/src/main_loop.rs") == 1.0
    assert _path_prior("src/pasr/select.py") == 1.0
    # fixture data, wherever it sits in the tree
    assert _path_prior("crates/parser/test_data/parser/ok/0035_weird_exprs.rs") < 1.0
    assert _path_prior("a/__snapshots__/b.rs") < 1.0
    # prose is demoted, but by less than fixture data
    assert _path_prior("crates/parser/test_data/x.rs") < _path_prior("docs/book/src/troubleshooting.md") < 1.0
    # a file merely called "test_something.rs" is still code
    assert _path_prior("crates/x/src/test_runner.rs") == 1.0


_RUST_QUALIFIED = """//! Interruption.

pub struct Signals {
    flag: bool,
}

impl Signals {
    pub fn check(&self) -> bool {
        self.flag
    }
}

pub fn run_pipeline(signals: &Signals) {
    if signals.check() {
        return;
    }
}
"""


def test_a_qualified_name_is_retried_bare_rather_than_returning_nothing(tmp_path: Path):
    """`Signals::check` is spelled that way nowhere: call sites read `signals.check()`.

    The literal search returned usage_count 0 and definition_count 0, which a caller
    cannot tell from "no such symbol" -- and the old advice said to check the spelling,
    so it did: across 48 recorded runs, 12 of 18 qualified queries came back empty and
    the model spent its remaining turns on Signals::interrupted, Signals::interrupt_flag,
    signals.check. Every one of them reaches the answer's own file from the final
    segment alone.
    """
    root = tmp_path / "ws"
    root.mkdir()
    (root / "signals.rs").write_text(_RUST_QUALIFIED, encoding="utf-8")

    result = find_usages(root, "Signals::check")

    assert result["searched"] == "check"
    assert result["symbol"] == "Signals::check", "the reply still says what was asked for"
    assert result["definition_count"] == 1
    assert any("signals.check()" in hit["text"] for hit in result["hits"])


def test_a_name_that_matches_as_written_is_not_rewritten(tmp_path: Path):
    """The retry fires only on silence. `Signals::new` is exactly how Rust calls an
    associated function, and rewriting it to `new` would bury the caller in matches.
    """
    root = tmp_path / "ws"
    root.mkdir()
    (root / "signals.rs").write_text(_RUST_QUALIFIED, encoding="utf-8")

    assert "searched" not in find_usages(root, "check")
    assert "searched" not in find_usages(root, "signals.check")
    # a name with no qualifier and no match stays empty rather than inventing a retry
    missing = find_usages(root, "Nonexistent")
    assert missing["hits"] == [] and "searched" not in missing
