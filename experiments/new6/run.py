"""The hybrid on 6 held-out papers, against the pasted PDF. Same model server, sampling and prompts as the bench.

    LLAMA_URL=<server>/v1 LLAMA_KEY=... python experiments/new6/run.py [--arms hybrid,direct] [--runs 1,2,3]
        [--workers N] [--only paper-ID,...]
    python experiments/new6/run.py sizes        # no model: what each paper costs in each arm's prompt

Arms (answers/<arm>-r<k>/<paper>-<id>.json; a record that exists is skipped, so a run resumes):
  llama-hybrid  experiments/bench-cross/hybrid.py as it is: pages rendered from ugrc's atoms (tables row by row),
                Jev's lead pages first, then BM25, up to 24k tokens (a paper that fits goes whole); one free reply;
                code points every number at the atom that prints it.
  llama-direct  experiments/bench-llama/direct.py's prompt: the PDF's pdftotext text, one free reply.
The probes are frozen (probes.json, frozen.sha256): the runner refuses to start if they changed.
"""
import hashlib
import json
import os
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

PAPERS = ROOT / "runs" / "new6"
PDFS = Path.home() / "Desktop" / "papers-new6"
TITLES = {
    "droplet": "Droplet entrainment and how to minimize it",
    "nutrisigma": "Impact of Nutrisigma on performance of young Garole lambs",
    "teak-pyrolysis": "Production of Medium-Grade Fuel from Pyrolysis of Teak Tree Leaves",
    "aspen-transest": "Development of an Aspen Plus model for catalytic transesterification with different reactor arrangements and kinetic mechanisms",
    "agave": "Genomic Potential and Climate Resilience of Agave angustifolia Haworth in Raicilla Production",
    "atlas-ttbar": "Measurement of lepton differential distributions and the top quark mass in ttbar production in pp collisions at sqrt(s) = 8 TeV with the ATLAS detector",
}
ARMS = {"hybrid": "llama-hybrid", "direct": "llama-direct"}
lock = threading.Lock()


def probes():
    frozen = (HERE / "frozen.sha256").read_text().split()[0]
    if hashlib.sha256((HERE / "probes.json").read_bytes()).hexdigest() != frozen:
        raise SystemExit("new6/probes.json changed since it was frozen")
    for paper, ps in json.loads((HERE / "probes.json").read_text())["papers"].items():
        for p in ps:
            yield paper, p


def paper_text(paper):
    """pdftotext of the PDF ugrc ingested (checked by hash), cached in text/."""
    man = json.loads((PAPERS / paper / "manifest.json").read_text())
    out = HERE / "text" / f"{paper}.txt"
    if not out.exists():
        pdf = PDFS / man["file"]
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != man["sha256"]:
            raise SystemExit(f"{pdf} is not the PDF ugrc ingested for {paper}")
        out.parent.mkdir(exist_ok=True)
        subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf), str(out)], check=True)
    text = out.read_text()
    return text, {"file": man["file"], "pages": man["pages"], "pdf_sha256": man["sha256"], "tool": "pdftotext",
                  "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "chars": len(text)}


_pages = {}


def pages_of(paper):
    with lock:
        if paper not in _pages:
            _pages[paper] = hybrid.pages(store.connect_question(PAPERS / paper))
        return _pages[paper]


def one(job):
    paper, p, arm, run = job
    out = HERE / "answers" / f"{ARMS[arm]}-r{run}"
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"{paper}-{p['id']}.json"
    if f.exists():
        return
    t = time.time()
    base = {"arm": ARMS[arm], "run": run, "paper": paper, "probe": p["id"], "cat": p["cat"], "question": p["q"],
            "expect": p["expect"], "trap": p.get("trap"), "must": p["must"], "model": hybrid.MODEL}
    if arm == "hybrid":
        con = store.connect_question(PAPERS / paper)
        rec = hybrid.answer(con, p["q"], pages_of(paper), title=TITLES[paper], way="leads")
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
    f.write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
    u = rec.get("usage") or {}
    with lock:
        print(f"done  {ARMS[arm]}-r{run} {paper}-{p['id']:3} prompt={u.get('prompt_tokens', '?'):>6} "
              f"{rec.get('finish_reason')} {time.time() - t:5.1f}s", flush=True)


def sizes():
    for paper in TITLES:
        pgs = pages_of(paper)
        rendered = sum(len(v["text"]) for v in pgs.values()) / 3.6
        text, _ = paper_text(paper)
        print(f"{paper:16} pages={len(pgs):3}  rendered≈{rendered / 1000:5.1f}k tok (budget {hybrid.BUDGET // 1000}k: "
              f"{'whole' if rendered <= hybrid.BUDGET else 'picked'})  pdftotext≈{len(text) / 3.6 / 1000:5.1f}k tok")


if __name__ == "__main__":
    if sys.argv[1:2] == ["sizes"]:
        sizes()
        sys.exit(0)
    if not hybrid.LLAMA_URL or not direct.URL:
        raise SystemExit("set LLAMA_URL (the server's /v1) and LLAMA_KEY")
    arg = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d  # noqa: E731
    arms = arg("--arms", "hybrid,direct").split(",")
    runs = [int(x) for x in arg("--runs", "1").split(",")]
    workers = int(arg("--workers", "6"))
    only = arg("--only", None)
    only = set(only.split(",")) if only else None
    papers = arg("--papers", None)
    papers = set(papers.split(",")) if papers else None
    # a question's arms and runs queue together, a paper's questions together (the server reuses the prefill)
    jobs = [(paper, p, a, r) for paper, p in probes() if (not only or f"{paper}-{p['id']}" in only)
            and (not papers or paper in papers) for r in runs for a in arms]
    print(f"{len(jobs)} answers: arms {arms}, runs {runs}, {workers} workers", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))
    print("all done", flush=True)
