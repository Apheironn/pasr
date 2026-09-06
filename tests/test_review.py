import unittest
from pathlib import Path

from pasr.review import FileChange, parse_unified_diff, render_review, review_context
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

    def test_unresolved_file_is_reported_not_fatal(self):
        diff = _DIFF.replace("app/pipeline.py", "app/not_here.py")
        result = review_context(parse_unified_diff(diff), _TEXTS, tokenizer=WhitespaceTokenizer())
        self.assertEqual(result["changed_files"], [])
        self.assertEqual(result["unresolved_files"], ["app/not_here.py"])
        self.assertIn("Review context", render_review(result))


class ReadGitDiffTests(unittest.TestCase):
    def test_non_git_directory_raises_runtimeerror(self):
        import tempfile

        from pasr.review import read_git_diff

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                read_git_diff(Path(tmp), staged=False, ref_range="")


if __name__ == "__main__":
    unittest.main()
