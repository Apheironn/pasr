from pathlib import Path

import pytest

from pasr.investigate import investigate

_SERVER = """\
//! The main loop: dispatches requests and reports progress.
use crate::state::Server;

pub fn handle_event(server: &mut Server) {
    if server.is_settled() {
        report(server.current_status());
    }
}
"""
_STATE = """\
pub struct StatusReport {
    pub settled: bool,
}

impl Server {
    /// Unlike `is_done`, this returns false while we are reindexing.
    pub fn is_settled(&self) -> bool {
        self.pending == 0
    }

    pub fn current_status(&self) -> StatusReport {
        StatusReport { settled: self.is_settled() }
    }
}
"""
_NOISE = "\n".join(f"// unrelated helper {i} for parsing" for i in range(40))


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main_loop.rs").write_text(_SERVER, encoding="utf-8")
    (root / "src" / "state.rs").write_text(_STATE, encoding="utf-8")
    for i in range(4):
        (root / "src" / f"noise{i}.rs").write_text(_NOISE, encoding="utf-8")
    return root


def test_one_call_locates_reads_and_stays_in_budget(workspace: Path):
    result = investigate(workspace, "how does it report progress while reindexing", budget_tokens=800)

    assert result["files_selected"], "content search should pick at least one file"
    assert result["token_count"] <= 800
    assert result["evidence_lines"]
    assert result["context"]
    assert all(":" in line for line in result["evidence_lines"])


def test_absent_words_are_named_so_the_caller_stops_hunting_them(workspace: Path):
    result = investigate(workspace, "reindexing kubernetes helm", budget_tokens=600)
    assert "kubernetes" in result["absent_terms"]
    assert any("appear in no file" in line for line in result["advice"])


def test_span_bodies_are_not_returned_twice(workspace: Path):
    """`context` already carries the text; repeating it in spans doubles the caller's bill."""
    result = investigate(workspace, "reindexing progress", budget_tokens=800)
    assert all(isinstance(p, str) for p in result["span_provenance"])
    assert "spans" not in result


def test_a_question_with_no_content_words_is_rejected(workspace: Path):
    with pytest.raises(ValueError, match="content word"):
        investigate(workspace, "how is it that the")


def test_rejects_bad_budget(workspace: Path):
    with pytest.raises(ValueError, match="budget_tokens"):
        investigate(workspace, "reindexing", budget_tokens=0)
