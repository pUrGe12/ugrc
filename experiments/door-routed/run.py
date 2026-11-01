"""ugrc's door with the best setting (PLAN.md): search picks the paper, then Llama answers through the door, where it
never types a number: every number comes from a quote of a line or cell by id, a clause-base value by id (a measure
run), or a SQL query the machine runs. Two arms, on the fresh test's 80 questions and routes:

  door        the door as built, short prompt for a small model, Jev's leads with the question (bench-llama's
              llama-leads-sp, its best Llama arm): the model looks things up with the sql tool
  door-facts  the same door and prompt, with the routed paper's facts+prose form added to the question (the same
              sentences and tables the winning setup shows), each value followed by its measure id and each table
              cell and figure fact led by its atom id, so the model can point without searching

    python experiments/door-routed/run.py show ARM KEY
    python experiments/door-routed/run.py sizes
    LLAMA_URL=... LLAMA_KEY=... python experiments/door-routed/run.py answer ARM [--workers 8]    (run.sh wraps this)

One process per arm (door-facts replaces ask.question_message for its process). A question with no accepted answer
within MAX_TURNS is recorded with `accepted: false` and the error; nothing reaches the user, so it counts as not right.
No live judge (PLAN.md): Jev's credits ran out, so the judge passed to ask.ask always fails; a pairing the stored
clause base already gives still agrees by code, and every other is recorded `unchecked`. If the model server fails, nothing is recorded for that question and the run stops.
"""
import hashlib
import importlib.util
import json
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from ugrc import ask, jev, llm, store  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


FR = _load("fresh_run", ROOT / "experiments" / "fresh" / "run.py")
P, L, C = FR.P, FR.L, FR.C
ARMS = ("door", "door-facts")
MAX_TURNS = 20                 # as bench-llama's door arms
lock = threading.Lock()
stop = threading.Event()
GATE = ("no live judge: Jev's credits ran out (HTTP 402, 2026-11-01); a pairing the stored clause base gives agrees "
        "by code, every other is unchecked")


def no_judge(state, questions):
    """The pairing gate's judge for this run: always unavailable, so pairing.check records `unchecked`."""
    raise jev.JevError("no judge in this run: " + GATE)


def server_failed(e) -> bool:
    """The model server, not the model, failed (as bench-llama/run.py)."""
    import http.client
    import urllib.error
    return isinstance(e, (llm.ServerError, urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError))

HEAD = ("## The document, condensed\n"
        "Below is the document, condensed: page by page, the sentences that state a value and a few other sentences "
        "that best match the question, then its tables row by row and facts read from its figures. Each value in a "
        "sentence is followed by its measure id in braces, like 1,250 m^2/g {p4.L22:3#17}: to use that value, put the "
        "id in a measure run. Each table cell and figure fact starts with its id in brackets, like [p6.T2.r3c2]: to "
        "use a value from it, quote it exactly with that id as the atom. You need the sql tool only for what is not "
        "shown here.\n\n")


def with_ids(con, routed, question):
    """The winning setup's facts+prose form of `routed` for `question` (the same sentences, picked by prose.document
    on the same store), rendered with the ids the door accepts."""
    _, picked, _ = P.document(L.connect(routed), question)
    values = {sid for sid, role in con.execute("SELECT sentence, role FROM measures").fetchall() if role != "identifier"}
    keep = values | set(picked)
    marks = {}
    for mid, text, sid in con.execute("SELECT id, text, sentence FROM measures").fetchall():
        marks.setdefault(sid, []).append((int(mid.split("#")[1]), text, mid))
    rows = sorted(con.execute("SELECT id, page, text FROM sentences").fetchall(), key=lambda r: P.scaling.cr._order(r[0]))
    pages = {}
    for sid, page, text in rows:
        if sid not in keep:
            continue
        for off, val, mid in sorted(marks.get(sid, []), reverse=True):      # from the end, so offsets stay right
            end = off + len(val)
            text = text[:end] + f" {{{mid}}}" + text[end:]
        pages.setdefault(page, []).append(f"- {text}")
    q = lambda sql, args=(): con.execute(sql, list(args)).fetchall()  # noqa: E731
    heads = {}
    for tid, h in q("SELECT table_id, header FROM table_columns ORDER BY table_id, col_no"):
        heads.setdefault(tid, []).append(h or "")
    for tid, page, label, cap in q("SELECT id, page, label, caption FROM tables ORDER BY page, id"):
        out = pages.setdefault(page, [])
        out.append(f"{label or 'Table'}. {cap or ''}" + (f"\nColumns: {' | '.join(heads[tid])}" if tid in heads else ""))
        cells = {}
        for cid, r, t in q("SELECT id, row_no, text FROM cells WHERE table_id = ? ORDER BY row_no, col_no", [tid]):
            cells.setdefault(r, []).append(f"[{cid}] {t or ''}")
        out += [" | ".join(c) for _, c in sorted(cells.items())]
    for fid, page, label in q("SELECT id, page, label FROM figures WHERE label IS NOT NULL ORDER BY page, id"):
        for kid, st, v, u in q("SELECT id, statement, value, unit FROM figure_facts WHERE figure_id = ? ORDER BY fact_no", [fid]):
            pages.setdefault(page, []).append(f"[{kid}] ({label}, read from the image) {st}" + (f" ({v} {u or ''})" if v is not None else ""))
    return "\n\n".join(f"=== page {p} ===\n" + "\n".join(lines) for p, lines in sorted(pages.items()))


def use_facts(routes):
    """door-facts: the door's own question message (question, then Jev's leads), then the facts+prose form with ids."""
    own = ask.question_message

    def message(con, question):
        text, found = own(con, question)
        routed = routes[question]
        return text + "\n\n" + HEAD + with_ids(con, routed, question), found
    ask.question_message = message


def frozen():
    FR.install()
    C._check_frozen(ROOT / "experiments" / "fresh" / "frozen.sha256")
    C._check_frozen(HERE / "frozen.sha256")
    return FR.questions(), FR.routes()


def path(arm, key):
    _, p, pid = key.split("/")
    return HERE / "answers" / f"{arm}-r1" / f"{p}-{pid}.json"


def one(arm, key, q, r, client):
    f = path(arm, key)
    if f.exists() or stop.is_set():
        return
    t = time.time()
    root = FR.BL.SETS["fresh"]["runs"].parent / r["routed"]           # runs/<set>/<paper>
    base = {"arm": arm, "run": 1, "key": key, "paper": q["paper"], "probe": q["id"], "cat": q["cat"],
            "question": q["q"], "expect": q["expect"], "trap": q["trap"], "routed": r["routed"], "target": r["target"],
            "pairing_gate": GATE}
    try:
        rec = ask.ask(root, q["q"], model=llm_model(), cl=client, log=lambda *_: None, prompt="small", judge=no_judge)
        rec = dict(rec, **base, accepted=True, seconds=round(time.time() - t, 1))
    except Exception as e:
        if server_failed(e):
            stop.set()
            with lock:
                print(f"STOP  {arm:10} {key:32} the model server failed ({type(e).__name__}: {str(e)[:160]}); "
                      f"nothing recorded for this question", flush=True)
            return
        tried = getattr(e, "record", None) or {}
        rec = dict(base, accepted=False, rendered="", error=f"{type(e).__name__}: {e}"[:600],
                   turns=tried.get("turns"), tool_calls=tried.get("tool_calls"), usage=tried.get("usage"),
                   door_refusals=tried.get("door_refusals"), trace=tried.get("trace"),
                   traceback=traceback.format_exc()[-2000:], seconds=round(time.time() - t, 1))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
    with lock:
        print(f"done  {arm:10} {key:32} accepted={rec['accepted']!s:5} turns={rec.get('turns')} "
              f"refusals={len(rec.get('door_refusals') or [])} {time.time() - t:5.1f}s", flush=True)


def llm_model():
    import os
    return os.environ.get("LLAMA_MODEL", "llama-3.1-8b-instruct")


def answer(arm, workers):
    import os
    qs, rt = frozen()
    if arm == "door-facts":
        use_facts({q["q"]: rt[k]["routed"] for k, q in qs.items()})
    ask.MAX_TURNS = MAX_TURNS
    client = llm.OpenAIChat(os.environ["LLAMA_URL"], os.environ.get("LLAMA_KEY"), one_call_per_turn=True)
    print(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} {arm}: {len(qs)} questions", flush=True)
    keys = sorted(qs, key=lambda k: (rt[k]["routed"], k))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda k: one(arm, k, qs[k], rt[k], client), keys))
    print(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} {arm} " + ("STOPPED: the model server failed" if stop.is_set() else "end"),
          flush=True)


def first_message(arm, key):
    qs, rt = FR.questions(), FR.routes()
    q, r = qs[key], rt[key]
    root = FR.BL.SETS["fresh"]["runs"].parent / r["routed"]
    con = store.connect_question(root)
    try:
        text, _ = ask.question_message(con, q["q"])
        if arm == "door-facts":
            text += "\n\n" + HEAD + with_ids(con, r["routed"], q["q"])
        return ask.system_prompt(con, "small"), text
    finally:
        con.close()


def sizes():
    FR.install()
    for arm in ARMS:
        n = [sum(map(len, first_message(arm, k))) / 3.6 for k in FR.questions()]
        print(f"{arm:10} first prompt, tokens (chars / 3.6): mean {sum(n) / len(n):,.0f}, max {max(n):,.0f}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "show":
        FR.install()
        s, u = first_message(sys.argv[2], sys.argv[3])
        print(f"SYSTEM ({len(s):,} chars):\n{s[:1200]}\n...\n\nUSER ({len(u):,} chars):\n{u[:3000]}\n...\n{u[-1500:]}")
    elif cmd == "sizes":
        sizes()
    elif cmd == "answer":
        assert sys.argv[2] in ARMS
        answer(sys.argv[2], int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 8)
    else:
        raise SystemExit(__doc__)
