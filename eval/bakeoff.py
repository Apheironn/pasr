"""Compat shim: `python eval/bakeoff.py` -> `pasr_eval.bakeoff:main` (a.k.a. `pasr-bench bakeoff`)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pasr_eval.bakeoff import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
