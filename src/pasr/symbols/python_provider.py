"""Python symbol provider (stdlib ``ast``, no third-party parser)."""

from __future__ import annotations

import ast

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

    refs: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            refs.add(child.id)
        elif isinstance(child, ast.Attribute):
            refs.add(child.attr)
    refs -= defines

    kind = "class" if isinstance(node, ast.ClassDef) else "function"
    start, end = _char_bounds(node, line_starts)
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
    start, end = _char_bounds(node, line_starts)
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
    start, end = _char_bounds(node, line_starts)
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
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _char_bounds(node: ast.AST, line_starts: list[int]) -> tuple[int, int]:
    start = line_starts[int(node.lineno) - 1] + int(node.col_offset)
    end = line_starts[int(node.end_lineno) - 1] + int(node.end_col_offset)
    return start, end
