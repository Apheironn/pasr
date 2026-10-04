"""Why are split-reader answers materially wrong? Classify each error by what the model saw.

For every materially_incorrect answer in the four powered studies, take the source lines the
blind reviewer cited as proof of the error, find the smallest enclosing definition, and ask
whether the trajectory delivered (a) none of those lines, (b) some of the cited lines or only
part of the enclosing definition, or (c) the whole enclosing definition.
"""

import ast
import collections
import importlib.util
import json
import re
from pathlib import Path

R = Path(r"D:\kodlama\pasr\eval\agent_bench\results")
STUDIES = ("powered_split_20261001", "cheap_search_20261002", "split_cap4_20261002", "stop_message_20261002")
LBL = re.compile(r"\[([^\]\n:]+):(\d+)(?:-(\d+))?\]")
CITE = re.compile(r"([\w./-]+\.py)(?::|`?\s*(?:lines?)?\s*)(\d+)(?:\s*[-–]\s*(\d+))?")
CITE_MORE = re.compile(r"[,;]\s*(\d+)(?:\s*[-–]\s*(\d+))?")


def reviews_for(study):
    spec = importlib.util.spec_from_file_location("an_" + study, R / study / "analyze.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.ROOT = R / study
    by_row, problems = m.validated_reviews()
    assert not problems, (study, problems[:3])
    return by_row


def delivered(row):
    seen = collections.defaultdict(set)
    for o in row["tool_outputs"]:
        name, text = o["name"], o["delivered"]
        if name in ("search_code", "read_code", "select_context"):
            for m in LBL.finditer(text):
                a = int(m.group(2))
                seen[m.group(1)].update(range(a, int(m.group(3) or a) + 1))
        elif name == "read_file":
            p = str(o["input"].get("path", "")).replace(chr(92), "/").lstrip("./")
            for line in text.splitlines():
                m = re.match(r"(\d+): ", line)
                if m:
                    seen[p].add(int(m.group(1)))
        elif name == "grep":
            for line in text.splitlines():
                m = re.match(r"([^:]+):(\d+):", line)
                if m:
                    seen[m.group(1)].add(int(m.group(2)))
        elif name == "find_evidence":
            try:
                for h in json.loads(text).get("hits", []):
                    src, _, ln = h["provenance"].rpartition(":")
                    if ln.isdigit():
                        seen[src].add(int(ln))
            except Exception:
                pass
    return seen


_files = {}


def corpus_files(root):
    if root not in _files:
        _files[root] = [p.relative_to(root).as_posix() for p in root.rglob("*.py")]
    return _files[root]


PREFER = set()


def resolve(root, cited):
    cited = cited.lstrip("./")
    hits = [p for p in corpus_files(root) if p == cited or p.endswith("/" + cited)]
    if len(hits) > 1:
        hits = [p for p in hits if p in PREFER] or [
            p for p in hits if not p.startswith(("tests/", "testing/", "docs/"))
        ]
    return hits[0] if len(hits) == 1 else None


_defs = {}


def enclosing(root, path, line):
    key = (root, path)
    if key not in _defs:
        try:
            tree = ast.parse((root / path).read_text(encoding="utf-8"))
            _defs[key] = [
                (n.lineno, n.end_lineno)
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
        except Exception:
            _defs[key] = []
    spans = [s for s in _defs[key] if s[0] <= line <= s[1]]
    return min(spans, key=lambda s: s[1] - s[0]) if spans else None


def cited_ranges(text, root):
    out = []
    for m in CITE.finditer(text):
        path = resolve(root, m.group(1))
        if not path:
            continue
        a = int(m.group(2))
        out.append((path, a, int(m.group(3) or a)))
        tail = text[m.end() : m.end() + 40]
        for extra in CITE_MORE.finditer(tail):
            if extra.start() > 3:
                break
            b = int(extra.group(1))
            out.append((path, b, int(extra.group(2) or b)))
    return out


def classify(row, review, root):
    seen = delivered(row)
    text = " ".join(e.get("reason", "") for e in review.get("material_errors", []))
    ranges = cited_ranges(text, root)
    mechanism = [r for r in ranges if not r[0].startswith(("tests/", "testing/", "docs/"))]
    ranges = mechanism or ranges
    if not ranges:
        return "no_citation", []
    detail = []
    any_line = all_lines = whole_def = True
    for path, a, b in ranges:
        lines = set(range(a, b + 1))
        got = seen.get(path, set())
        d = enclosing(root, path, a)
        def_lines = set(range(d[0], d[1] + 1)) if d else lines
        detail.append(
            {
                "path": path,
                "cited": f"{a}-{b}",
                "cited_delivered": f"{len(lines & got)}/{len(lines)}",
                "def": f"{d[0]}-{d[1]}" if d else None,
                "def_delivered": f"{len(def_lines & got)}/{len(def_lines)}",
            }
        )
        any_line &= bool(lines & got)
        all_lines &= lines <= got
        whole_def &= def_lines <= got
    if not any_line:
        return "never_delivered", detail
    if not all_lines or not whole_def:
        return "fragment", detail
    return "delivered_misread", detail


def main():
    tally = collections.defaultdict(collections.Counter)
    examples = []
    for study in STUDIES:
        rows = json.loads((R / study / "results.json").read_text(encoding="utf-8"))["rows"]
        reviews = reviews_for(study)
        cases = {c["id"]: c for c in json.loads((R / study / "cases.json").read_text(encoding="utf-8"))["cases"]}
        for i, row in enumerate(rows):
            review = reviews.get(i)
            if not review or review["verdict"] != "materially_incorrect":
                continue
            root = R / study / "corpora" / row["corpus"]
            PREFER.clear()
            PREFER.update(cases[row["case_id"]]["source_sha256"])
            kind, detail = classify(row, review, root)
            tally[row["profile"]][kind] += 1
            if row["profile"] == "split":
                examples.append((study[:12], row["case_id"][:46], row["tool_calls"], kind, detail))
    for profile in ("split", "native", "current"):
        print(profile, dict(tally[profile]), "total", sum(tally[profile].values()))
    print()
    for e in examples:
        print(e[0], e[1], "calls", e[2], "->", e[3])
        for d in e[4]:
            print("      ", d)


if __name__ == "__main__":
    main()
