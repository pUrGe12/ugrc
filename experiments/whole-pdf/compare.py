"""Tokens, cost and unprinted numbers: whole-PDF answers vs the ugrc answers to the same questions.

    python experiments/whole-pdf/compare.py [--answers answers-haiku] [--numbers]

--answers names the answers folder, the same in all three experiments (answers = Opus, answers-haiku = Haiku).
--numbers lists every unprinted number. A number in a whole-PDF answer is "unprinted" when its digits occur
nowhere in the paper's extracted text (lines, cells, OCR, figure facts): a computed value or a misread one;
grading decides which. ugrc answers have none by construction: every number is a quote or a traced SQL value.
"""
import json
import re
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
# $/M tokens: (input, 5-minute cache write, cache read, output). Haiku 5.5 has a second card for prompts over 100K.
PRICES = {"claude-opus-5-5": [(None, (4.0, 5.0, 0.20, 20.0))],
          "claude-haiku-5-5": [(100_000, (0.10, 0.125, 0.01, 0.50)), (None, (0.50, 0.625, 0.05, 2.50))]}
KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
UGRC = {"p2": ROOT / "experiments/claude-capability", "p3": ROOT / "experiments/claude-capability",
        "prof": ROOT / "experiments/prof-rag"}
TEXT = {"p2": ROOT / "runs/paper2", "p3": ROOT / "runs/paper3", "prof": ROOT / "runs/papers-corpus"}
NUM = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*")
SKIP = re.compile(r"(?:pages?|p\.|pp\.|Fig(?:ure)?s?\.?|Tables?|Sections?|Eqs?\.?|Refs?\.?|\[)\s*$", re.I)


def read_in(u):
    return u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)


def cost(u, model, prompt):
    """`prompt` picks the rate card: the prompt length of one call. For a multi-turn ugrc record (usage summed
    over turns) pass its largest turn's estimate; the card under 100K is assumed."""
    card = next(c for limit, c in PRICES[model] if limit is None or prompt <= limit)
    return sum(u.get(k, 0) * p for k, p in zip(KEYS, card)) / 1e6


def paper_text(root):
    con = duckdb.connect(str(Path(root) / "atoms.duckdb"), read_only=True)
    text = " ".join(t for (t,) in con.execute("SELECT text FROM atoms WHERE text IS NOT NULL").fetchall())
    return re.sub(r"\s+", " ", text)


def unprinted(answer, text):
    out = []
    for m in NUM.finditer(answer):
        if SKIP.search(answer[max(0, m.start() - 12):m.start()]):
            continue                                   # a page, figure, table or reference number
        n = m.group().rstrip(".,")
        if n not in text and n.replace(",", "") not in text:
            out.append(n)
    return out


def ugrc_record(answers, s, pid):
    f = UGRC[s] / answers / (f"{s}-{pid}.json" if s in ("p2", "p3") else f"{pid}.json")
    return json.loads(f.read_text()) if f.exists() else None


def main(answers="answers", show_numbers=False):
    rows = defaultdict(list)
    texts = {}
    for f in sorted((HERE / answers).glob("*.json")):
        r = json.loads(f.read_text())
        s = r["set"]
        if s not in texts:
            texts[s] = paper_text(TEXT[s])
        rows[s].append((r, ugrc_record(answers, s, r["probe"]), unprinted(r["answer"], texts[s])))
    print(f"{'set':5} {'n':>3} | {'whole-PDF: prompt':>18} {'cost':>7} {'unprinted':>9} | "
          f"{'ugrc: answered':>14} {'read/q':>8} {'peak≈':>7} {'turns':>5} {'cost':>7}")
    for s, rs in rows.items():
        model = rs[0][0]["model"]
        w_in = [read_in(r["usage"]) for r, _, _ in rs]
        w_cost = sum(cost(r["usage"], model, read_in(r["usage"])) for r, _, _ in rs)
        us = [u for _, u, _ in rs if u]
        u_in = [read_in(u["usage"]) for u in us] or [0]
        u_new = [u["usage"]["cache_creation_input_tokens"] + u["usage"]["input_tokens"] for u in us] or [0]
        u_cost = sum(cost(u["usage"], model, 0) for u in us)
        turns = [u["turns"] for u in us] or [0]
        n_unp = sum(1 for *_, n in rs if n)
        print(f"{s:5} {len(rs):>3} | {st.median(w_in):>18,.0f} ${w_cost:>6.2f} {n_unp:>9} | "
              f"{len(us):>10}/{len(rs):<3} {st.median(u_in):>8,.0f} {st.median(u_new):>7,.0f} {st.median(turns):>5} ${u_cost:>6.2f}")
    if show_numbers:
        for s, rs in rows.items():
            for r, _, n in rs:
                if n:
                    print(f"  {s}-{r['probe']}: {', '.join(n)}")


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args[args.index("--answers") + 1] if "--answers" in args else "answers", "--numbers" in args)
