"""Compat shim: `python eval/run_eval.py` -> `pasr_eval.run:main` (a.k.a. `pasr-bench run`)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pasr_eval.run import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
