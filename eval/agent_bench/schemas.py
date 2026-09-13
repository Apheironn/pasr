"""Tool schemas, in the neutral JSON-Schema shape both backends accept."""

from __future__ import annotations

BASELINE = [
    {
        "name": "grep",
        "description": (
            "Search file CONTENTS for a regex pattern (case-insensitive). Returns matching "
            "'path:line:text' rows. Does not search filenames."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "description": "file or directory to search under, default '.'"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a slice of one file's lines (default up to 300 lines from start_line).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
            "required": ["path"],
        },
    },
]

PASR = [
    {
        "name": "find_evidence",
        "description": (
            "Search the CONTENT of every file for a question and get back the lines that bear on it, "
            "each with its enclosing function and the terms it matched, ranked by how rare each term "
            "is (a word in two files outranks a word in two hundred). Use this FIRST when the question "
            "is conceptual and you do not yet know any file, path or symbol name - it is the only tool "
            "that bridges a question worded differently from the code (asking about a server going "
            "idle when the code says quiescent). No max_files limit, no bodies."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "include": {"type": "array", "items": {"type": "string"}},
                "top_k": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_files",
        "description": (
            "Rank workspace files by how many query terms appear in their own path/filename. Call this "
            "when you do not know which real file paths exist. Lexical path matching, not semantic: if "
            "your words do not appear in any path, matches come back empty - then call with query='' and "
            "a directory in include to list the real names."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "include": {"type": "array", "items": {"type": "string"}},
                "top_k": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_symbols",
        "description": (
            "Where is a symbol DEFINED? Returns file:line definitions for functions, structs, traits, "
            "enums, types and modules matching your query, across the whole workspace. Answers in one "
            "call instead of guessing which file holds it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "include": {"type": "array", "items": {"type": "string"}},
                "kinds": {"type": "array", "items": {"type": "string"}},
                "top_k": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_usages",
        "description": (
            "Where is a symbol USED? Returns every line that writes the name, across the workspace, each "
            "with the code on that line and the function/struct it sits inside - definition first, then "
            "call sites. Use it when the answer is a chain rather than one definition (what checks this, "
            "and who reports it): one call replaces walking file by file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "include": {"type": "array", "items": {"type": "string"}},
                "top_k": {"type": "integer"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "select_context",
        "description": (
            "Return a small, budgeted, provenance-tracked slice of the workspace for a query. Pass "
            "include (globs/directories) or files (explicit paths); it does not search the repo by "
            "filename itself. Spend little on early calls: whatever a call returns is re-sent to the "
            "model on every later turn, so a big first slice is the most expensive thing you can ask "
            "for. To see what a file contains, pass outline=true for a definitions-only index (a few "
            "hundred tokens), then call again for bodies where they matter. files also accepts the "
            "path:start-end provenance every other tool reports, e.g. files=[src/command.rs:190-193] - "
            "reading exactly the lines you were just pointed at costs a few dozen tokens instead of a "
            "slice of the whole file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "include": {"type": "array", "items": {"type": "string"}},
                "files": {"type": "array", "items": {"type": "string"}},
                "budget_tokens": {"type": "integer"},
                "max_files": {"type": "integer"},
                "outline": {"type": "boolean"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "expand_context",
        "description": "Re-run a prior select_context (by its id) once with a larger budget.",
        "parameters": {
            "type": "object",
            "properties": {"receipt_id": {"type": "string"}, "extra_budget": {"type": "integer"}},
            "required": ["receipt_id"],
        },
    },
    {
        "name": "trace_dependencies",
        "description": "Transitive definition closure for a symbol (or its callers). Returns bodies; expensive.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "include": {"type": "array", "items": {"type": "string"}},
                "direction": {"type": "string", "enum": ["dependencies", "callers"]},
            },
            "required": ["symbol"],
        },
    },
]

INVESTIGATE_TOOL = {
    "name": "investigate",
    "description": (
        "Answer-shaped first call for an open question about the codebase: finds the lines anywhere "
        "that bear on it, follows the code's own names one hop out, and returns a budgeted slice of "
        "the files it chose - locate and read in a single call, with file:line provenance. Start "
        "here when you do not yet know any file or symbol; use the narrower tools to follow up."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "include": {"type": "array", "items": {"type": "string"}},
            "budget_tokens": {"type": "integer"},
        },
        "required": ["question"],
    },
}

PASR_PLUS = [INVESTIGATE_TOOL, *PASR]


def anthropic(tools: list[dict]) -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]


def openai(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": t} for t in tools]
