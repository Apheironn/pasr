"""``pasr`` CLI — run PASR without an agent.

pasr find "<query>" [globs...]           rank files by path/filename match
pasr symbols "<query>" [globs...]        where matching symbols are defined (file:line)
pasr explain "<query>" [globs...]        show the selection receipt
pasr trace <symbol> [globs...]           a dependency closure (--callers to reverse it)
pasr pack <name> "<query>" [globs...]    save a Context Pack
pasr review [--staged|--range|--diff]    diff-aware context: touched defs + their callers
pasr context --issue <text> [globs...]   headless context slice for CI / agents
pasr report [--since] [--price-per-mtok] summarise .pasr/ledger.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from pasr import __version__
from pasr.find_files import DEFAULT_TOP_K, find_files
from pasr.ledger import append_ledger, entry_from_receipt, read_ledger, render_report, summarize
from pasr.receipt import receipt_bytes, render_markdown, write_receipt
from pasr.schema import validate_select_context_request, validate_trace_dependencies_request
from pasr.select import build_select_receipt, run_select_context, save_pack
from pasr.symbol_search import DEFAULT_TOP_K as SYMBOL_TOP_K
from pasr.symbol_search import find_symbols
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


def _find(args: argparse.Namespace) -> int:
    try:
        result = find_files(args.workspace, query=args.query, include=args.paths or None, top_k=args.top_k)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    print(f"# {result['total_candidates']} candidate file(s), top {len(result['matches'])}\n")
    for match in result["matches"]:
        score = f"{match['match_score']:.2f}" if match["match_score"] is not None else "-"
        keywords = ", ".join(match["matched_keywords"]) or "-"
        print(f"{score}  {match['path']}  ({keywords})")
    return 0


def _symbols(args: argparse.Namespace) -> int:
    try:
        result = find_symbols(
            args.workspace, query=args.query, include=args.paths or None, kinds=args.kinds or None, top_k=args.top_k
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    print(
        f"# {result['symbol_match_count']} definition(s) matched across "
        f"{result['files_indexed']} indexed file(s), top {len(result['matches'])}\n"
    )
    for match in result["matches"]:
        print(f"{match['match_score']:.2f}  {match['kind']:<9} {match['name']}  {match['provenance']}")
    if not result["matches"] and result["unparsed_extensions"]:
        print(f"\nno symbol provider for: {', '.join(result['unparsed_extensions'][:10])}", file=sys.stderr)
    return 0


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
            "map_tokens": args.map_tokens,
            "trace": args.trace,
            "outline": args.outline,
        },
        workspace_root=args.workspace,
    )
    started = time.perf_counter()
    receipt = build_select_receipt(request)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if not args.no_write:
        write_receipt(request.workspace_root, receipt)
        if not args.no_ledger:
            append_ledger(request.workspace_root, entry_from_receipt(receipt, source="cli"))
    print(receipt_bytes(receipt).rstrip() if args.json else render_markdown(receipt))
    if not args.json:
        # timing is not part of the receipt (that stays wall-clock-free and byte-stable);
        # it goes to stderr so --json and receipt files are unaffected.
        print(f"\nselected in {elapsed_ms:.0f} ms  (offline, deterministic)", file=sys.stderr)
    return 0


def _review(args: argparse.Namespace) -> int:
    from pasr.file_discovery import discover_workspace_files
    from pasr.review import parse_unified_diff, read_git_diff, render_review, review_context

    if args.diff:
        diff_text = Path(args.diff).read_text(encoding="utf-8", errors="replace")
    else:
        try:
            diff_text = read_git_diff(Path(args.workspace), staged=args.staged, ref_range=args.ref_range)
        except RuntimeError as exc:
            print(f"error: {exc}\nhint: pass --diff <file> with a unified diff", file=sys.stderr)
            return 2

    changes = parse_unified_diff(diff_text)
    if not changes:
        print("no changed files with hunks in the diff")
        return 0

    records = discover_workspace_files(Path(args.workspace).resolve(), include_patterns=args.paths or ["."])
    texts = {r.relative_path: r.path.read_text(encoding="utf-8", errors="replace") for r in records}
    result = review_context(changes, texts, budget_tokens=args.budget, callers_depth=args.callers_depth)

    if args.context_file:
        Path(args.context_file).write_text(result["context"], encoding="utf-8", newline="\n")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(render_review(result), end="")
    return 0


def _report(args: argparse.Namespace) -> int:
    rows = read_ledger(args.workspace)
    summary = summarize(rows, since=args.since, price_per_mtok=args.price_per_mtok)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(render_report(summary), end="")
    return 0


def _trace(args: argparse.Namespace) -> int:
    direction = "callers" if args.callers else "dependencies"
    request = validate_trace_dependencies_request(
        {
            "symbol": args.symbol,
            "include": args.paths or ["."],
            "max_depth": args.max_depth,
            "direction": direction,
        },
        workspace_root=args.workspace,
    )
    texts = {
        meta["relative_path"]: path.read_text(encoding="utf-8", errors="replace")
        for path, meta in zip(request.files, request.file_metadata, strict=True)
    }
    result = trace_dependencies(args.symbol, texts, max_depth=request.max_depth, direction=request.direction).to_dict()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        if not result["found"]:
            print(f"symbol '{args.symbol}' is not defined in the scanned files")
            return 1
        pct = result["token_reduction"] * 100
        pct_str = ">99" if pct >= 99.5 else str(round(pct))
        noun = "callers" if direction == "callers" else "definitions"
        print(f"# {args.symbol} — {len(result['spans'])} {noun}, {pct_str}% fewer tokens than the index\n")
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
            "map_tokens": args.map_tokens,
            "trace": args.trace,
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
            "map_tokens": args.map_tokens,
            "trace": args.trace,
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

    find = sub.add_parser("find", help="Rank workspace files by path/filename match for a query.")
    find.add_argument("query")
    find.add_argument("paths", nargs="*", help="Globs / directories (default: whole workspace).")
    find.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, dest="top_k")
    find.add_argument("--json", action="store_true", help="Emit matches as JSON.")
    find.set_defaults(func=_find)

    symbols = sub.add_parser("symbols", help="Find where matching symbols are defined (file:line).")
    symbols.add_argument("query")
    symbols.add_argument("paths", nargs="*", help="Globs / directories (default: whole workspace).")
    symbols.add_argument("--kind", action="append", dest="kinds", help="Filter by kind (repeatable).")
    symbols.add_argument("--top-k", type=int, default=SYMBOL_TOP_K, dest="top_k")
    symbols.add_argument("--json", action="store_true", help="Emit matches as JSON.")
    symbols.set_defaults(func=_symbols)

    explain = sub.add_parser("explain", help="Run select_context and print the receipt.")
    explain.add_argument("query")
    explain.add_argument("paths", nargs="*", help="Globs / directories (default: '.').")
    explain.add_argument("--budget", type=int, default=3000, dest="budget")
    explain.add_argument("--prefix-tokens", type=int, default=128, dest="prefix_tokens")
    explain.add_argument("--tail-tokens", type=int, default=128, dest="tail_tokens")
    explain.add_argument("--recall-strategy", default="coverage_aware", dest="recall_strategy")
    explain.add_argument("--block-size", type=int, default=400, dest="block_size")
    explain.add_argument("--semantic", default="", choices=("", "none", "hashing", "minilm"))
    explain.add_argument(
        "--map-tokens",
        type=int,
        default=0,
        dest="map_tokens",
        help="Prepend a query-ranked symbol index of this many tokens (carved from --budget).",
    )
    explain.add_argument("--trace", default="", help="Also fold this symbol's dependency closure into the slice.")
    explain.add_argument(
        "--outline",
        action="store_true",
        help="Definitions-only index for the files (no bodies) - locate cheaply, then read.",
    )
    explain.add_argument("--json", action="store_true", help="Emit the receipt as JSON.")
    explain.add_argument("--no-write", action="store_true", help="Do not write the receipt file.")
    explain.add_argument("--no-ledger", action="store_true", help="Do not append to .pasr/ledger.jsonl.")
    explain.set_defaults(func=_explain)

    review = sub.add_parser("review", help="Diff-aware context: touched definitions + the callers they affect.")
    review.add_argument("paths", nargs="*", help="Globs / directories to scan for callers (default: '.').")
    review.add_argument("--diff", default="", help="Read a unified diff from this file instead of running git.")
    review.add_argument("--staged", action="store_true", help="Review the staged diff (git diff --cached).")
    review.add_argument("--range", default="", dest="ref_range", help="A git range, e.g. main..HEAD.")
    review.add_argument("--budget", type=int, default=6000, dest="budget")
    review.add_argument("--callers-depth", type=int, default=1, dest="callers_depth")
    review.add_argument("--context-file", default="", dest="context_file", help="Write the raw review context here.")
    review.add_argument("--json", action="store_true", help="Emit the review as JSON.")
    review.set_defaults(func=_review)

    report = sub.add_parser("report", help="Summarise .pasr/ledger.jsonl: tokens and round trips saved.")
    report.add_argument("--since", default="", help="Only rows on/after this ISO date prefix, e.g. 2026-09-01.")
    report.add_argument(
        "--price-per-mtok",
        type=float,
        default=0.0,
        dest="price_per_mtok",
        help="USD per million input tokens; if set, show an estimated cost avoided.",
    )
    report.add_argument("--json", action="store_true", help="Emit the summary as JSON.")
    report.set_defaults(func=_report)

    trace = sub.add_parser("trace", help="Print a symbol's dependency closure.")
    trace.add_argument("symbol")
    trace.add_argument("paths", nargs="*", help="Globs / directories (default: '.').")
    trace.add_argument("--max-depth", type=int, default=4, dest="max_depth")
    trace.add_argument(
        "--callers",
        action="store_true",
        help="Reverse the edges: trace what transitively references the symbol (impact analysis).",
    )
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
    pack.add_argument(
        "--map-tokens",
        type=int,
        default=0,
        dest="map_tokens",
        help="Prepend a query-ranked symbol index of this many tokens (carved from --budget).",
    )
    pack.add_argument("--trace", default="", help="Also fold this symbol's dependency closure into the slice.")
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
    context.add_argument(
        "--map-tokens",
        type=int,
        default=0,
        dest="map_tokens",
        help="Prepend a query-ranked symbol index of this many tokens (carved from --budget).",
    )
    context.add_argument("--trace", default="", help="Also fold this symbol's dependency closure into the slice.")
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
