"""Generic tree-sitter symbol provider (JavaScript / TypeScript / Rust).

A node-walk with a small per-language config rather than tree-sitter queries: fewer
moving parts, fully deterministic. Grammars are imported lazily so the base package
stays light until a non-Python file is actually parsed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from pasr.symbols.base import FileSymbols, SymbolDef

_JS_DEF_NODES = frozenset(
    {
        "function_declaration",
        "generator_function_declaration",
        "class_declaration",
        "method_definition",
    }
)
_JS_FUNC_VALUE_NODES = frozenset({"arrow_function", "function", "function_expression", "class", "class_expression"})
_JS_IDENT_NODES = frozenset({"identifier", "property_identifier", "shorthand_property_identifier", "type_identifier"})
_FUNC_SCOPE = frozenset(
    {
        "function_declaration",
        "generator_function_declaration",
        "method_definition",
        "arrow_function",
        "function",
        "function_expression",
    }
)


_RUST_DEF_NODES = frozenset(
    {
        "function_item",
        "struct_item",
        "enum_item",
        "union_item",
        "trait_item",
        "impl_item",
        "mod_item",
        "const_item",
        "static_item",
        "type_item",
        "macro_definition",
    }
)
_RUST_KINDS = {
    "function_item": "function",
    "struct_item": "struct",
    "enum_item": "enum",
    "union_item": "struct",
    "trait_item": "trait",
    "impl_item": "impl",
    "mod_item": "module",
    "const_item": "variable",
    "static_item": "variable",
    "type_item": "type",
    "macro_definition": "macro",
}


@dataclass(frozen=True)
class LanguageConfig:
    language: str
    def_nodes: frozenset[str]
    func_value_nodes: frozenset[str]
    ident_nodes: frozenset[str]
    import_nodes: frozenset[str]
    params_fields: tuple[str, ...] = ("parameters", "formal_parameters")
    grammar: str = ""  # dotted "module:function" producing a tree-sitter Language capsule
    name_fields: tuple[str, ...] = ("name",)
    kind_by_node: dict[str, str] = field(default_factory=dict)


_CONFIGS: dict[str, LanguageConfig] = {
    "javascript": LanguageConfig(
        language="javascript",
        def_nodes=_JS_DEF_NODES,
        func_value_nodes=_JS_FUNC_VALUE_NODES,
        ident_nodes=_JS_IDENT_NODES,
        import_nodes=frozenset({"import_statement"}),
        grammar="tree_sitter_javascript:language",
    ),
    "typescript": LanguageConfig(
        language="typescript",
        def_nodes=_JS_DEF_NODES | {"interface_declaration", "type_alias_declaration", "enum_declaration"},
        func_value_nodes=_JS_FUNC_VALUE_NODES,
        ident_nodes=_JS_IDENT_NODES,
        import_nodes=frozenset({"import_statement"}),
        grammar="tree_sitter_typescript:language_typescript",
    ),
    "tsx": LanguageConfig(
        language="tsx",
        def_nodes=_JS_DEF_NODES | {"interface_declaration", "type_alias_declaration", "enum_declaration"},
        func_value_nodes=_JS_FUNC_VALUE_NODES,
        ident_nodes=_JS_IDENT_NODES,
        import_nodes=frozenset({"import_statement"}),
        grammar="tree_sitter_typescript:language_tsx",
    ),
    "rust": LanguageConfig(
        language="rust",
        def_nodes=_RUST_DEF_NODES,
        func_value_nodes=frozenset({"closure_expression"}),
        ident_nodes=frozenset({"identifier", "type_identifier", "field_identifier"}),
        import_nodes=frozenset({"use_declaration"}),
        params_fields=("parameters",),
        grammar="tree_sitter_rust:language",
        # `impl_item` has no `name`; its `type` field carries the type being implemented,
        # so `impl GlobalState` indexes under "GlobalState" rather than "<anonymous>".
        name_fields=("name", "type"),
        kind_by_node=_RUST_KINDS,
    ),
}


@lru_cache(maxsize=8)
def _parser(config_key: str):
    import importlib

    from tree_sitter import Language, Parser

    module_name, func_name = _CONFIGS[config_key].grammar.split(":")
    module = importlib.import_module(module_name)
    return Parser(Language(getattr(module, func_name)()))


class TreeSitterProvider:
    """Symbol provider for one tree-sitter language config."""

    def __init__(self, config_key: str) -> None:
        self._key = config_key
        self.language = _CONFIGS[config_key].language

    def available(self) -> bool:
        try:
            _parser(self._key)
            return True
        except Exception:
            return False

    def parse(self, source: str, text: str) -> FileSymbols:
        config = _CONFIGS[self._key]
        try:
            tree = _parser(self._key).parse(text.encode("utf-8"))
        except Exception:
            return FileSymbols(source=source, language=self.language, definitions=(), imports=())

        byte_char = _byte_to_char_map(text)
        definitions: list[SymbolDef] = []
        imports: list[SymbolDef] = []
        self._collect(tree.root_node, False, source, text, byte_char, config, definitions, imports)

        return FileSymbols(
            source=source,
            language=self.language,
            definitions=tuple(definitions),
            imports=tuple(imports),
        )

    def _collect(self, node, in_func, source, text, byte_char, config, definitions, imports) -> None:
        node_type = node.type
        if node_type in config.import_nodes:
            imports.append(_import_symbol(node, source, text, byte_char, config))
            return
        if node_type in config.def_nodes:
            definitions.append(_def_symbol(node, source, text, byte_char, config))
            for child in node.children:
                self._collect(child, True, source, text, byte_char, config, definitions, imports)
            return
        if node_type == "variable_declarator":
            value = node.child_by_field_name("value")
            is_func = value is not None and value.type in config.func_value_nodes
            if is_func or not in_func:  # skip locals inside function bodies
                definitions.append(
                    _def_symbol(node, source, text, byte_char, config, force_kind=None if is_func else "variable")
                )
            if is_func:
                for child in node.children:
                    self._collect(child, True, source, text, byte_char, config, definitions, imports)
                return
        child_in_func = in_func or node_type in _FUNC_SCOPE
        for child in node.children:
            self._collect(child, child_in_func, source, text, byte_char, config, definitions, imports)


def _def_symbol(node, source, text, byte_char, config: LanguageConfig, force_kind: str | None = None) -> SymbolDef:
    name_node = next(
        (n for n in (node.child_by_field_name(f) for f in config.name_fields) if n is not None),
        None,
    )
    name = _node_text(name_node, text, byte_char) if name_node is not None else ""

    defines: set[str] = {name} if name else set()
    for params_field in config.params_fields:
        params = node.child_by_field_name(params_field)
        if params is not None:
            defines.update(_ident_texts(params, text, byte_char, config))

    refs = _ident_texts(node, text, byte_char, config) - defines
    kind = (
        force_kind
        or config.kind_by_node.get(node.type)
        or ("class" if "class" in node.type or "interface" in node.type else "function")
    )
    return _build(node, name or "<anonymous>", kind, source, text, byte_char, defines, refs)


def _import_symbol(node, source, text, byte_char, config: LanguageConfig) -> SymbolDef:
    names = _ident_texts(node, text, byte_char, config)
    return _build(
        node,
        sorted(names)[0] if names else "import",
        "import",
        source,
        text,
        byte_char,
        defines=set(names),
        refs=set(),
    )


def _build(node, name, kind, source, text, byte_char, defines, refs) -> SymbolDef:
    char_start = byte_char[node.start_byte]
    char_end = byte_char[node.end_byte]
    return SymbolDef(
        name=name,
        kind=kind,
        source=source,
        line_start=node.start_point[0] + 1,
        line_end=node.end_point[0] + 1,
        char_start=char_start,
        char_end=char_end,
        defines=frozenset(defines),
        refs=frozenset(refs),
        text=text[char_start:char_end],
    )


def _ident_texts(node, text, byte_char, config: LanguageConfig) -> set[str]:
    found: set[str] = set()
    for descendant in _walk(node):
        if descendant.type in config.ident_nodes and descendant.child_count == 0:
            found.add(_node_text(descendant, text, byte_char))
    return found


def _node_text(node, text: str, byte_char: list[int]) -> str:
    return text[byte_char[node.start_byte] : byte_char[node.end_byte]]


def _walk(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _byte_to_char_map(text: str) -> list[int]:
    mapping: list[int] = []
    char_index = 0
    for char in text:
        mapping.extend([char_index] * len(char.encode("utf-8")))
        char_index += 1
    mapping.append(char_index)
    return mapping
