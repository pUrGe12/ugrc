"""Llama reasons on the clause base: no tools, no SQL, no door, no pointers. One reply per question.

    LLAMA_URL=<server>/v1 LLAMA_KEY=... python experiments/clause-reasoning/run.py --ways clauses,text --runs 1 [--workers 6]

The 154 single-paper questions (bench-leads, bench-multistep), each asked of its own paper (runs/bench/<paper>), whose
whole clause base goes in the prompt. Two ways of writing it (PLAN.md):
  clauses  every sentence of the clause base in reading order, marked with what it does (Jev's modality and polarity),
           and under it every value it prints with Jev's reading: role, property, what it is of, by what method, what
           it measures                                              -> answers/llama-clauses-r<k>/
  text     the same sentences with nothing of Jev's: no marks, no readings      -> answers/llama-clauses-text-r<k>/
Both also get every table row by row (caption and column headers first) and the figure facts, page by page, as the
hybrid renders them: the clause base reads prose only. Answers go to experiments/bench-llama/answers/<arm>-r<k>/<bench>/
<paper>-<id>.json in the shape bench-llama/grade.py reads. Each record lists the numbers in its answer printed in no
atom of the paper (`numbers_not_in_paper`: computed or invented). A record that exists is skipped.
"""
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "bench-llama"))
from ugrc import llm, store  # noqa: E402
from direct import TITLES  # noqa: E402

URL = os.environ.get("LLAMA_URL", "").rstrip("/")
KEY = os.environ.get("LLAMA_KEY")
MODEL = os.environ.get("LLAMA_MODEL", "llama-3.1-8b-instruct")
ARMS = {"clauses": "llama-clauses", "text": "llama-clauses-text"}
OUT = ROOT / "experiments" / "bench-llama" / "answers"
lock = threading.Lock()

SYSTEM = ('You answer questions about one document, "{title}", using only what it contains. Below is the document '
          "page by page: its text sentence by sentence, its tables written row by row, and facts read from its "
          "figures.{readings} Answer briefly. If you compute a number, show the calculation. If the question assumes "
          "something the document contradicts, say so. If the document does not hold the answer, say so.")
READINGS = (" Each sentence is marked with what it does (a result, a method, an interpretation, a possibility, "
            "background from other work, or other; and whether it is negated). Under a sentence, every value it "
            "prints is listed with what a classifier read it to be: its role (result: this work measured or obtained "
            "it; setting: a condition chosen; background: from other work; count; identifier: a label), what it is "
            "of, by what method, and what it measures. The readings can be wrong; the sentence is what the document "
            "says.")


def frozen_questions():
    for line in (HERE / "frozen.sha256").read_text().splitlines():
        digest, name = line.split()
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != digest:
            raise SystemExit(f"clause-reasoning/{name} changed since it was frozen")
    return json.loads((HERE / "questions.json").read_text())["stage1"]


_ORDER = re.compile(r"p(\d+)\.L(\d+):(\d+)")


def _order(sid):
    m = _ORDER.match(sid)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (10 ** 6, 0, 0)


def _offset(mid):
    try:
        return int(mid.rsplit("#", 1)[1])
    except (IndexError, ValueError):
        return 0


def _reading(m):
    role, prop, about, method, quantity = m
    parts = [role or "?"]
    if prop and prop != "other":
        parts.append(prop)
    for label, xs in (("of", about), ("by", method), ("measures", quantity)):
        if xs:
            parts.append(f"{label} " + " / ".join(xs))
    return "; ".join(parts)


def render(con, way):
    """The document as the prompt gives it: per page, the clause base's sentences (with Jev's marks and readings when
    way == "clauses"), then the page's tables row by row, then its figure facts."""
    q = lambda sql, args=(): con.execute(sql, list(args)).fetchall()  # noqa: E731
    pages = {}
    values = {}
    for mid, sid, text, role, prop, about, method, quantity in q(
            "SELECT id, sentence, text, role, property, about, method, quantity FROM measures"):
        values.setdefault(sid, []).append((mid, text, (role, prop, about, method, quantity)))
    for sid, page, text, modality, polarity in sorted(q("SELECT id, page, text, modality, polarity FROM sentences"),
                                                      key=lambda r: _order(r[0])):
        out = pages.setdefault(page, [])
        if way == "clauses":
            mark = (modality or "other") + (", negated" if polarity == "negated" else "")
            out.append(f"- [{mark}] {text}")
            for mid, vtext, m in sorted(values.get(sid, []), key=lambda v: _offset(v[0])):
                out.append(f"    value {vtext!r}: {_reading(m)}")
        else:
            out.append(f"- {text}")
    heads = {}
    for tid, h in q("SELECT table_id, header FROM table_columns ORDER BY table_id, col_no"):
        heads.setdefault(tid, []).append(h or "")
    for tid, page, label, cap in q("SELECT id, page, label, caption FROM tables ORDER BY page, id"):
        out = pages.setdefault(page, [])
        out.append(f"{label or 'Table'}. {cap or ''}" + (f"\nColumns: {' | '.join(heads[tid])}" if tid in heads else ""))
        rows = {}
        for r, t in q("SELECT row_no, text FROM cells WHERE table_id = ? ORDER BY row_no, col_no", [tid]):
            rows.setdefault(r, []).append(t or "")
        out += [" | ".join(cells) for _, cells in sorted(rows.items())]
    for fid, page, label in q("SELECT id, page, label FROM figures WHERE label IS NOT NULL ORDER BY page, id"):
        for st, v, u in q("SELECT statement, value, unit FROM figure_facts WHERE figure_id = ? ORDER BY fact_no", [fid]):
            pages.setdefault(page, []).append(f"({label}, read from the image) {st}" + (f" ({v} {u or ''})" if v is not None else ""))
    return "\n\n".join(f"=== page {p} ===\n" + "\n".join(lines) for p, lines in sorted(pages.items()))


NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def _n(s):
    return s.replace(",", "").rstrip(".")


def printed_numbers(con):
    return {_n(x) for (t,) in con.execute("SELECT text FROM atoms WHERE text IS NOT NULL").fetchall() for x in NUM.findall(t)}


def chat(system, user):
    body = json.dumps({"model": MODEL, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                       "max_tokens": llm.MAX_OUTPUT, "temperature": llm.TEMPERATURE, "top_p": llm.TOP_P}).encode()
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {KEY}"} if KEY else {})}
    last = None
    for attempt in range(llm.RETRIES + 1):
        if attempt:
            time.sleep(min(2 ** attempt, 60))
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{URL}/chat/completions", data=body, headers=headers),
                                        timeout=llm.TIMEOUT_S) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in llm.RETRY_CODES:
                raise                                   # a bad key or an over-long prompt will not fix itself
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
    raise llm.ServerError(f"the model server kept failing: {last}")


def log(msg):
    with lock:
        print(msg, flush=True)


def main(ways, runs, workers):
    import run as bench
    keys = frozen_questions()
    probes = {f"{b}/{paper}-{p['id']}": (b, paper, p) for b, paper, p in bench.probes()}
    assert set(keys) <= set(probes)
    ctx, nums = {}, {}

    def context(paper, way):
        with lock:
            if (paper, way) not in ctx:
                con = store.connect_question(ROOT / "runs" / "bench" / paper)
                assert store.has_clauses(con), paper
                ctx[(paper, way)] = render(con, way)
                nums.setdefault(paper, printed_numbers(con))
        return ctx[(paper, way)]

    # a paper's questions run together, each way's in a block, so the server reuses the prefill of the shared prompt
    jobs = [(k, r, w) for r in runs for paper in sorted({probes[k][1] for k in keys}) for w in ways
            for k in sorted(k for k in keys if probes[k][1] == paper)]

    def one(job):
        k, run, way = job
        b, paper, p = probes[k]
        out = OUT / f"{ARMS[way]}-r{run}" / b
        out.mkdir(parents=True, exist_ok=True)
        f = out / f"{paper}-{p['id']}.json"
        if f.exists():
            return
        t = time.time()
        doc = context(paper, way)
        system = SYSTEM.format(title=TITLES[paper], readings=READINGS if way == "clauses" else "")
        resp = chat(system, f"{doc}\n\nQuestion: {p['q']}")
        text = resp["choices"][0]["message"].get("content") or ""
        rec = {"arm": ARMS[way], "run": run, "bench": b, "paper": paper, "probe": p["id"], "cat": p["cat"],
               "expect": p["expect"], "trap": p.get("trap"), "question": p["q"], "model": MODEL,
               "rendered": text, "finish_reason": resp["choices"][0].get("finish_reason"), "usage": resp.get("usage"),
               "turns": 1, "tool_calls": 0, "door_refusals": [], "citations": [], "runs": [], "trace": [],
               "numbers_not_in_paper": sorted({_n(x) for x in NUM.findall(text)} - nums[paper] - {""}),
               "prompt": {"style": f"clause-reasoning:{way}", "system": system,
                          "document_sha256": hashlib.sha256(doc.encode()).hexdigest(), "document_chars": len(doc)},
               "seconds": round(time.time() - t, 1)}
        f.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
        log(f"done  {ARMS[way]}-r{run} {k:40} {rec['usage'].get('prompt_tokens') if rec['usage'] else '?'} tok "
            f"{time.time() - t:.0f}s")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))


if __name__ == "__main__":
    ways = sys.argv[sys.argv.index("--ways") + 1].split(",")
    assert set(ways) <= set(ARMS), ways
    runs = [int(x) for x in sys.argv[sys.argv.index("--runs") + 1].split(",")]
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 6
    if "--show" in sys.argv:                            # print one paper's two documents, no model call
        paper = sys.argv[sys.argv.index("--show") + 1]
        con = store.connect_question(ROOT / "runs" / "bench" / paper)
        for w in ways:
            print(f"######## {w}\n{render(con, w)[:6000]}\n")
        sys.exit(0)
    log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} start: ways {ways}, runs {runs}")
    main(ways, runs, workers)
    log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} end")
