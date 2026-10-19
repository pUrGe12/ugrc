"""Do the whole-PDF answers' page citations hold? (Single-paper sets only: p2, p3.)

    python experiments/whole-pdf/cite_check.py [answers-dir ...]      # default: answers answers-haiku

For every line of an answer that names a page ("page 6", "p. 3", "pp. 9–10"), each number on that line
that is printed somewhere in the paper is looked up on the cited page(s). Lenient: all pages named on the
line count for every number on it. A ugrc answer passes this by construction: each number is a pointer.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TEXT = {"p2": ROOT / "runs/paper2", "p3": ROOT / "runs/paper3"}
PAGE = re.compile(r"\b(?:pages?|pp?\.)\s*(\d+)(?:\s*(?:[–-]|and|,)\s*(\d+))?", re.I)
NUM = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*")
SKIP = re.compile(r"(?:pages?|pp?\.|Fig(?:ure)?s?\.?|Tables?|Sections?|Eqs?\.?|Refs?\.?|\[|S)\s*$", re.I)


def pages_text(root):
    con = duckdb.connect(str(Path(root) / "atoms.duckdb"), read_only=True)
    by = defaultdict(list)
    for page, text in con.execute("SELECT page, text FROM atoms WHERE text IS NOT NULL AND page IS NOT NULL").fetchall():
        by[page].append(text)
    return {p: re.sub(r"\s+", " ", " ".join(t)) for p, t in by.items()}


def check(answers):
    texts = {s: pages_text(r) for s, r in TEXT.items()}
    tally, misses = Counter(), []
    for f in sorted((HERE / answers).glob("p[23]-*.json")):
        r = json.loads(f.read_text())
        pages = texts[r["set"]]
        whole = " ".join(pages.values())
        for line in r["answer"].splitlines():
            cited = set()
            for m in PAGE.finditer(line):
                a, b = int(m.group(1)), int(m.group(2) or m.group(1))
                cited |= set(range(min(a, b), max(a, b) + 1)) if b - a < 6 else {a, b}
            if not cited:
                continue
            for m in NUM.finditer(line):
                if SKIP.search(line[max(0, m.start() - 8):m.start()]):
                    continue
                n = m.group().rstrip(".,")
                forms = {n, n.replace(",", "")}
                if not any(x in whole for x in forms) or len(n.replace(",", "").replace(".", "")) < 2:
                    continue                          # computed, or too short to locate
                if not cited & set(pages):
                    tally["page not in the PDF"] += 1
                    misses.append((f.stem, n, sorted(cited), "no such page"))
                elif any(x in pages[p] for p in cited & set(pages) for x in forms):
                    tally["on the cited page"] += 1
                else:
                    tally["not on the cited page"] += 1
                    found = sorted(p for p, t in pages.items() if any(x in t for x in forms))
                    misses.append((f.stem, n, sorted(cited), f"printed on {found}"))
    return tally, misses


if __name__ == "__main__":
    for d in sys.argv[1:] or ["answers", "answers-haiku"]:
        tally, misses = check(d)
        total = sum(tally.values())
        print(f"{d}: {total} cited numbers: " + ", ".join(f"{k} {v}" for k, v in tally.items()))
        for m in misses:
            print("   ", *m)
