"""Python symbol provider (stdlib ``ast``, no third-party parser)."""

from __future__ import annotations

import ast

from pasr.source_text import physical_lines
from pasr.symbols.base import FileSymbols, SymbolDef

_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_ASSIGN_NODES = (ast.Assign, ast.AnnAssign)


class PythonSymbolProvider:
    """Parses ``.py`` sources into :class:`FileSymbols` via the ``ast`` module."""

    language = "python"

    def parse(self, source: str, text: str) -> FileSymbols:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return FileSymbols(source=source, language=self.language, definitions=(), imports=())

        line_starts = _line_start_offsets(text)
        definitions: list[SymbolDef] = []
        imports: list[SymbolDef] = []

        for node in ast.iter_child_nodes(tree):  # module-level assignments only
            if isinstance(node, _ASSIGN_NODES) and hasattr(node, "end_lineno"):
                definitions.append(_assignment(node, source, text, line_starts))
        for node in ast.walk(tree):
            if isinstance(node, _DEF_NODES) and hasattr(node, "end_lineno"):
                definitions.append(_definition(node, source, text, line_starts))
            elif isinstance(node, (ast.Import, ast.ImportFrom)) and hasattr(node, "end_lineno"):
                imports.append(_import(node, source, text, line_starts))

        return FileSymbols(
            source=source,
            language=self.language,
            definitions=tuple(definitions),
            imports=tuple(imports),
        )


def _definition(node: ast.AST, source: str, text: str, line_starts: list[int]) -> SymbolDef:
    name = str(getattr(node, "name", "") or "")
    defines: set[str] = {name} if name else set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        defines.update(arg.arg for arg in node.args.args)
        defines.update(arg.arg for arg in node.args.kwonlyargs)
        defines.update(arg.arg for arg in node.args.posonlyargs)
        if node.args.vararg is not None:
            defines.add(node.args.vararg.arg)
        if node.args.kwarg is not None:
            defines.add(node.args.kwarg.arg)

    refs: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            refs.add(child.id)
        elif isinstance(child, ast.Attribute):
            refs.add(child.attr)
    refs -= defines

    kind = "class" if isinstance(node, ast.ClassDef) else "function"
    start, end = _char_bounds(node, line_starts, text)
    return SymbolDef(
        name=name,
        kind=kind,
        source=source,
        line_start=int(node.lineno),
        line_end=int(node.end_lineno),
        char_start=start,
        char_end=end,
        defines=frozenset(defines),
        refs=frozenset(refs),
        text=text[start:end],
    )


def _assignment(node: ast.AST, source: str, text: str, line_starts: list[int]) -> SymbolDef:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names = {t.id for t in targets if isinstance(t, ast.Name)}
    refs = {
        child.id for child in ast.walk(node) if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    } - names
    start, end = _char_bounds(node, line_starts, text)
    return SymbolDef(
        name=sorted(names)[0] if names else "<assignment>",
        kind="variable",
        source=source,
        line_start=int(node.lineno),
        line_end=int(node.end_lineno),
        char_start=start,
        char_end=end,
        defines=frozenset(names),
        refs=frozenset(refs),
        text=text[start:end],
    )


def _import(node: ast.AST, source: str, text: str, line_starts: list[int]) -> SymbolDef:
    names: set[str] = set()
    imported: set[str] = set()
    for alias in getattr(node, "names", []):
        local = alias.asname or alias.name.split(".", 1)[0]
        names.add(local)
        imported.add(alias.name)
    start, end = _char_bounds(node, line_starts, text)
    return SymbolDef(
        name=sorted(names)[0] if names else "import",
        kind="import",
        source=source,
        line_start=int(node.lineno),
        line_end=int(node.end_lineno),
        char_start=start,
        char_end=end,
        defines=frozenset(names),
        refs=frozenset(imported),
        text=text[start:end],
    )


def _line_start_offsets(text: str) -> list[int]:
    starts = [0]
    for line in physical_lines(text, keepends=True):
        starts.append(starts[-1] + len(line))
    return starts


def _char_bounds(node: ast.AST, line_starts: list[int], text: str) -> tuple[int, int]:
    # AST columns are UTF-8 byte offsets, whereas SymbolDef offsets index str.
    def offset(lineno: int, column: int) -> int:
        start = line_starts[lineno - 1]
        end = line_starts[lineno] if lineno < len(line_starts) else len(text)
        line = text[start:end]
        if line.isascii():
            return start + column
        return start + len(line.encode("utf-8")[:column].decode("utf-8"))

    return offset(int(node.lineno), int(node.col_offset)), offset(int(node.end_lineno), int(node.end_col_offset))
