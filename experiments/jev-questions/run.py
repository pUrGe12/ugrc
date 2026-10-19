"""Build one clause base with one question set and one judge.

    python run.py v5|v6 PAPER_DIR OUT_DIR [--url http://127.0.0.1:8771/v1/systemone] [--model NAME]

Without --url the judge is TypeSafe's Jev (JEV_API_KEY); with it, any self-hosted judge that speaks the
same API (/v1/systemone with choice, noul and score questions). v5 is the question set as it was before this work (clauses_v5.py), v6 the new design as frozen before
the held-out paper was run (clauses_v6.py), v7 ugrc/clauses.py (v6 plus the fixes made after it).
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent))

from ugrc import jev  # noqa: E402


def module(version):
    """v5 and v6 are frozen copies (frozen.sha256); v7 is ugrc/clauses.py as it is now."""
    if version == "v7":
        from ugrc import clauses
        return clauses
    name = f"clauses_{version}"
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                      # dataclasses look their module up here
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("version", choices=["v5", "v6", "v7"])
    ap.add_argument("paper")
    ap.add_argument("out")
    ap.add_argument("--url")
    ap.add_argument("--model", default=jev.MODEL)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    if a.url:
        jev.URL = a.url
        jev.TIMEOUT_S = 1800                     # a local CPU judge answers a request in seconds to minutes
        os.environ.setdefault("JEV_API_KEY", "local")
    t = time.time()
    module(a.version).build(a.paper, a.out, model=a.model, workers=a.workers,
                            log=lambda m: print(m, file=sys.stderr, flush=True))
    print(f"{a.version} {a.paper} -> {a.out}: {time.time() - t:.0f}s", file=sys.stderr)
