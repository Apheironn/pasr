from pathlib import Path

import pytest

from pasr.find_files import find_files


def test_ranks_path_matches_by_query_term_overlap(mini_workspace: Path):
    result = find_files(mini_workspace, query="ratelimit response headers")

    assert result["total_candidates"] >= 5
    assert result["matches"][0]["path"] == "api/ratelimit.py"
    assert result["matches"][0]["matched_keywords"] == ["ratelimit"]
    assert result["matches"][0]["match_score"] == round(1 / 3, 3)


@pytest.mark.parametrize("query", ["", " \t\n"])
def test_empty_query_lists_candidates_unranked(mini_workspace: Path, query: str):
    result = find_files(mini_workspace, query=query)

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


@pytest.mark.parametrize("query", ["where", "WHEN", "Who", "is"])
def test_stopword_literal_ranks_matching_filename_instead_of_listing(tmp_path: Path, query: str):
    (tmp_path / "aaa.rs").write_text("", encoding="utf-8")
    (tmp_path / "filters").mkdir()
    name = query.casefold()
    (tmp_path / "filters" / f"{name}.rs").write_text("", encoding="utf-8")
    (tmp_path / "filters" / f"{name}ver.rs").write_text("", encoding="utf-8")

    result = find_files(tmp_path, f" {query} ", top_k=1)

    assert result["matches"] == [{"path": f"filters/{name}.rs", "match_score": 1.0, "matched_keywords": [name]}]
    listing = find_files(tmp_path, "", top_k=1)
    assert listing["matches"] == [{"path": "aaa.rs", "match_score": None, "matched_keywords": []}]


@pytest.mark.parametrize("query", ["where/in", r"where\in", "where_in"])
def test_literal_path_retains_stopword_components_for_ranking(tmp_path: Path, query: str):
    (tmp_path / "where").mkdir()
    (tmp_path / "where" / "in.rs").write_text("", encoding="utf-8")
    (tmp_path / "where" / "else.rs").write_text("", encoding="utf-8")
    (tmp_path / "aaa.rs").write_text("", encoding="utf-8")

    result = find_files(tmp_path, query)

    assert result["matches"] == [
        {"path": "where/in.rs", "match_score": 1.0, "matched_keywords": ["where", "in"]},
        {"path": "where/else.rs", "match_score": 0.5, "matched_keywords": ["where"]},
    ]


def test_stopwords_in_prose_do_not_change_path_ranking(tmp_path: Path):
    (tmp_path / "where.rs").write_text("", encoding="utf-8")
    (tmp_path / "quiescent.rs").write_text("", encoding="utf-8")

    result = find_files(tmp_path, "where is quiescent")

    assert result["matches"] == [{"path": "quiescent.rs", "match_score": 1.0, "matched_keywords": ["quiescent"]}]


@pytest.mark.parametrize("query", ["where", "where is", "?!"])
def test_nonblank_query_without_path_matches_does_not_list_files(tmp_path: Path, query: str):
    (tmp_path / "aaa.rs").write_text("", encoding="utf-8")

    assert find_files(tmp_path, query)["matches"] == []
