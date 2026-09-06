"""``pasr-bench`` console entry: a thin dispatcher over the two orchestrators.

    pasr-bench run [args...]       # the 4-arm real-agent / keyword evaluation
    pasr-bench bakeoff [args...]   # the offline retrieval bake-off
    pasr-bench plans               # list the packaged plans

Everything after the sub-command is forwarded verbatim, so
``pasr-bench run --agent claude --resume ...`` works exactly like the old
``python eval/run_eval.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_USAGE = "usage: pasr-bench {run|bakeoff|plans} [args...]"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(_USAGE)
        print("\n  run      end-to-end evaluation -> a timestamped delivery")
        print("  bakeoff  offline retrieval bake-off (grep / repo-map / semantic / PASR)")
        print("  plans    list the plan files bundled with this package")
        return 0 if args else 2

    cmd, rest = args[0], args[1:]
    if cmd == "run":
        from pasr_eval.run import main as run_main

        return run_main(rest)
    if cmd == "bakeoff":
        from pasr_eval.bakeoff import main as bakeoff_main

        return bakeoff_main(rest)
    if cmd == "plans":
        for path in sorted((Path(__file__).parent / "plans").glob("*.json")):
            print(path)
        return 0
    print(f"unknown sub-command {cmd!r}\n{_USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
