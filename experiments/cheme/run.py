"""The ChemE held-out test (PLAN.md): hybrid, facts and pdf on new6 (extractor v5) and the 9 ChemE papers.

    LLAMA_URL=<server>/v1 LLAMA_KEY=... python experiments/cheme/run.py [--arms hybrid,facts,pdf] [--runs 1,2,3]
        [--workers N] [--sets new6,cheme] [--papers a,b]
    python experiments/cheme/run.py sizes        # no model: what each paper costs in each arm's prompt (characters)

Arms (answers/<arm>-r<k>/<paper>-<id>.json; a record that exists is skipped, so a run resumes):
  llama-hybrid-v5  experiments/bench-cross/hybrid.py as it is, on atoms from extractor v5 (runs/new6-v5, runs/cheme).
  llama-facts      the scaling test's condensed clause base, the paper alone (its llama-scale-facts-L1): page by page
                   the clause-base sentences that print a value Jev did not read as an identifier, then the tables
                   row by row and figure facts; the scaling test's system prompt for that form.
  llama-direct     bench-llama/direct.py's prompt with the PDF's pdftotext. On new6 not run again: the three runs of
                   experiments/new6/answers/llama-direct-r* are reused (answer_path).
The probes and plan are frozen (frozen.sha256 here, ../new6/frozen.sha256): the runner refuses to start if they changed.
"""
import hashlib
import html
import importlib.util
import json
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "bench-cross"))
sys.path.insert(0, str(ROOT / "experiments" / "bench-llama"))
import hybrid  # noqa: E402
import direct  # noqa: E402  (chat, numbers_not_in_text, SYSTEM)
from ugrc import llm, store  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


scaling = _load("scaling_run", ROOT / "experiments" / "scaling" / "run.py")    # condensed, SYSTEM, FORM, cr
new6 = _load("new6_run", ROOT / "experiments" / "new6" / "run.py")              # TITLES

SETS = {
    "new6": {"runs": ROOT / "runs" / "new6-v5", "pdfs": Path.home() / "Desktop" / "papers-new6",
             "probes": ROOT / "experiments" / "new6" / "probes.json",
             "frozen": ROOT / "experiments" / "new6" / "frozen.sha256"},
    "cheme": {"runs": ROOT / "runs" / "cheme", "pdfs": Path.home() / "Desktop" / "papers-cheme",
              "probes": HERE / "probes.json", "frozen": HERE / "frozen.sha256"},
}
ARMS = {"hybrid": "llama-hybrid-v5", "facts": "llama-facts", "pdf": "llama-direct"}
lock = threading.Lock()


def _title(t):
    return re.sub(r"<[^>]+>", "", html.unescape(t)).rstrip(".")


TITLES = {**new6.TITLES, **{k: _title(v["title"]) for k, v in json.loads((HERE / "papers.json").read_text()).items()}}


def _check_frozen(path):
    """Every 'sha256  file' line of a frozen.sha256 still holds."""
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        f = path.parent / name.strip().lstrip("*")
        if hashlib.sha256(f.read_bytes()).hexdigest() != digest:
            raise SystemExit(f"{f} changed since it was frozen")


def probes(sets=SETS):
    digest, name = (HERE / "extract.sha256").read_text().split()
    if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
        raise SystemExit(f"{name} changed since it was frozen (extract.sha256)")
    for s in sets:
        _check_frozen(SETS[s]["frozen"])
        for paper, ps in json.loads(SETS[s]["probes"].read_text())["papers"].items():
            for p in ps:
                yield s, paper, p


def answer_path(arm, run, s, paper, pid):
    if arm == "pdf" and s == "new6":
        return ROOT / "experiments" / "new6" / "answers" / f"llama-direct-r{run}" / f"{paper}-{pid}.json"
    return HERE / "answers" / f"{ARMS[arm]}-r{run}" / f"{paper}-{pid}.json"


def connect(s, paper):
    con = store.connect_question(SETS[s]["runs"] / paper)
    assert store.has_clauses(con), paper
    return con


def paper_text(s, paper):
    """pdftotext of the PDF ugrc ingested (checked by hash), cached in direct-text/."""
    man = json.loads((SETS[s]["runs"] / paper / "manifest.json").read_text())
    out = HERE / "direct-text" / f"{paper}.txt"
    if not out.exists():
        pdf = SETS[s]["pdfs"] / man["file"]
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != man["sha256"]:
            raise SystemExit(f"{pdf} is not the PDF ugrc ingested for {paper}")
        out.parent.mkdir(exist_ok=True)
        subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf), str(out)], check=True)
    text = out.read_text()
    return text, {"file": man["file"], "pages": man["pages"], "pdf_sha256": man["sha256"], "tool": "pdftotext",
                  "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "chars": len(text)}


_cache = {}


def cached(kind, s, paper):
    with lock:
        if (kind, paper) not in _cache:
            con = connect(s, paper)
            _cache[(kind, paper)] = {"pages": lambda: hybrid.pages(con),
                                     "facts": lambda: scaling.condensed(con, "facts"),
                                     "numbers": lambda: scaling.cr.printed_numbers(con)}[kind]()
        return _cache[(kind, paper)]


def facts_prompt(paper, question, doc):
    title = TITLES[paper]
    system = scaling.SYSTEM.format(title=title, form=scaling.FORM["facts"].format(among=""))
    return system, f'<document title="{title}">\n{doc}\n</document>\n\nQuestion (about "{title}"): {question}'


def one(job):
    s, paper, p, arm, run = job
    f = answer_path(arm, run, s, paper, p["id"])
    if f.exists():
        return
    t = time.time()
    base = {"arm": ARMS[arm], "run": run, "set": s, "paper": paper, "probe": p["id"], "cat": p["cat"],
            "question": p["q"], "expect": p["expect"], "trap": p.get("trap"), "must": p["must"], "model": hybrid.MODEL}
    if arm == "hybrid":
        rec = hybrid.answer(connect(s, paper), p["q"], cached("pages", s, paper), title=TITLES[paper], way="leads")
    elif arm == "facts":
        doc = cached("facts", s, paper)
        system, user = facts_prompt(paper, p["q"], doc)
        resp = scaling.cr.chat(system, user)
        choice = resp["choices"][0]
        text = choice["message"].get("content") or ""
        rec = {"rendered": text, "finish_reason": choice.get("finish_reason"), "turns": 1, "tool_calls": 0,
               "numbers_not_in_paper": sorted({scaling.cr._n(x) for x in scaling.cr.NUM.findall(text)}
                                              - cached("numbers", s, paper) - {""}),
               "document": {"form": "facts", "chars": len(doc), "sha256": hashlib.sha256(doc.encode()).hexdigest()},
               "prompt": {"style": "scaling:facts", "system": system,
                          "user_sha256": hashlib.sha256(user.encode()).hexdigest(), "user_chars": len(user)},
               "usage": resp.get("usage")}
    else:
        text, source = paper_text(s, paper)
        resp = direct.chat(direct.SYSTEM.format(file=source["file"], pages=source["pages"]),
                           f"<document>\n{text}\n</document>\n\nQuestion: {p['q']}")
        choice = resp["choices"][0]
        answer = choice["message"].get("content") or ""
        rec = {"rendered": answer, "finish_reason": choice.get("finish_reason"), "turns": 1, "tool_calls": 0,
               "numbers_not_in_text": direct.numbers_not_in_text(answer, text), "source": source,
               "prompt": {"style": "direct", "system": direct.SYSTEM}, "usage": resp.get("usage")}
    rec = {**base, **rec, "sampling": {"temperature": llm.TEMPERATURE, "top_p": llm.TOP_P, "max_tokens": llm.MAX_OUTPUT},
           "seconds": round(time.time() - t, 1)}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
    u = rec.get("usage") or {}
    with lock:
        print(f"done  {ARMS[arm]}-r{run} {paper}-{p['id']:3} prompt={u.get('prompt_tokens', '?'):>6} "
              f"{rec.get('finish_reason')} {time.time() - t:5.1f}s", flush=True)


def sizes():
    for s in SETS:
        for paper in json.loads(SETS[s]["probes"].read_text())["papers"]:
            pgs = cached("pages", s, paper)
            rendered = sum(len(v["text"]) for v in pgs.values())
            facts = cached("facts", s, paper)
            text, _ = paper_text(s, paper)
            print(f"{s:5} {paper:16} pages={len(pgs):3} rendered={rendered / 1000:6.1f}k chars "
                  f"({'whole' if rendered / 3.6 <= hybrid.BUDGET else 'picked'})  facts={len(facts) / 1000:6.1f}k  "
                  f"pdftotext={len(text) / 1000:6.1f}k   {TITLES[paper][:50]}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["sizes"]:
        sizes()
        sys.exit(0)
    if sys.argv[1:2] == ["show"]:
        print(cached("facts", sys.argv[2], sys.argv[3]))
        sys.exit(0)
    if not hybrid.LLAMA_URL or not direct.URL or not scaling.cr.URL:
        raise SystemExit("set LLAMA_URL (the server's /v1) and LLAMA_KEY")
    arg = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d  # noqa: E731
    arms = arg("--arms", "hybrid,facts,pdf").split(",")
    assert set(arms) <= set(ARMS), arms
    runs = [int(x) for x in arg("--runs", "1,2,3").split(",")]
    workers = int(arg("--workers", "6"))
    sets = arg("--sets", "new6,cheme").split(",")
    papers = arg("--papers", None)
    papers = set(papers.split(",")) if papers else None
    # a paper's questions queue together, and a question's arms and runs together (the server reuses the prefill)
    jobs = [(s, paper, p, a, r) for s, paper, p in probes(sets) if not papers or paper in papers
            for r in runs for a in arms if not (a == "pdf" and s == "new6")]
    missing = [j for j in [(s, paper, p, "pdf", r) for s, paper, p in probes(sets) if s == "new6" and "pdf" in arms
                           for r in runs] if not answer_path("pdf", j[4], "new6", j[1], j[2]["id"]).exists()]
    if missing:
        raise SystemExit(f"{len(missing)} reused new6 pdf answers are missing")
    print(f"{len(jobs)} answers: arms {arms}, runs {runs}, sets {sets}, {workers} workers", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))
    print("all done", flush=True)
