import unittest

from pasr.symbols import get_provider, supported_extensions, symbol_candidates
from pasr.symbols.python_provider import PythonSymbolProvider
from pasr.tokenize import WhitespaceTokenizer

PY = """import os
from math import sqrt as root

WIDTH = 80


def area(w, h):
    return w * h


class Box:
    def volume(self, w, h, d):
        return area(w, h) * d
"""

JS = """import { logger } from "./logger";

const LIMIT = 10;

export function entry(payload) {
  return process(payload);
}

function process(x) {
  logger.info(x);
  return x + LIMIT;
}
"""


class RegistryTests(unittest.TestCase):
    def test_get_provider_by_extension(self):
        self.assertEqual(get_provider("pkg/a.py").language, "python")
        self.assertEqual(get_provider("pkg/a.js").language, "javascript")
        self.assertEqual(get_provider("pkg/a.ts").language, "typescript")
        self.assertIsNone(get_provider("pkg/a.rb"))
        self.assertIn(".py", supported_extensions())


class PythonProviderTests(unittest.TestCase):
    def test_extracts_definitions_imports_and_module_vars(self):
        fs = PythonSymbolProvider().parse("m.py", PY)
        names = {d.name for d in fs.definitions}
        self.assertLessEqual({"area", "Box", "volume", "WIDTH"}, names)
        imports = {name for imp in fs.imports for name in imp.defines}
        self.assertLessEqual({"os", "root"}, imports)

        area = next(d for d in fs.definitions if d.name == "area")
        self.assertEqual(area.kind, "function")
        self.assertLessEqual({"area", "w", "h"}, set(area.defines))

        volume = next(d for d in fs.definitions if d.name == "volume")
        self.assertIn("area", volume.refs)

    def test_syntax_error_yields_empty_symbols(self):
        fs = PythonSymbolProvider().parse("bad.py", "def broken(")
        self.assertEqual((fs.definitions, fs.imports), ((), ()))

    def test_unicode_ast_byte_columns_preserve_exact_source(self):
        text = 'é = "✓"; answer = "YES"; next_value = 4\n'
        symbols = PythonSymbolProvider().parse("unicode.py", text)
        expected = ['é = "✓"', 'answer = "YES"', "next_value = 4"]
        self.assertEqual([d.text for d in symbols.definitions], expected)
        for definition in symbols.definitions:
            self.assertEqual(text[definition.char_start : definition.char_end], definition.text)

    def test_non_newline_separators_do_not_shift_ast_source(self):
        for prefix in ("x = 1\f\n", 'label = "a\u2028b"\n'):
            text = prefix + "def target():\n    return 2\n"
            symbols = PythonSymbolProvider().parse("m.py", text)
            target = next(d for d in symbols.definitions if d.name == "target")
            self.assertEqual(target.text, "def target():\n    return 2")
            self.assertEqual((target.line_start, target.line_end), (2, 3))

    def test_all_parameter_bindings_are_definitions_not_references(self):
        text = "def invoke(pos, /, normal, *args, key=1, **kwargs):\n    return pos, args, kwargs, key\n"
        definition = PythonSymbolProvider().parse("m.py", text).definitions[0]
        self.assertLessEqual({"pos", "normal", "args", "key", "kwargs"}, definition.defines)
        self.assertFalse({"pos", "args", "kwargs"} & definition.refs)


class TreeSitterProviderTests(unittest.TestCase):
    def test_extracts_js_functions_import_and_module_const(self):
        provider = get_provider("web/util.js")
        fs = provider.parse("web/util.js", JS)
        names = {d.name for d in fs.definitions}
        self.assertLessEqual({"entry", "process", "LIMIT"}, names)
        self.assertIn("logger", {name for imp in fs.imports for name in imp.defines})

        process = next(d for d in fs.definitions if d.name == "process")
        self.assertIn("LIMIT", process.refs)
        # a local const is not a module symbol
        self.assertNotIn("x", names)

    def test_typescript_alias_and_enum_have_filterable_kinds(self):
        text = "type Alias = string;\nenum Mode { Fast }\n"
        for source in ("types.ts", "types.tsx"):
            symbols = get_provider(source).parse(source, text)
            self.assertEqual({d.name: d.kind for d in symbols.definitions}, {"Alias": "type", "Mode": "enum"})

    def test_physical_newlines_and_unicode_preserve_original_spans(self):
        for newline in ("\n", "\r\n", "\r"):
            with self.subTest(newline=newline):
                lines = ['const label = "café\u2028x";', "function target() {", "  return label;", "}"]
                text = newline.join(lines) + newline
                symbols = get_provider("m.js").parse("m.js", text)
                target = next(d for d in symbols.definitions if d.name == "target")
                self.assertEqual((target.line_start, target.line_end), (2, 4))
                self.assertEqual(target.text, newline.join(lines[1:]))
                self.assertEqual(text[target.char_start : target.char_end], target.text)
                self.assertEqual(symbols.definitions[0].text, 'label = "café\u2028x"')


class SymbolCandidateTests(unittest.TestCase):
    def test_candidates_align_to_line_additive_offsets(self):
        provider = PythonSymbolProvider()
        fs = provider.parse("m.py", PY)
        tok = WhitespaceTokenizer()
        candidates = symbol_candidates(fs, "compute the area of a box", PY, tok)

        self.assertTrue(candidates)
        top = candidates[0]
        self.assertEqual(top.selection_reasons, ("symbol",))
        self.assertIn("provenance", top.metadata)
        self.assertEqual(top.token_count, top.end - top.start)
        self.assertIn("symbols", top.metadata)

    def test_no_query_terms_returns_nothing(self):
        fs = PythonSymbolProvider().parse("m.py", PY)
        self.assertEqual(symbol_candidates(fs, "   ", PY, WhitespaceTokenizer()), [])

    def test_same_line_symbols_keep_the_complete_coordinate_window(self):
        text = 'alpha = "needle"; beta = "needed"\n'
        symbols = PythonSymbolProvider().parse("m.py", text)
        candidates = symbol_candidates(symbols, "needle needed", text, WhitespaceTokenizer())
        self.assertEqual([candidate.text for candidate in candidates], [text])

    def test_physical_lines_keep_complete_symbol_body_and_token_bounds(self):
        for newline in ("\n", "\r\n", "\r"):
            with self.subTest(newline=newline):
                prefix = 'label = "a\u2028b\fc"' + newline
                body = "def target():" + newline + '    return "café"' + newline
                text = prefix + body
                tok = WhitespaceTokenizer()
                symbols = PythonSymbolProvider().parse("m.py", text)
                (candidate,) = symbol_candidates(symbols, "target", text, tok)
                self.assertEqual(candidate.text, body)
                self.assertEqual(candidate.metadata["provenance"], "m.py:2-3")
                self.assertEqual(candidate.start, tok.count(prefix))
                self.assertEqual(candidate.end, tok.count(prefix) + tok.count(body))


if __name__ == "__main__":
    unittest.main()
