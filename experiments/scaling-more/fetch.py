"""Fetch and select the arXiv papers (PLAN.md). Candidates: query 1 (candidates.json), then query 2 (candidates2.json),
each in arXiv's relevance order, first category cond-mat.mtrl-sci, physics.chem-ph or physics.app-ph. A candidate is
kept when its PDF downloads and has 5 to 30 pages; fetching stops once WANT are kept. Writes fetched.json."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PDFS = Path(os.path.expanduser("~/Desktop/papers-arxiv"))
WANT = int(sys.argv[1]) if len(sys.argv) > 1 else 34
CATS = ("cond-mat.mtrl-sci", "physics.chem-ph", "physics.app-ph")


def pages(f):
    out = subprocess.run(["pdfinfo", str(f)], capture_output=True, text=True).stdout
    return next((int(l.split()[-1]) for l in out.splitlines() if l.startswith("Pages:")), None)


cands = [o for name in ("candidates.json", "candidates2.json") for o in json.loads((HERE / name).read_text())
         if o["cats"][0] in CATS]
kept, rows = 0, []
for o in cands:
    if kept >= WANT:
        break
    f = PDFS / f"{o['id']}.pdf"
    n = pages(f) if f.exists() else None
    tries = 0
    while n is None and tries < 2:
        host = "export.arxiv.org" if tries == 0 else "arxiv.org"
        subprocess.run(["curl", "-sS", "-L", "--max-time", "180", "-o", str(f), f"https://{host}/pdf/{o['id']}"])
        time.sleep(4)
        n, tries = pages(f), tries + 1
    ok = n is not None and 5 <= n <= 30
    kept += ok
    rows.append(dict(o, pages=n, kept=ok))
    print(o["id"], n, "KEEP" if ok else "skip", o["title"][:70], flush=True)
(HERE / "fetched.json").write_text(json.dumps(rows, indent=1) + "\n")
print(f"{kept} kept of {len(rows)} looked at")
