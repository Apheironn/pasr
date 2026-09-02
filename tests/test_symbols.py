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


if __name__ == "__main__":
    unittest.main()
