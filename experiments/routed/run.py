"""The routed test (PLAN.md): keyword search picks one paper from the question's 10-paper library, then Llama 3.1 8B
answers with that one paper in view, in the one-paper prompts of the earlier tests. The question does not name its paper.

    python experiments/routed/run.py route               no model: routes.json (the paper each question is sent to)
    python experiments/routed/run.py sizes               no model: prompt sizes per arm
    python experiments/routed/run.py show ARM KEY        no model: the prompt one question gets
    LLAMA_URL=<server>/v1 LLAMA_KEY=... python experiments/routed/run.py answer [--arms prose,pdf] [--workers 8]

Questions, libraries and pdftotext pages are the library test's (experiments/library, frozen there).
Router: every pdftotext page of the library's 10 papers, headed by its title (the library test's pages arm), ranked by
the hybrid's BM25 on the question; the question goes to the paper of the top-ranked page.
Arms (answers/<arm>-r1/<set>__<paper>-<id>.json; a record that exists is skipped, so a run resumes):
  prose  the routed paper in the facts+prose form: prose/run.py's document() and prompt(), as cheme2's prose arm.
  pdf    the routed paper's pdftotext with bench-llama/direct.py's prompt, as cheme2's pdf arm.
"""
import hashlib
import importlib.util
import json
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


L = _load("library_run", ROOT / "experiments" / "library" / "run.py")   # questions, libraries, pages, titles
P, C = L.P, L.C
scaling, hybrid, llm, direct = L.scaling, L.hybrid, L.llm, C.direct
C.TITLES.update(L.TITLES)       # prose's prompt() looks the title up here; set-qualified ids, so no name clashes
ARMS = ("prose", "pdf")
ROUTES = HERE / "routes.json"
lock = threading.Lock()


def log(msg):
    with lock:
        print(msg, flush=True)


def library_questions():
    return (json.loads((L.HERE / "questions.json").read_text())["questions"],
            json.loads((L.HERE / "libraries.json").read_text())["libraries"])


# ---------------------------------------------------------------- route (no model)

def route_one(question, docs):
    pages = {(d, n): f"=== {L.TITLES[d]}, page {n} ===\n{body}" for d in docs for n, body in L.text_pages(d).items()}
    ranked = list(hybrid.bm25(question, pages))
    order = []
    for d, _ in ranked:
        if d not in order:
            order.append(d)
    return {"routed": ranked[0][0], "top_page": list(ranked[0]), "paper_order": order}


def route():
    qs, libs = library_questions()
    out, right = {}, 0
    for key, q in qs.items():
        r = route_one(q["q"], libs[q["library"]]["documents"])
        target = f"{q['set']}/{q['paper']}"
        out[key] = {"target": target, **r, "routed_right": r["routed"] == target}
        right += r["routed"] == target
    ROUTES.write_text(json.dumps({"about": "run.py route: the paper of the top BM25 page among the library's 10 papers",
                                  "routes": out}, indent=1) + "\n")
    print(f"{right} of {len(out)} questions routed to their own paper")
    for key, r in out.items():
        if not r["routed_right"]:
            print(f"  {key}: routed to {r['routed']}; its own paper ranks {r['paper_order'].index(r['target']) + 1}")


# ---------------------------------------------------------------- prompts

def prompt(arm, q, routed):
    """(system, user, extra) for one question sent to the paper `routed`."""
    if arm == "prose":
        doc, picked, used = P.document(L.connect(routed), q)
        system, user = P.prompt(routed, q, doc)
        return system, user, {"added": {"sentences": picked, "chars": used},
                              "document": {"form": "facts+prose", "chars": len(doc),
                                           "sha256": hashlib.sha256(doc.encode()).hexdigest()}}
    s, paper = routed.split("/")
    man = json.loads((L.SETS[s]["runs"] / paper / "manifest.json").read_text())
    text = L.paper_text(routed)
    system = direct.SYSTEM.format(file=man["file"], pages=man["pages"])
    return system, f"<document>\n{text}\n</document>\n\nQuestion: {q}", {
        "source": {"file": man["file"], "pages": man["pages"], "tool": "pdftotext", "chars": len(text),
                   "text_sha256": hashlib.sha256(text.encode()).hexdigest()}}


# ---------------------------------------------------------------- answering

def frozen():
    qs, _ = L.frozen()                                   # the library test's questions, still as frozen there
    C._check_frozen(HERE / "frozen.sha256")
    return qs, json.loads(ROUTES.read_text())["routes"]


def answer_path(arm, key):
    s, paper, pid = key.split("/")
    return HERE / "answers" / f"{arm}-r1" / f"{s}__{paper}-{pid}.json"


def one(arm, key, q, r):
    f = answer_path(arm, key)
    if f.exists():
        return
    t = time.time()
    routed = r["routed"]
    system, user, extra = prompt(arm, q["q"], routed)
    resp = (scaling.cr.chat if arm == "prose" else direct.chat)(system, user)
    choice = resp["choices"][0]
    text = choice["message"].get("content") or ""
    rec = {"arm": arm, "run": 1, "key": key, "library": q["library"], "set": q["set"], "paper": q["paper"],
           "probe": q["id"], "cat": q["cat"], "question": q["q"], "expect": q["expect"], "trap": q["trap"],
           "must": q["must"], "model": scaling.cr.MODEL, "rendered": text, "finish_reason": choice.get("finish_reason"),
           "routed": routed, "target": r["target"], "target_shown": routed == r["target"], "top_page": r["top_page"],
           "numbers_not_in_paper": sorted({scaling.cr._n(x) for x in scaling.cr.NUM.findall(text)}
                                          - L.numbers(routed) - {""}),
           **extra,
           "prompt": {"style": f"routed:{arm}", "system": system, "user_chars": len(user),
                      "user_sha256": hashlib.sha256(user.encode()).hexdigest()},
           "usage": resp.get("usage"),
           "sampling": {"temperature": llm.TEMPERATURE, "top_p": llm.TOP_P, "max_tokens": llm.MAX_OUTPUT},
           "seconds": round(time.time() - t, 1)}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
    u = rec["usage"] or {}
    log(f"done  {arm:5} {key:36} prompt={u.get('prompt_tokens', '?'):>6} routed_right={rec['target_shown']!s:5} "
        f"{rec['finish_reason']} {time.time() - t:5.1f}s")


def answer(arms, workers):
    if not scaling.cr.URL:
        raise SystemExit("set LLAMA_URL (the server's /v1) and LLAMA_KEY")
    qs, routes = frozen()
    log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} start: arms {arms}")
    keys = sorted(qs, key=lambda k: (routes[k]["routed"], k))     # by routed paper, so the pdf arm's prefill is shared
    for arm in arms:
        todo = [k for k in keys if not answer_path(arm, k).exists()]
        log(f"-- {arm}: {len(todo)} questions")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda k: one(arm, k, qs[k], routes[k]), todo))
    log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} end")


def sizes():
    qs, _ = library_questions()
    routes = json.loads(ROUTES.read_text())["routes"]
    for arm in ARMS:
        n = []
        for k, q in qs.items():
            system, user, _ = prompt(arm, q["q"], routes[k]["routed"])
            n.append((len(system) + len(user)) / 3.6)
        print(f"{arm:5} prompt tokens (chars / 3.6): mean {sum(n) / len(n):,.0f}, max {max(n):,.0f}")


def show(arm, key):
    qs, _ = library_questions()
    routes = json.loads(ROUTES.read_text())["routes"]
    system, user, _ = prompt(arm, qs[key]["q"], routes[key]["routed"])
    print(f"SYSTEM: {system}\n\nUSER ({len(user):,} chars):\n{user[:1500]}\n...\n{user[-600:]}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "route":
        route()
    elif cmd == "sizes":
        sizes()
    elif cmd == "show":
        show(sys.argv[2], sys.argv[3])
    elif cmd == "answer":
        a = sys.argv[sys.argv.index("--arms") + 1].split(",") if "--arms" in sys.argv else list(ARMS)
        assert set(a) <= set(ARMS), a
        answer(a, int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 8)
    else:
        raise SystemExit(__doc__)
