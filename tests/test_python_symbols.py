import unittest

from _helpers import WhitespaceTokenizer

from pasr.symbols.python_symbols import generate_python_symbol_candidates


class PythonSymbolCandidateTests(unittest.TestCase):
    def test_selects_raw_function_window_with_symbol_dependencies(self):
        text = """def harmless(value):
    return value

def ensure_inside_workspace(path, workspace):
    resolved = path.resolve()
    resolved.relative_to(workspace)
    return resolved
"""
        tokenizer = WhitespaceTokenizer([text, "workspace path escapes"])

        candidates = generate_python_symbol_candidates(
            text=text,
            query="workspace path escapes",
            tokenizer=tokenizer,
            source="safety.py",
            max_tokens=64,
        )

        self.assertTrue(candidates)
        selected = candidates[0]
        self.assertIn("relative_to", selected.text)
        self.assertEqual(selected.selection_reasons, ("python_symbol_dependency",))
        self.assertEqual(selected.metadata["node_type"], "FunctionDef")
        self.assertIn("workspace", selected.metadata["symbols"])
        self.assertIn("relative_to", selected.metadata["dependencies"])
        self.assertLessEqual(selected.token_count, 64)

    def test_ignores_non_python_and_invalid_python_sources(self):
        tokenizer = WhitespaceTokenizer(["not valid python", "query"])

        self.assertEqual(
            generate_python_symbol_candidates("text", "query", tokenizer, "README.md"),
            [],
        )
        self.assertEqual(
            generate_python_symbol_candidates("def broken(", "query", tokenizer, "broken.py"),
            [],
        )

    def test_splits_large_nodes_into_bounded_raw_windows(self):
        body = "\n".join(f"    value_{index} = path" for index in range(80))
        text = f"def inspect_path(path):\n{body}\n"
        tokenizer = WhitespaceTokenizer([text, "inspect path"])

        candidates = generate_python_symbol_candidates(
            text=text,
            query="inspect path",
            tokenizer=tokenizer,
            source="large.py",
            max_tokens=16,
        )

        self.assertGreater(len(candidates), 1)
        self.assertTrue(all(candidate.token_count <= 16 for candidate in candidates))

    def test_accepts_unique_repo_snippet_provenance_after_python_path(self):
        text = "def locate_client(config):\n    return Client(config=config)\n"
        tokenizer = WhitespaceTokenizer([text, "client config"])

        candidates = generate_python_symbol_candidates(
            text=text,
            query="client config",
            tokenizer=tokenizer,
            source="real-repository/src/client.py::2:locate_client",
            max_tokens=64,
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].source, "real-repository/src/client.py::2:locate_client")


if __name__ == "__main__":
    unittest.main()
