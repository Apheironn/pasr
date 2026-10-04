"""Workspace discovery tests over a synthetic tree (no repo layout assumptions)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pasr.file_discovery import (
    FileDiscoveryConfig,
    discover_workspace_files,
    relative_file_paths,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "outputs").mkdir()
    (tmp_path / "README.md").write_text("# readme\n", encoding="utf-8")
    (tmp_path / "docs" / "architecture.md").write_text("# arch\n" * 5, encoding="utf-8")
    (tmp_path / "docs" / "guide.md").write_text("# guide\n", encoding="utf-8")
    (tmp_path / "src" / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "src" / "pkg" / "b.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "outputs" / "run.md").write_text("generated\n", encoding="utf-8")
    return tmp_path


def test_discovers_explicit_files(workspace: Path) -> None:
    files = discover_workspace_files(
        workspace_root=workspace,
        include_patterns=["README.md", "docs/architecture.md"],
    )

    assert relative_file_paths(files) == ["README.md", "docs/architecture.md"]
    assert all(file.path.is_absolute() for file in files)
    assert all(file.size_bytes > 0 for file in files)


def test_discovers_directory_and_filters_generated_outputs(workspace: Path) -> None:
    files = discover_workspace_files(
        workspace_root=workspace,
        include_patterns=["docs", "outputs"],
    )
    paths = relative_file_paths(files)

    assert "docs/architecture.md" in paths
    assert "docs/guide.md" in paths
    assert "outputs/run.md" in paths  # not a build dir; only .gitignore / excludes filter it


def test_discovers_globbed_python_files_sorted(workspace: Path) -> None:
    files = discover_workspace_files(
        workspace_root=workspace,
        include_patterns=["src/pkg/*.py"],
    )
    paths = relative_file_paths(files)

    assert paths == ["src/pkg/a.py", "src/pkg/b.py"]
    assert paths == sorted(paths)


def test_applies_extra_exclude_patterns(workspace: Path) -> None:
    files = discover_workspace_files(
        workspace_root=workspace,
        include_patterns=["README.md", "docs/architecture.md"],
        extra_exclude_patterns=["docs/architecture.md"],
    )

    assert relative_file_paths(files) == ["README.md"]


def test_applies_file_size_limit(workspace: Path) -> None:
    files = discover_workspace_files(
        workspace_root=workspace,
        include_patterns=["docs/architecture.md"],
        config=FileDiscoveryConfig(max_file_bytes=1),
    )

    assert files == []


def test_rejects_parent_directory_patterns(workspace: Path) -> None:
    with pytest.raises(ValueError, match="must stay inside workspace"):
        discover_workspace_files(
            workspace_root=workspace,
            include_patterns=["../outside.md"],
        )


def test_rejects_empty_include_patterns(workspace: Path) -> None:
    with pytest.raises(ValueError, match="must be a non-empty list"):
        discover_workspace_files(workspace_root=workspace, include_patterns=[])


def test_discovers_broadened_language_extensions(workspace: Path) -> None:
    (workspace / "src" / "pkg" / "client.ts").write_text("export const x = 1\n", encoding="utf-8")
    (workspace / "src" / "pkg" / "server.go").write_text("package main\n", encoding="utf-8")

    files = discover_workspace_files(
        workspace_root=workspace,
        include_patterns=["src/pkg"],
    )
    paths = set(relative_file_paths(files))

    assert {"src/pkg/client.ts", "src/pkg/server.go"} <= paths


def test_respects_gitignore(workspace: Path) -> None:
    (workspace / ".gitignore").write_text("*.log\ngenerated/\n", encoding="utf-8")
    (workspace / "keep.md").write_text("keep\n", encoding="utf-8")
    (workspace / "debug.log").write_text("noise\n", encoding="utf-8")
    (workspace / "generated").mkdir()
    (workspace / "generated" / "out.md").write_text("noise\n", encoding="utf-8")

    files = discover_workspace_files(workspace_root=workspace, include_patterns=["."])
    paths = set(relative_file_paths(files))

    assert "keep.md" in paths
    assert "debug.log" not in paths
    assert "generated/out.md" not in paths


def test_gitignore_can_be_disabled(workspace: Path) -> None:
    (workspace / ".gitignore").write_text("*.log\n", encoding="utf-8")
    (workspace / "debug.log").write_text("noise\n", encoding="utf-8")

    files = discover_workspace_files(
        workspace_root=workspace,
        include_patterns=["debug.log"],
        config=FileDiscoveryConfig(respect_gitignore=False, allowed_extensions=None),
    )

    assert relative_file_paths(files) == ["debug.log"]


def test_gitignore_overrides_local_exclude_and_refreshes(workspace: Path) -> None:
    (workspace / ".git" / "info").mkdir(parents=True)
    (workspace / ".git" / "info" / "exclude").write_text("README.md\n", encoding="utf-8")
    ignore = workspace / ".gitignore"
    ignore.write_text("!README.md\n", encoding="utf-8")
    assert relative_file_paths(discover_workspace_files(workspace, ["README.md"])) == ["README.md"]

    ignore.write_text("README.md\n", encoding="utf-8")
    assert discover_workspace_files(workspace, ["README.md"]) == []


@pytest.mark.parametrize("extension", [".mts", ".cts"])
def test_discovers_typescript_module_extensions(workspace: Path, extension: str) -> None:
    name = f"module{extension}"
    (workspace / name).write_text("export const value = 1;\n", encoding="utf-8")
    assert relative_file_paths(discover_workspace_files(workspace, [name])) == [name]


def test_nested_ignore_precedence_and_parent_directory_barriers(tmp_path: Path) -> None:
    files = {
        ".gitignore": "*.tmp.py\nblocked/\n!blocked/keep.py\n",
        "pkg/.gitignore": "vendor/\nbuild/*\n!build/keep.py\n!keep.tmp.py\n/local.py\n",
        "pkg/deep/.gitignore": "!deep.tmp.py\nkeep.tmp.py\n",
        "pkg/vendor/no.py": "",
        "pkg/build/no.py": "",
        "pkg/build/keep.py": "",
        "pkg/keep.tmp.py": "",
        "pkg/drop.tmp.py": "",
        "pkg/local.py": "",
        "pkg/deep/local.py": "",
        "pkg/deep/deep.tmp.py": "",
        "pkg/deep/keep.tmp.py": "",
        "blocked/.gitignore": "!keep.py\n",
        "blocked/keep.py": "",
    }
    for relative, text in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    expected = ["pkg/build/keep.py", "pkg/deep/deep.tmp.py", "pkg/deep/local.py", "pkg/keep.tmp.py"]
    for include in (["."], ["**/*.py"], ["pkg"], ["pkg/**/*.py"]):
        assert relative_file_paths(discover_workspace_files(tmp_path, include)) == expected
    assert discover_workspace_files(tmp_path, ["blocked/keep.py"]) == []
    assert discover_workspace_files(tmp_path, ["pkg/vendor/no.py"]) == []


def test_discovery_never_follows_directory_junction_outside_workspace(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "good.py").write_text("good = 1\n", encoding="utf-8")
    (outside / "secret.py").write_text("secret = 1\n", encoding="utf-8")
    link = root / "linked"
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.warns(RuntimeWarning, match="Skipping directory linked"):
            assert relative_file_paths(discover_workspace_files(root, ["."])) == ["good.py"]
        with pytest.raises(ValueError, match="escapes workspace"):
            discover_workspace_files(root, ["linked"])
    finally:
        if sys.platform == "win32":
            os.rmdir(link)
        else:
            link.unlink()
