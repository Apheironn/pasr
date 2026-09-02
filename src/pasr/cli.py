"""``pasr`` CLI — run PASR without an agent.

pasr explain "<query>" [globs...]   show the selection receipt
pasr trace <symbol> [globs...]      show a dependency closure
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pasr import __version__
from pasr.receipt import receipt_bytes, render_markdown, write_receipt
from pasr.schema import validate_select_context_request, validate_trace_dependencies_request
from pasr.select import build_select_receipt
from pasr.trace import trace_dependencies


def _explain(args: argparse.Namespace) -> int:
    request = validate_select_context_request(
        {
            "query": args.query,
            "include": args.paths or ["."],
            "budget_tokens": args.budget,
            "prefix_tokens": args.prefix_tokens,
            "tail_tokens": args.tail_tokens,
            "recall_strategy": args.recall_strategy,
            "block_size": args.block_size,
        },
        workspace_root=args.workspace,
    )
    receipt = build_select_receipt(request)
    if not args.no_write:
        write_receipt(request.workspace_root, receipt)
    print(receipt_bytes(receipt).rstrip() if args.json else render_markdown(receipt))
    return 0


def _trace(args: argparse.Namespace) -> int:
    request = validate_trace_dependencies_request(
        {"symbol": args.symbol, "include": args.paths or ["."], "max_depth": args.max_depth},
        workspace_root=args.workspace,
    )
    texts = {
        meta["relative_path"]: path.read_text(encoding="utf-8", errors="replace")
        for path, meta in zip(request.files, request.file_metadata, strict=True)
    }
    result = trace_dependencies(args.symbol, texts, max_depth=request.max_depth).to_dict()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        if not result["found"]:
            print(f"symbol '{args.symbol}' is not defined in the scanned files")
            return 1
        pct = round(result["token_reduction"] * 100)
        print(f"# {args.symbol} — {len(result['spans'])} definitions, {pct}% fewer tokens than the index\n")
        for span in result["spans"]:
            print(f"- {span['provenance']}  ({span['kind']} {span['name']})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pasr", description="PASR context broker — CLI")
    parser.add_argument("--version", action="version", version=f"pasr {__version__}")
    parser.add_argument("--workspace", type=Path, default=Path.cwd(), help="Workspace root (default: cwd).")
    sub = parser.add_subparsers(dest="command", required=True)

    explain = sub.add_parser("explain", help="Run select_context and print the receipt.")
    explain.add_argument("query")
    explain.add_argument("paths", nargs="*", help="Globs / directories (default: '.').")
    explain.add_argument("--budget", type=int, default=3000, dest="budget")
    explain.add_argument("--prefix-tokens", type=int, default=128, dest="prefix_tokens")
    explain.add_argument("--tail-tokens", type=int, default=128, dest="tail_tokens")
    explain.add_argument("--recall-strategy", default="coverage_aware", dest="recall_strategy")
    explain.add_argument("--block-size", type=int, default=400, dest="block_size")
    explain.add_argument("--json", action="store_true", help="Emit the receipt as JSON.")
    explain.add_argument("--no-write", action="store_true", help="Do not write the receipt file.")
    explain.set_defaults(func=_explain)

    trace = sub.add_parser("trace", help="Print a symbol's dependency closure.")
    trace.add_argument("symbol")
    trace.add_argument("paths", nargs="*", help="Globs / directories (default: '.').")
    trace.add_argument("--max-depth", type=int, default=4, dest="max_depth")
    trace.add_argument("--json", action="store_true", help="Emit the closure as JSON.")
    trace.set_defaults(func=_trace)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
