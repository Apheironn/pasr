from pathlib import Path

import pytest

from pasr.find_files import find_files


def test_ranks_path_matches_by_query_term_overlap(mini_workspace: Path):
    result = find_files(mini_workspace, query="ratelimit response headers")

    assert result["total_candidates"] >= 5
    assert result["matches"][0]["path"] == "api/ratelimit.py"
    assert result["matches"][0]["matched_keywords"] == ["ratelimit"]
    assert result["matches"][0]["match_score"] == round(1 / 3, 3)


def test_empty_query_lists_candidates_unranked(mini_workspace: Path):
    result = find_files(mini_workspace, query="")

    paths = [m["path"] for m in result["matches"]]
    assert paths == sorted(paths)
    assert all(m["match_score"] is None for m in result["matches"])


def test_no_path_overlap_returns_no_matches(mini_workspace: Path):
    result = find_files(mini_workspace, query="quantum teleportation")

    assert result["total_candidates"] >= 5
    assert result["matches"] == []


def test_include_scopes_the_search(mini_workspace: Path):
    result = find_files(mini_workspace, query="session", include=["auth"])

    assert result["total_candidates"] == 1
    assert result["matches"][0]["path"] == "auth/session.py"


def test_top_k_must_be_positive(mini_workspace: Path):
    with pytest.raises(ValueError, match="top_k"):
        find_files(mini_workspace, query="session", top_k=0)
