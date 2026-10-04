"""Tool schemas, in the neutral JSON-Schema shape both backends accept."""

from __future__ import annotations

from tools_pasr import list_pasr_tools

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

# PASR augments, rather than replaces, the baseline tools.
PASR = [*BASELINE, *list_pasr_tools()]


def anthropic(tools: list[dict]) -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]


def openai(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": t} for t in tools]
