from pathlib import Path

import pytest

from pasr.symbol_search import find_evidence, find_usages

_RUST = """\
pub struct Server {
    ready: bool,
}

impl Server {
    pub fn is_ready(&self) -> bool {
        self.ready
    }

    pub fn status(&self) -> Status {
        if self.is_ready() { Status::Up } else { Status::Down }
    }
}

pub fn report(server: &Server) {
    let _ = server.is_ready();
}
"""


@pytest.fixture
def rust_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "srv").mkdir(parents=True)
    (root / "srv" / "server.rs").write_text(_RUST, encoding="utf-8")
    return root


def test_definition_comes_first_then_call_sites_with_their_owner(rust_workspace: Path):
    result = find_usages(rust_workspace, "is_ready")

    assert result["definition_count"] == 1
    assert result["usage_count"] == 2
    assert result["hits"][0]["role"] == "definition"
    assert result["hits"][0]["provenance"] == "srv/server.rs:6"

    owners = {hit["in"] for hit in result["hits"] if hit["role"] == "usage"}
    assert owners == {"function status", "function report"}, "each usage must name its enclosing definition"


def test_every_hit_carries_the_line_text(rust_workspace: Path):
    """Locations without code force the caller to fetch the line again."""
    result = find_usages(rust_workspace, "is_ready")
    assert all(hit["text"] for hit in result["hits"])
    assert any("Status::Up" in hit["text"] for hit in result["hits"])


def test_whole_word_matching_only(rust_workspace: Path):
    assert find_usages(rust_workspace, "ready")["usage_count"] >= 1
    assert find_usages(rust_workspace, "is_read")["hits"] == []


def test_top_k_truncates_and_says_so(rust_workspace: Path):
    result = find_usages(rust_workspace, "is_ready", top_k=1)
    assert len(result["hits"]) == 1
    assert result["truncated"] is True


def test_missing_symbol_is_empty_not_an_error(rust_workspace: Path):
    result = find_usages(rust_workspace, "no_such_symbol")
    assert result["hits"] == []
    assert result["files_scanned"] >= 1


def test_rejects_empty_symbol_and_bad_top_k(rust_workspace: Path):
    with pytest.raises(ValueError, match="symbol"):
        find_usages(rust_workspace, "   ")
    with pytest.raises(ValueError, match="top_k"):
        find_usages(rust_workspace, "is_ready", top_k=0)


def test_read_lines_cover_complete_small_functions_in_hit_order(rust_workspace: Path):
    hits = find_usages(rust_workspace, "is_ready")["hits"]

    assert [(hit["provenance"], hit["role"], hit["read_lines"]) for hit in hits] == [
        ("srv/server.rs:6", "definition", "6-8"),
        ("srv/server.rs:11", "usage", "10-12"),
        ("srv/server.rs:16", "usage", "15-17"),
    ]
    assert [hit["text"] for hit in hits] == [
        "pub fn is_ready(&self) -> bool {",
        "if self.is_ready() { Status::Up } else { Status::Down }",
        "let _ = server.is_ready();",
    ]


@pytest.mark.parametrize("locate", [find_evidence, find_usages])
@pytest.mark.parametrize("function_lines", [40, 41])
def test_read_lines_switch_from_complete_function_to_neighborhood(tmp_path: Path, locate, function_lines: int):
    lines = ["def process():", *("    pass" for _ in range(function_lines - 2)), "    return 1"]
    lines[19] = "    checkpoint()"
    (tmp_path / "worker.py").write_text("\n".join(lines), encoding="utf-8")

    hit = locate(tmp_path, "checkpoint")["hits"][0]

    assert hit["provenance"] == "worker.py:20"
    assert hit["in"] == "function process"
    assert hit["read_lines"] == ("1-40" if function_lines == 40 else "12-28")


@pytest.mark.parametrize("locate", [find_evidence, find_usages])
def test_read_lines_use_innermost_function_not_outer_class(tmp_path: Path, locate):
    lines = ["class Worker:", "    def process(self):", "        checkpoint()", "        return 1"]
    lines.extend("    field = 0" for _ in range(50))
    (tmp_path / "worker.py").write_text("\n".join(lines), encoding="utf-8")

    hit = locate(tmp_path, "checkpoint")["hits"][0]

    assert hit["read_lines"] == "2-4"


@pytest.mark.parametrize("locate", [find_evidence, find_usages])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_search_provenance_uses_physical_lines(tmp_path: Path, locate, newline: str):
    lines = ['label = "a\u2028b\fc"', "def target():", '    return "checkpoint café"']
    (tmp_path / "m.py").write_bytes((newline.join(lines) + newline).encode("utf-8-sig"))

    (hit,) = locate(tmp_path, "checkpoint")["hits"]

    assert hit["provenance"] == "m.py:3"
    assert hit["in"] == "function target"
    assert hit["text"] == 'return "checkpoint café"'
    assert hit["read_lines"] == "2-3"
