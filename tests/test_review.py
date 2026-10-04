import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pasr.cli import main
from pasr.review import FileChange, parse_unified_diff, read_review_inputs, render_review, review_context
from pasr.tokenize import WhitespaceTokenizer

TRACE_REPO = Path(__file__).parent / "fixtures" / "trace_repo"
_TEXTS = {
    path.relative_to(TRACE_REPO).as_posix(): path.read_text(encoding="utf-8")
    for path in sorted(TRACE_REPO.rglob("*"))
    if path.is_file()
}

_DIFF = """\
diff --git a/app/pipeline.py b/app/pipeline.py
index 111..222 100644
--- a/app/pipeline.py
+++ b/app/pipeline.py
@@ -26,0 +27 @@ def normalize(row):
+    # tightened
"""


class ParseUnifiedDiffTests(unittest.TestCase):
    def test_extracts_new_side_hunks(self):
        changes = parse_unified_diff(_DIFF)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].path, "app/pipeline.py")
        self.assertEqual(changes[0].hunks, [(27, 1)])

    def test_deleted_file_is_dropped(self):
        deleted = "--- a/gone.py\n+++ /dev/null\n@@ -1,3 +0,0 @@\n-x\n"
        self.assertEqual(parse_unified_diff(deleted), [])

    def test_git_quoted_utf8_path_resolves_to_the_changed_file(self):
        diff = '--- "a/caf\\303\\251.py"\n+++ "b/caf\\303\\251.py"\n@@ -2 +2 @@\n-    return 0\n+    return 1\n'
        changes = parse_unified_diff(diff)
        result = review_context(changes, {"café.py": "def target():\n    return 1\n"})
        self.assertEqual(result["unresolved_files"], [])
        self.assertEqual(result["changed_files"], ["café.py"])
        self.assertEqual([span["name"] for span in result["spans"]], ["target"])

    def test_overlaps(self):
        change = FileChange("f.py", [(27, 1)])
        self.assertTrue(change.overlaps(26, 27))  # normalize spans 26-27
        self.assertFalse(change.overlaps(9, 11))  # run_pipeline spans 9-11


class ReviewContextTests(unittest.TestCase):
    def _review(self, budget=4000):
        return review_context(parse_unified_diff(_DIFF), _TEXTS, tokenizer=WhitespaceTokenizer(), budget_tokens=budget)

    def test_touched_and_impacted(self):
        result = self._review()
        self.assertEqual(result["changed_files"], ["app/pipeline.py"])
        touched = " ".join(result["touched_symbols"])
        impacted = " ".join(result["impacted_callers"])
        self.assertIn("normalize", touched)
        self.assertNotIn("normalize", impacted)  # the touched def is not repeated as a caller
        self.assertIn("run_pipeline", impacted)  # run_pipeline calls normalize
        self.assertIn("# changed definitions", result["context"])
        self.assertIn("# callers that could be affected", result["context"])
        self.assertLessEqual(result["token_count"], 4000)
        self.assertTrue(result["within_budget"])

    def test_is_deterministic(self):
        self.assertEqual(self._review(), self._review())

    def test_specificity_filter_keeps_the_innermost_touched_def(self):
        # a hunk inside one function must not also pull an enclosing definition
        result = self._review()
        self.assertEqual(len(result["touched_symbols"]), 1)
        self.assertIn("function normalize", result["touched_symbols"][0])

    def test_rendered_context_obeys_budget_including_headings_and_provenance(self):
        texts = {"a.py": "def target():\n    return 1\n\ndef caller():\n    return target()\n"}
        changes = [FileChange("a.py", [(2, 1)])]
        tok = WhitespaceTokenizer()
        for budget in range(31):
            with self.subTest(budget=budget):
                result = review_context(changes, texts, tokenizer=tok, budget_tokens=budget)
                self.assertEqual(result["token_count"], tok.count(result["context"]))
                self.assertLessEqual(result["token_count"], budget)
                self.assertTrue(result["within_budget"])
                if result["spans"]:
                    self.assertIn("def target():\n    return 1", result["context"])
                else:
                    self.assertEqual(result["context"], "")
        complete = review_context(changes, texts, tokenizer=tok, budget_tokens=21)
        self.assertEqual({span["name"] for span in complete["spans"]}, {"target", "caller"})

    def test_rejects_negative_budget_and_depth_even_without_changes(self):
        for options in ({"budget_tokens": -1}, {"callers_depth": -1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                review_context([], {}, **options)

    def test_unresolved_file_is_reported_not_fatal(self):
        diff = _DIFF.replace("app/pipeline.py", "app/not_here.py")
        result = review_context(parse_unified_diff(diff), _TEXTS, tokenizer=WhitespaceTokenizer())
        self.assertEqual(result["changed_files"], [])
        self.assertEqual(result["unresolved_files"], ["app/not_here.py"])
        self.assertIn("Review context", render_review(result))


@unittest.skipUnless(shutil.which("git"), "Git is required")
class GitReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pasr review ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.email", "review@example.invalid")
        self.git("config", "user.name", "Review tests")
        self.git("config", "core.autocrlf", "false")

    def git(self, *arguments, input_bytes=None, check=True):
        result = subprocess.run(
            ["git", "-C", str(self.root), *arguments], input=input_bytes, capture_output=True, check=check
        )
        return result.stdout.decode("utf-8").strip()

    def write(self, path, text):
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")

    def source(self, target, caller):
        self.write("target.py", f"def target():\n    return {target}\n")
        self.write("caller.py", f"def caller():\n    return target() + {caller}\n")

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def cli(self, *arguments, workspace=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["--workspace", str(workspace or self.root), "review", *arguments, "--json"])
        return code, json.loads(stdout.getvalue()) if code == 0 else None, stderr.getvalue()

    def history(self):
        self.source(0, 6)
        base = self.commit("base")
        self.source(6, 6)
        six = self.commit("six")
        self.source(7, 8)
        self.commit("head")
        self.source(8, 8)
        self.git("add", ".")
        self.source(9, 9)
        return base, six

    def test_source_and_callers_follow_selected_revision_under_budget(self):
        base, six = self.history()
        for options, value, kind in (
            (["--staged"], 8, "index"),
            (["--range", f"{base}..{six}"], 6, "commit"),
            (["--range", f"{base}...{six}"], 6, "commit"),
            ([], 9, "worktree"),
        ):
            with self.subTest(kind=kind, options=options):
                code, result, error = self.cli(*options, "--budget", "160")
                self.assertEqual(code, 0, error)
                self.assertIn(f"    return {value}", result["context"])
                self.assertIn(f"    return target() + {value}", result["context"])
                self.assertEqual(result["source_revision"]["kind"], kind)
                self.assertLessEqual(result["token_count"], 160)
                if kind != "worktree":
                    self.assertNotIn("return 9", result["context"])
                    self.assertNotIn("target() + 9", result["context"])
                    self.assertIn("caller", " ".join(result["impacted_callers"]))
                if kind == "commit":
                    self.assertEqual(result["source_revision"]["commit"], six)

    def test_unborn_head_uses_index_and_decodes_quoted_utf8_paths(self):
        path = "src/café space.py"
        self.write(path, "def target():\n    return 8\n")
        self.git("add", ".")
        self.write(path, "def target():\n    return 9\n")
        code, result, error = self.cli("--staged")
        self.assertEqual(code, 0, error)
        self.assertEqual(result["changed_files"], [path])
        self.assertIn("return 8", result["context"])
        self.assertIsNone(result["source_revision"]["base_commit"])

    def test_rename_and_delete_read_new_paths_even_when_missing_in_worktree(self):
        self.write("old café.py", "def target():\n    value = 6\n    return value\n")
        self.write("gone.py", "def gone():\n    return 0\n")
        base = self.commit("base")
        self.git("mv", "old café.py", "new café space.py")
        self.write("new café space.py", "def target():\n    value = 8\n    return value\n")
        self.git("rm", "gone.py")
        end = self.commit("renamed")
        (self.root / "new café space.py").unlink()
        code, result, error = self.cli("--range", f"{base}..{end}")
        self.assertEqual(code, 0, error)
        self.assertEqual(result["changed_files"], ["new café space.py"])
        self.assertIn("value = 8", result["context"])
        self.assertEqual(result["unresolved_files"], [])

    def test_triple_dot_uses_merge_base_not_left_tree(self):
        self.source(0, 6)
        base = self.commit("base")
        self.source(6, 6)
        left = self.commit("left")
        self.git("checkout", "-q", "--detach", base)
        self.source(6, 6)
        right = self.commit("right")
        code, result, error = self.cli("--range", f"{left}...{right}")
        self.assertEqual(code, 0, error)
        self.assertIn("return 6", result["context"])
        self.assertEqual(result["source_revision"]["base_commit"], base)
        code, result, error = self.cli("--range", f"{left}..{right}")
        self.assertEqual(code, 0, error)
        self.assertEqual(result["context"], "")

    def test_pinned_tree_survives_index_and_branch_changes_before_diff(self):
        from unittest.mock import patch

        import pasr.review as review

        base, six = self.history()
        original_git = review._git
        for options, expected in (({"staged": True}, 8), ({"ref_range": f"{base}..review-end"}, 6)):
            self.git("branch", "-f", "review-end", six)
            self.source(8, 8)
            self.git("add", ".")
            mutated = False

            def mutate_before_diff(root, *arguments, **kwargs):
                nonlocal mutated
                if arguments[0] == "diff" and not mutated:
                    mutated = True
                    self.source(9, 9)
                    self.git("add", ".")
                    self.git("branch", "-f", "review-end", "HEAD")
                return original_git(root, *arguments, **kwargs)

            with self.subTest(options=options), patch.object(review, "_git", side_effect=mutate_before_diff):
                diff, texts, revision = read_review_inputs(self.root, ["."], **options)
                result = review_context(parse_unified_diff(diff), texts)
                self.assertIn(f"return {expected}", result["context"])
                self.assertNotIn("return 9", result["context"])
                self.assertEqual(texts["caller.py"], f"def caller():\n    return target() + {expected}\n")
                self.assertIn("tree", revision)

    def test_pinned_ignore_scope_subworkspace_and_symlink_entries(self):
        self.write("scope/target.py", "def target():\n    return 8\n")
        self.write("scope/.gitignore", "ignored.py\nnested/*.py\n")
        self.write("scope/nested/.gitignore", "!keep.py\n")
        for path in ("ignored.py", "nested/no.py", "nested/keep.py", ".hidden.py", "node_modules/no.py"):
            self.write("scope/" + path, f"def caller():\n    return target() + {len(path)}\n")
        self.write("outside.py", "def outside():\n    return target() + 999\n")
        self.git("add", "-f", ".")
        symlink = self.git("hash-object", "-w", "--stdin", input_bytes=b"../../outside.py")
        self.git("update-index", "--add", "--cacheinfo", f"120000,{symlink},scope/link.py")
        self.write("scope/link.py", "def leak():\n    return target() + 9999\n")
        self.write("scope/.gitignore", "")
        self.write("scope/nested/.gitignore", "")
        diff, texts, _ = read_review_inputs(self.root / "scope", ["."], staged=True)
        self.assertEqual(set(texts), {"target.py", "nested/keep.py"})
        self.assertIn("+++ b/target.py", diff)
        _, scoped, _ = read_review_inputs(self.root / "scope", ["./nested/**/*.py"], staged=True)
        self.assertEqual(set(scoped), {"nested/keep.py"})
        with self.assertRaises(ValueError):
            read_review_inputs(self.root / "scope", ["../outside.py"], staged=True)

    def test_external_diff_is_explicitly_worktree_and_rejects_mixed_modes(self):
        base, six = self.history()
        self.write("external.diff", "--- a/target.py\n+++ b/target.py\n@@ -2 +2 @@\n-    return 0\n+    return 9\n")
        code, result, error = self.cli("--diff", str(self.root / "external.diff"))
        self.assertEqual(code, 0, error)
        self.assertEqual(result["source_revision"], {"kind": "worktree", "diff": "external"})
        self.assertIn("target() + 9", result["context"])
        for options in ({"staged": True}, {"ref_range": f"{base}..{six}"}):
            with self.assertRaises(ValueError):
                read_review_inputs(self.root, ["."], diff_path=self.root / "external.diff", **options)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["review", "--staged", "--range", f"{base}..{six}"])
        self.assertEqual(raised.exception.code, 2)

    def test_errors_are_nonzero_without_falling_back_to_worktree(self):
        self.source(0, 0)
        self.commit("base")
        for options in (
            ["--range", "missing..HEAD"],
            ["--range", "HEAD"],
            ["--range=--output=outside..HEAD"],
            ["--diff", str(self.root / "missing.diff")],
        ):
            with self.subTest(options=options):
                code, result, error = self.cli(*options)
                self.assertEqual(code, 2)
                self.assertIsNone(result)
                self.assertIn("error:", error)
        (self.root / "invalid.diff").write_bytes(b"\xff")
        self.assertEqual(self.cli("--diff", str(self.root / "invalid.diff"))[0], 2)
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(RuntimeError):
                read_review_inputs(Path(other), ["."])

    def test_unmerged_index_fails_honestly(self):
        self.source(0, 0)
        base = self.commit("base")
        self.source(1, 0)
        left = self.commit("left")
        self.git("checkout", "-q", "--detach", base)
        self.source(2, 0)
        self.commit("right")
        self.git("merge", "--no-commit", left, check=False)
        code, result, error = self.cli("--staged")
        self.assertEqual(code, 2)
        self.assertIsNone(result)
        self.assertIn("unmerged", error)


if __name__ == "__main__":
    unittest.main()
