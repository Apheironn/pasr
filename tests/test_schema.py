from pathlib import Path

import pytest

from pasr.schema import validate_select_context_request


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# notes\n", encoding="utf-8")
    return tmp_path


def test_requires_a_query(workspace: Path) -> None:
    with pytest.raises(ValueError, match="query is required"):
        validate_select_context_request({"files": ["notes.md"]}, workspace)


def test_resolves_explicit_files_and_globs_without_duplicates(workspace: Path) -> None:
    request = validate_select_context_request({"query": "q", "files": ["pkg/a.py"], "include": ["pkg/*.py"]}, workspace)
    rels = [meta["relative_path"] for meta in request.file_metadata]
    assert rels == ["pkg/a.py", "pkg/b.py"]
    assert all(path.is_absolute() for path in request.files)


def test_rejects_workspace_escape(workspace: Path) -> None:
    for bad in ("../outside.py", "/etc/passwd", "C:\\Windows\\win.ini"):
        with pytest.raises(ValueError, match="escapes workspace"):
            validate_select_context_request({"query": "q", "files": [bad]}, workspace)


def test_rejects_missing_file(workspace: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        validate_select_context_request({"query": "q", "files": ["pkg/missing.py"]}, workspace)


def test_rejects_unresolved_file_set(workspace: Path) -> None:
    with pytest.raises(ValueError, match="at least one file"):
        validate_select_context_request({"query": "q", "include": ["pkg/*.rs"]}, workspace)


def test_a_locator_in_include_names_the_parameter_that_takes_it(workspace: Path) -> None:
    # A model that reads "pkg/a.py:1-2" off a hit will sometimes paste it into `include`,
    # where it matches nothing. "resolves to no files" alone just earns the same call again.
    with pytest.raises(ValueError, match=r'files=\["pkg/a\.py:1-2"\]'):
        validate_select_context_request({"query": "q", "include": ["pkg/a.py:1-2"]}, workspace)

    request = validate_select_context_request({"query": "q", "files": ["pkg/a.py:1-2"]}, workspace)
    assert [meta["line_ranges"] for meta in request.file_metadata] == [[[1, 2]]]


def test_rejects_bad_numeric_fields(workspace: Path) -> None:
    with pytest.raises(ValueError, match="budget_tokens must be positive"):
        validate_select_context_request({"query": "q", "files": ["notes.md"], "budget_tokens": 0}, workspace)
    with pytest.raises(ValueError, match="prefix_tokens must be non-negative"):
        validate_select_context_request({"query": "q", "files": ["notes.md"], "prefix_tokens": -1}, workspace)
    with pytest.raises(ValueError, match="budget_tokens must be an integer"):
        validate_select_context_request({"query": "q", "files": ["notes.md"], "budget_tokens": True}, workspace)


def test_rejects_unknown_recall_strategy(workspace: Path) -> None:
    with pytest.raises(ValueError, match="recall_strategy"):
        validate_select_context_request({"query": "q", "files": ["notes.md"], "recall_strategy": "nope"}, workspace)


def test_enforces_max_files(workspace: Path) -> None:
    with pytest.raises(ValueError, match="exceeding max_files"):
        validate_select_context_request({"query": "q", "include": ["pkg/*.py"], "max_files": 1}, workspace)


@pytest.mark.parametrize(
    "field,value",
    [
        ("query", None),
        ("query", 42),
        ("outline", "false"),
        ("outline", 1),
        ("budget_tokens", 3.9),
        ("budget_tokens", float("inf")),
        ("budget_tokens", float("nan")),
        ("trace", ["target"]),
    ],
)
def test_rejects_values_that_change_meaning_when_coerced(workspace: Path, field: str, value) -> None:
    with pytest.raises(ValueError):
        validate_select_context_request({"query": "target value", "files": ["pkg/a.py"], field: value}, workspace)


@pytest.mark.parametrize("symbol", [None, 42, [], ""])
def test_trace_requires_a_nonempty_symbol_string(workspace: Path, symbol) -> None:
    from pasr.schema import validate_trace_dependencies_request

    with pytest.raises(ValueError):
        validate_trace_dependencies_request({"symbol": symbol, "files": ["pkg/a.py"]}, workspace)
