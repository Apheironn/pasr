"""``pasr`` CLI — run PASR without an agent.

pasr explain "<query>" [globs...]        show the selection receipt
pasr trace <symbol> [globs...]           show a dependency closure
pasr pack <name> "<query>" [globs...]    save a Context Pack
pasr context --issue <text> [globs...]   headless context slice for CI / agents
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pasr import __version__
from pasr.receipt import receipt_bytes, render_markdown, write_receipt
from pasr.schema import validate_select_context_request, validate_trace_dependencies_request
from pasr.select import build_select_receipt, run_select_context, save_pack
from pasr.trace import trace_dependencies


def context_metrics(result: dict) -> dict:
    """Compact machine-readable metrics for a headless selection."""
    files = result.get("diagnostics", {}).get("files", [])
    return {
        "route": result["route"],
        "query_class": result.get("query_class"),
        "confidence": result.get("confidence"),
        "tokens_in": result["total_input_tokens"],
        "tokens_out": result["token_count"],
        "token_reduction": result["token_reduction"],
        "files_scanned": len(files),
        "span_count": len(result["spans"]),
        # estimate: one PASR call replaces the agent opening each scanned file
        "round_trips_saved": max(0, len(files) - 1),
    }


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
            "semantic": args.semantic,
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


def _pack(args: argparse.Namespace) -> int:
    request = validate_select_context_request(
        {
            "query": args.query,
            "include": args.paths or ["."],
            "budget_tokens": args.budget,
            "prefix_tokens": args.prefix_tokens,
            "tail_tokens": args.tail_tokens,
            "recall_strategy": args.recall_strategy,
            "block_size": args.block_size,
            "semantic": args.semantic,
        },
        workspace_root=args.workspace,
    )
    path, pack = save_pack(args.name, request)
    print(
        f"wrote {path.relative_to(args.workspace) if path.is_relative_to(args.workspace) else path}  "
        f"({pack['token_count']} tokens, {len(pack['spans'])} spans, {pack['content_hash'][:12]})"
    )
    return 0


def _context(args: argparse.Namespace) -> int:
    if args.issue_file:
        issue = Path(args.issue_file).read_text(encoding="utf-8", errors="replace")
    elif args.issue:
        issue = args.issue
    else:
        print("error: provide --issue or --issue-file", file=sys.stderr)
        return 2

    request = validate_select_context_request(
        {
            "query": issue,
            "include": args.paths or ["."],
            "budget_tokens": args.budget,
            "prefix_tokens": args.prefix_tokens,
            "tail_tokens": args.tail_tokens,
            "recall_strategy": args.recall_strategy,
            "block_size": args.block_size,
            "semantic": args.semantic,
        },
        workspace_root=args.workspace,
    )
    # CI mode: don't litter .pasr/ — the context / metrics files are the outputs.
    result = run_select_context(request, write_receipt_file=args.receipt)
    metrics = context_metrics(result)

    if args.context_file:
        Path(args.context_file).write_text(result["context"], encoding="utf-8", newline="\n")
    if args.metrics_file:
        Path(args.metrics_file).write_text(
            json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )

    if args.format == "text":
        print(result["context"])
    else:
        print(json.dumps({"result": result, "metrics": metrics}, indent=2, sort_keys=True, ensure_ascii=False))
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
    explain.add_argument("--semantic", default="", choices=("", "none", "hashing", "minilm"))
    explain.add_argument("--json", action="store_true", help="Emit the receipt as JSON.")
    explain.add_argument("--no-write", action="store_true", help="Do not write the receipt file.")
    explain.set_defaults(func=_explain)

    trace = sub.add_parser("trace", help="Print a symbol's dependency closure.")
    trace.add_argument("symbol")
    trace.add_argument("paths", nargs="*", help="Globs / directories (default: '.').")
    trace.add_argument("--max-depth", type=int, default=4, dest="max_depth")
    trace.add_argument("--json", action="store_true", help="Emit the closure as JSON.")
    trace.set_defaults(func=_trace)

    pack = sub.add_parser("pack", help="Save a selection as a Context Pack under .pasr/packs/.")
    pack.add_argument("name")
    pack.add_argument("query")
    pack.add_argument("paths", nargs="*", help="Globs / directories (default: '.').")
    pack.add_argument("--budget", type=int, default=3000, dest="budget")
    pack.add_argument("--prefix-tokens", type=int, default=128, dest="prefix_tokens")
    pack.add_argument("--tail-tokens", type=int, default=128, dest="tail_tokens")
    pack.add_argument("--recall-strategy", default="coverage_aware", dest="recall_strategy")
    pack.add_argument("--block-size", type=int, default=400, dest="block_size")
    pack.add_argument("--semantic", default="", choices=("", "none", "hashing", "minilm"))
    pack.set_defaults(func=_pack)

    context = sub.add_parser("context", help="Headless context slice for CI / autonomous agents.")
    context.add_argument("paths", nargs="*", help="Globs / directories (default: '.').")
    context.add_argument("--issue", default="", help="Issue / task text to select context for.")
    context.add_argument("--issue-file", default="", dest="issue_file", help="File holding the issue text.")
    context.add_argument("--budget", type=int, default=6000, dest="budget")
    context.add_argument("--prefix-tokens", type=int, default=128, dest="prefix_tokens")
    context.add_argument("--tail-tokens", type=int, default=128, dest="tail_tokens")
    context.add_argument("--recall-strategy", default="coverage_aware", dest="recall_strategy")
    context.add_argument("--block-size", type=int, default=400, dest="block_size")
    context.add_argument("--semantic", default="", choices=("", "none", "hashing", "minilm"))
    context.add_argument("--format", choices=("json", "text"), default="json", dest="format")
    context.add_argument("--context-file", default="", dest="context_file", help="Write the raw context slice here.")
    context.add_argument("--metrics-file", default="", dest="metrics_file", help="Write JSON metrics here.")
    context.add_argument("--receipt", action="store_true", help="Also write a .pasr/receipts/ audit record.")
    context.set_defaults(func=_context)

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
