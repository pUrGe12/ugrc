"""Facts plus prose on 20 more papers (PLAN.md): prose, facts and pdf on the cheme2 papers, three runs.

    LLAMA_URL=<server>/v1 LLAMA_KEY=... python experiments/cheme2/run.py [--arms prose,facts,pdf] [--runs 1,2,3]
        [--workers N] [--papers a,b]
    python experiments/cheme2/run.py check     # no model: prose with nothing added is the facts form, for every paper
    python experiments/cheme2/run.py sizes     # no model: what each paper costs in each arm's prompt

Arms (answers/<arm>-r<k>/<paper>-<id>.json; a record that exists is skipped, so a run resumes), all code reused as is:
  llama-facts-prose  experiments/prose/run.py: document() and prompt().
  llama-facts        experiments/cheme/run.py's facts arm: scaling.condensed(con, "facts") and facts_prompt().
  llama-direct       experiments/cheme/run.py's pdf arm: pdftotext with bench-llama/direct.py's prompt.
The plan, papers and probes are frozen (frozen.sha256): the runner refuses to start if they changed.
"""
import hashlib
import importlib.util
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


P = _load("prose_run", ROOT / "experiments" / "prose" / "run.py")    # document, prompt, FORM; P.C = cheme run
C = P.C
scaling, direct, store, llm = C.scaling, C.direct, C.store, C.llm

RUNS_DIR = ROOT / "runs" / "cheme2"
PDFS = Path.home() / "Desktop" / "papers-cheme2"
ARMS = {"prose": "llama-facts-prose", "facts": "llama-facts", "pdf": "llama-direct"}
TITLES = {k: C._title(v["title"]) for k, v in json.loads((HERE / "papers.json").read_text()).items()}
C.TITLES.update(TITLES)          # prose's prompt() and cheme's facts_prompt() look titles up here
lock = threading.Lock()


def probes():
    digest, name = (ROOT / "experiments" / "cheme" / "extract.sha256").read_text().split()
    if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
        raise SystemExit(f"{name} changed since it was frozen (../cheme/extract.sha256)")
    C._check_frozen(HERE / "frozen.sha256")
    for paper, ps in json.loads((HERE / "probes.json").read_text())["papers"].items():
        for p in ps:
            yield paper, p


def answer_path(arm, run, paper, pid):
    return HERE / "answers" / f"{ARMS[arm]}-r{run}" / f"{paper}-{pid}.json"


def connect(paper):
    con = store.connect_question(RUNS_DIR / paper)
    assert store.has_clauses(con), paper
    return con


def paper_text(paper):
    """pdftotext of the PDF ugrc ingested (checked by hash), cached in direct-text/."""
    man = json.loads((RUNS_DIR / paper / "manifest.json").read_text())
    out = HERE / "direct-text" / f"{paper}.txt"
    if not out.exists():
        pdf = PDFS / man["file"]
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != man["sha256"]:
            raise SystemExit(f"{pdf} is not the PDF ugrc ingested for {paper}")
        out.parent.mkdir(exist_ok=True)
        subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf), str(out)], check=True)
    text = out.read_text()
    return text, {"file": man["file"], "pages": man["pages"], "pdf_sha256": man["sha256"], "tool": "pdftotext",
                  "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "chars": len(text)}


_cache = {}


def cached(kind, paper):
    with lock:
        if (kind, paper) not in _cache:
            con = connect(paper)
            _cache[(kind, paper)] = {"facts": lambda: scaling.condensed(con, "facts"),
                                     "numbers": lambda: scaling.cr.printed_numbers(con)}[kind]()
        return _cache[(kind, paper)]


def _llama(system, user, paper):
    resp = scaling.cr.chat(system, user)
    choice = resp["choices"][0]
    text = choice["message"].get("content") or ""
    return resp, choice, text, sorted({scaling.cr._n(x) for x in scaling.cr.NUM.findall(text)}
                                      - cached("numbers", paper) - {""})


def one(job):
    paper, p, arm, run = job
    f = answer_path(arm, run, paper, p["id"])
    if f.exists():
        return
    t = time.time()
    base = {"arm": ARMS[arm], "run": run, "set": "cheme2", "paper": paper, "probe": p["id"], "cat": p["cat"],
            "question": p["q"], "expect": p["expect"], "trap": p.get("trap"), "must": p["must"], "model": C.hybrid.MODEL}
    if arm == "prose":
        doc, picked, used = P.document(connect(paper), p["q"])
        system, user = P.prompt(paper, p["q"], doc)
        resp, choice, text, extra = _llama(system, user, paper)
        rec = {"rendered": text, "finish_reason": choice.get("finish_reason"), "turns": 1, "tool_calls": 0,
               "numbers_not_in_paper": extra, "added": {"sentences": picked, "chars": used},
               "document": {"form": "facts+prose", "chars": len(doc), "sha256": hashlib.sha256(doc.encode()).hexdigest()},
               "prompt": {"style": "prose", "system": system, "user_sha256": hashlib.sha256(user.encode()).hexdigest(),
                          "user_chars": len(user)}, "usage": resp.get("usage")}
    elif arm == "facts":
        doc = cached("facts", paper)
        system, user = C.facts_prompt(paper, p["q"], doc)
        resp, choice, text, extra = _llama(system, user, paper)
        rec = {"rendered": text, "finish_reason": choice.get("finish_reason"), "turns": 1, "tool_calls": 0,
               "numbers_not_in_paper": extra,
               "document": {"form": "facts", "chars": len(doc), "sha256": hashlib.sha256(doc.encode()).hexdigest()},
               "prompt": {"style": "scaling:facts", "system": system,
                          "user_sha256": hashlib.sha256(user.encode()).hexdigest(), "user_chars": len(user)},
               "usage": resp.get("usage")}
    else:
        text, source = paper_text(paper)
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


def check():
    """With nothing added, the prose document is byte for byte the facts form."""
    for paper in json.loads((HERE / "probes.json").read_text())["papers"]:
        con = connect(paper)
        doc, picked, _ = P.document(con, "", max_sentences=0)
        assert not picked and doc == scaling.condensed(con, "facts"), paper
        print(f"ok  {paper}")


def sizes():
    per = {}
    for paper, p in probes():
        doc, picked, used = P.document(connect(paper), p["q"])
        per.setdefault(paper, []).append((len(picked), used, len(doc)))
    for paper, xs in per.items():
        n = len(xs)
        text, _ = paper_text(paper)
        print(f"{paper:20} questions {n:2}  added {sum(x[0] for x in xs) / n:4.1f} sentences "
              f"{sum(x[1] for x in xs) / n:5.0f} chars  prose {sum(x[2] for x in xs) / n / 1000:5.1f}k  "
              f"facts {len(cached('facts', paper)) / 1000:5.1f}k  pdftotext {len(text) / 1000:6.1f}k")


if __name__ == "__main__":
    cmd = sys.argv[1:2]
    if cmd in (["check"], ["sizes"]):
        {"check": check, "sizes": sizes}[cmd[0]]()
        sys.exit(0)
    if not scaling.cr.URL or not direct.URL:
        raise SystemExit("set LLAMA_URL (the server's /v1) and LLAMA_KEY")
    arg = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d  # noqa: E731
    arms = arg("--arms", "prose,facts,pdf").split(",")
    assert set(arms) <= set(ARMS), arms
    runs = [int(x) for x in arg("--runs", "1,2,3").split(",")]
    workers = int(arg("--workers", "6"))
    papers = arg("--papers", None)
    papers = set(papers.split(",")) if papers else None
    qs = [(paper, p) for paper, p in probes() if not papers or paper in papers]
    jobs = [(paper, p, a, r) for r in runs for paper, p in qs for a in arms]
    print(f"{len(jobs)} answers: arms {arms}, runs {runs}, {workers} workers", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))
    print("all done", flush=True)
