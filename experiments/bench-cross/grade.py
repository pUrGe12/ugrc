"""Grade the cross-paper arms. Every answer is graded by hand (hand.json: {"<arm>-r1/<id>": {"verdict", "note"}});
the automatic check (bench-leads' `check`: every `must` group present, no `must_not`) is shown beside it.

    python experiments/bench-cross/grade.py sheet [ARM]   every answer not yet hand-graded, with its key; for ugrc
                                                         arms, the documents each citation points to
    python experiments/bench-cross/grade.py report       the table, by arm and category, and question-by-question pairs
    python experiments/bench-cross/grade.py pick         does Jev's page picking help the hybrid: llama-hybrid (leads, then
                                                         BM25) against llama-hybrid-bm25, runs 1-3 each, on the cross-paper
                                                         questions and the single-paper questions of ensm-2021 and cai2026
    python experiments/bench-cross/grade.py pick-sheet   those answers not yet hand-graded, by question, beside run 1's grade
"""
import collections
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "bench-leads"))
from grade import check, sign_test  # noqa: E402

ORDER = ["llama-direct-fill-r1", "llama-corpus-plain-sp-r1", "llama-corpus-leads-sp-r1", "llama-hybrid-r1"]
PICK_ARMS = ("llama-hybrid", "llama-hybrid-bm25")
PICK_PAPERS = ("ensm-2021", "cai2026")
RUNS = (1, 2, 3)


def load():
    probes = {p["id"]: p for p in json.loads((HERE / "probes.json").read_text())["probes"]}
    recs, errs = {}, {}
    for f in sorted((HERE / "answers").glob("*/*.json")):
        key = f"{f.parent.name}/{f.name.removesuffix('.error.json').removesuffix('.json')}"
        (errs if f.name.endswith(".error.json") else recs)[key] = json.loads(f.read_text())
    hand = json.loads((HERE / "hand.json").read_text()) if (HERE / "hand.json").exists() else {}
    return probes, recs, errs, hand


def verdicts():
    probes, recs, errs, hand = load()
    v = {}
    for k, r in recs.items():
        v[k] = hand[k]["verdict"] if k in hand else ("check-pass" if check(r, probes[k.split("/")[1]])[0] else "open")
    for k in errs:
        v[k] = "no answer"
    return probes, v


def _cited_docs(r):
    docs = []
    for c in r.get("citations") or []:
        src = c.get("source") or {}
        a = src.get("atom") or src.get("id") or ""
        d = a.split(":")[0] if ":" in a else None
        if d and d not in docs:
            docs.append(d)
    return docs


def sheet(arm=None):
    probes, recs, errs, hand = load()
    n = 0
    for k, r in sorted(recs.items()):
        if k in hand or (arm and not k.startswith(arm)):
            continue
        p = probes[k.split("/")[1]]
        ok, why = check(r, p)
        extra = ""
        if r.get("citations") is not None and "corpus" in k:
            extra = f" cites={_cited_docs(r)}"
        if "documents" in r:
            extra = f" in-prompt-needed={r.get('needed_documents_in_prompt')}/{p['papers']}"
        if "pointers" in r:
            extra = f" needed-in-pages={r.get('needed_pages_in_prompt')}/{p['papers']} not_in_passages={r['pointers']['not_in_passages']}"
        print(f"### {k} [{'OK' if ok else why}] turns={r.get('turns')}{extra}\nQ: {p['q']}\nE: {p['expect']}\nT: {p.get('trap')}\n"
              f"A: {r['rendered'][:1200]}\n")
        n += 1
    print(n, "to grade")


def report():
    probes, v = verdicts()
    arms = [a for a in ORDER if any(k.startswith(a + "/") for k in v)] + sorted(
        {k.split("/")[0] for k in v} - set(ORDER))
    cats = sorted({p["cat"] for p in probes.values()})
    print(f"{'arm':26} {'right':>5} {'part':>4} {'wrong':>5} {'none':>4} {'open':>4}  " + " ".join(f"{c:>5}" for c in cats))
    for a in arms:
        c = collections.Counter(x for k, x in v.items() if k.startswith(a + "/"))
        bycat = {cat: sum(1 for pid, p in probes.items() if p["cat"] == cat and v.get(f"{a}/{pid}") == "correct") for cat in cats}
        ncat = collections.Counter(p["cat"] for p in probes.values())
        print(f"{a:26} {c['correct']:>5} {c['partial']:>4} {c['wrong']:>5} {c['no answer']:>4} {c['open'] + c['check-pass']:>4}  "
              + " ".join(f"{bycat[cat]:>2}/{ncat[cat]:<2}" for cat in cats))
    for i, a in enumerate(arms):
        for b in arms[i + 1:]:
            w = sum(1 for pid in probes if v.get(f"{b}/{pid}") == "correct" and v.get(f"{a}/{pid}") != "correct")
            l = sum(1 for pid in probes if v.get(f"{a}/{pid}") == "correct" and v.get(f"{b}/{pid}") != "correct")
            print(f"{b} vs {a}: {b} right where {a} is not on {w}, the reverse on {l} (sign test p = {sign_test(w, l):.3f})")


def _bench():
    """bench-llama's grader (its probes, records and hand grades), loaded by path: its name clashes with this one."""
    spec = importlib.util.spec_from_file_location("bench_grade", ROOT / "experiments" / "bench-llama" / "grade.py")
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    return g


def key_pages(expect, papers, default=None):
    """{(paper, page)} the key cites: each `pN.` reference, under the paper named last before it (or `default`)."""
    out, cur = set(), default
    for m in re.finditer(r"(" + "|".join(map(re.escape, sorted(papers, key=len, reverse=True))) + r")|\bp(\d+)\.", expect):
        if m.group(1):
            cur = m.group(1)
        elif cur:
            out.add((cur, int(m.group(2))))
    return out


def _has_key_pages(rec, kp, paper=None):
    """Whether every page the key cites was in the prompt (None when the key cites none). A single paper's pages carry
    no document; `paper` fills it in."""
    if not kp:
        return None
    got = {(d or paper, pg) for d, pg in rec["pages"]}
    return all(k in got for k in kp)


def _pick_items():
    """[(set, question key, probe, {arm: {run: (verdict, record)}})] for every question of the comparison."""
    probes, recs, errs, hand = load()
    _, cv = verdicts()
    corpus = [d.name for d in (ROOT / "runs" / "bench").iterdir()]
    items = []
    for pid, p in probes.items():
        got = {a: {r: (cv.get(f"{a}-r{r}/{pid}"), recs.get(f"{a}-r{r}/{pid}")) for r in RUNS} for a in PICK_ARMS}
        items.append(("cross", pid, p, got, key_pages(p["expect"], corpus), None))
    g = _bench()
    bprobes, brecs, berrs, bhand = g.load()
    bv = g.verdicts(bprobes, brecs, berrs, bhand)
    for (b, paper, pid), p in bprobes.items():
        if paper not in PICK_PAPERS:
            continue
        k = f"{b}/{paper}-{pid}"
        got = {a: {r: ((bv.get(f"{a}-r{r}/{k}") or (None,))[0], brecs.get(f"{a}-r{r}/{k}")) for r in RUNS} for a in PICK_ARMS}
        items.append(("single", k, p, got, key_pages(p["expect"], [paper], default=paper), paper))
    return items


def pick():
    items = _pick_items()
    for group in ("cross", "single", None):
        its = [x for x in items if group is None or x[0] == group]
        name = {"cross": "cross-paper (33)", "single": "single-paper, ensm-2021 + cai2026 (28)", None: "both (61)"}[group]
        print(f"\n== {name}")
        right = {}
        for a in PICK_ARMS:
            vs = [got[a][r][0] for _, _, _, got, _, _ in its for r in RUNS]
            c = collections.Counter(vs)
            per_run = [sum(got[a][r][0] == "correct" for _, _, _, got, _, _ in its) for r in RUNS]
            cov = [_has_key_pages(got[a][r][1], kp, paper) for _, _, _, got, kp, paper in its for r in RUNS if got[a][r][1]]
            covered = sum(x is True for x in cov), sum(x is not None for x in cov)
            print(f"{a:20} right per run {per_run}  all runs: right {c['correct']} partial {c['partial']} wrong {c['wrong']} "
                  f"none {c['no answer']} ungraded {c['open'] + c['check-pass'] + c['unreviewed']} missing {c[None]}  "
                  f"| every key page in the prompt: {covered[0]}/{covered[1]}")
            right[a] = {q: sum(got[a][r][0] == "correct" for r in RUNS) for _, q, _, got, _, _ in its}
        a, b = PICK_ARMS
        w = sum(right[a][q] > right[b][q] for q in right[a])
        l = sum(right[a][q] < right[b][q] for q in right[a])
        print(f"per question, right runs out of 3: leads better on {w}, BM25 alone better on {l}, equal on {len(right[a]) - w - l} "
              f"(sign test p = {sign_test(w, l):.3f})")
        diff = [q for q in right[a] if right[a][q] != right[b][q]]
        if diff:
            print("  " + ", ".join(f"{q} {right[a][q]}-{right[b][q]}" for q in diff))


def pick_sheet():
    n = 0
    for group, q, p, got, kp, paper in _pick_items():
        ref = got["llama-hybrid"][1]
        todo = [(a, r) for a in PICK_ARMS for r in RUNS if got[a][r][1] is not None and got[a][r][0] not in
                ("correct", "partial", "wrong", "no answer")]
        if not todo:
            continue
        hand_ref = ""
        if group == "cross":
            hand_ref = (json.loads((HERE / "hand.json").read_text()).get(f"llama-hybrid-r1/{q}") or {}).get("note", "")
        else:
            hand_ref = (json.loads((ROOT / "experiments" / "bench-llama" / "hand.json").read_text())
                        .get(f"llama-hybrid-r1/{q}") or {}).get("note", "")
        print(f"######## {group} {q}  key pages {sorted(kp)}\nQ: {p['q']}\nE: {p['expect']}\nT: {p.get('trap')}\n"
              f"run 1 (leads): {ref[0]} — {hand_ref}")
        for a, r in todo:
            rec = got[a][r][1]
            has = _has_key_pages(rec, kp, paper)
            print(f"--- {a}-r{r} [key pages in prompt: {has}] not_in_passages={rec['pointers']['not_in_passages']}\n"
                  f"{rec['rendered'][:1500]}")
            n += 1
        print()
    print(n, "to grade")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "sheet":
        sheet(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        {"report": report, "pick": pick, "pick-sheet": pick_sheet}[cmd]()
