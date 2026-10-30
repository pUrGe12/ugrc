"""Do we need Jev, or ugrc, for the condensed form? (PLAN.md) Llama 3.1 8B at the 10-paper library.

    LLAMA_URL=<server>/v1 LLAMA_KEY=... python experiments/scaling-nojev/run.py [--arms code,pdf] [--workers 6]

Same questions, documents, order, slot, prompt and sampling as llama-scale-facts-L10 (experiments/scaling); only the
form differs (forms.py). Answers go to experiments/bench-llama/answers/llama-scale-<form>-L10-r1/; a record that exists
is skipped, so a run resumes.
"""
import hashlib
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import forms  # noqa: E402

scaling, direct, cr = forms.scaling, forms.direct, forms.scaling.cr
ROOT = forms.ROOT
OUT = ROOT / "experiments" / "bench-llama" / "answers"
ARMS = {"code": "llama-scale-code-L10", "pdf": "llama-scale-pdf-L10"}
FORM = {
    "code": scaling.FORM["facts"],
    "pdf": ("It is below{among}, condensed: page by page, the sentences of its text, extracted from the PDF, that "
            "contain a digit (other sentences are left out)."),
}
lock = threading.Lock()


def frozen():
    for line in (HERE / "frozen.sha256").read_text().splitlines():
        if len(line.split()) != 2:
            continue
        digest, name = line.split()
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != digest:
            raise SystemExit(f"scaling-nojev/{name} changed since it was frozen")
    keys, lib = scaling.frozen()                 # the scaling test's own freeze is checked too
    return keys, lib


def main(forms_wanted, workers):
    import run as bench                          # bench-llama/run.py: probes()
    keys, lib = frozen()
    docs_of = lib["documents"]["llama-scale-facts-L10"]
    probes = {f"{b}/{paper}-{p['id']}": (b, paper, p) for b, paper, p in bench.probes()}
    doc = {(p, f): forms.FORMS[f](p) for p in scaling.CORPUS for f in forms_wanted}
    nums = {p: cr.printed_numbers(scaling.connect(p)) for p in scaling.CORPUS}
    jobs = [(f, k) for f in forms_wanted for paper in scaling.CORPUS for k in keys if probes[k][1] == paper]

    def one(job):
        f, k = job
        b, paper, p = probes[k]
        out = OUT / f"{ARMS[f]}-r1" / b / f"{paper}-{p['id']}.json"
        if out.exists():
            return
        t = time.time()
        docs = docs_of[paper]
        system = scaling.SYSTEM.format(title=direct.TITLES[paper],
                                       form=FORM[f].format(among=f" among {len(docs)} documents"))
        body = "\n\n".join(f'<document title="{direct.TITLES[d]}">\n{doc[(d, f)]}\n</document>' for d in docs)
        user = f'{body}\n\nQuestion (about "{direct.TITLES[paper]}"): {p["q"]}'
        resp = cr.chat(system, user)
        text = resp["choices"][0]["message"].get("content") or ""
        rec = {"arm": ARMS[f], "run": 1, "bench": b, "paper": paper, "probe": p["id"], "cat": p["cat"],
               "expect": p["expect"], "trap": p.get("trap"), "question": p["q"], "model": scaling.MODEL,
               "rendered": text, "finish_reason": resp["choices"][0].get("finish_reason"), "usage": resp.get("usage"),
               "turns": 1, "tool_calls": 0, "door_refusals": [], "citations": [], "runs": [], "trace": [],
               "numbers_not_in_paper": sorted({cr._n(x) for x in cr.NUM.findall(text)} - nums[paper] - {""}),
               "library": {"form": f, "level": 10, "documents": docs, "target_slot": docs.index(paper)},
               "prompt": {"style": f"scaling-nojev:{f}", "system": system,
                          "user_sha256": hashlib.sha256(user.encode()).hexdigest(), "user_chars": len(user)},
               "sampling": {"temperature": cr.llm.TEMPERATURE, "top_p": cr.llm.TOP_P, "max_tokens": cr.llm.MAX_OUTPUT},
               "seconds": round(time.time() - t, 1)}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
        with lock:
            print(f"done  {ARMS[f]:22} {k:40} {rec['usage'].get('prompt_tokens') if rec['usage'] else '?':>7} tok "
                  f"{time.time() - t:4.0f}s", flush=True)

    print(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} start: {len(jobs)} jobs", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))
    print(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} end", flush=True)


if __name__ == "__main__":
    wanted = sys.argv[sys.argv.index("--arms") + 1].split(",") if "--arms" in sys.argv else list(ARMS)
    assert set(wanted) <= set(ARMS), wanted
    main(wanted, int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 6)
