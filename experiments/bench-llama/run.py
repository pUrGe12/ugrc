"""Haiku against Llama 3.1 8B, on the two frozen probe sets (experiments/bench-leads: 88, bench-multistep: 66).

    ANTHROPIC_API_KEY=... python experiments/bench-llama/run.py haiku-plain [RUNS] [--workers N]
    LLAMA_KEY=... [LLAMA_URL=http://127.0.0.1:8090/v1] python experiments/bench-llama/run.py llama-plain [RUNS]
    (serve.sh starts a local Llama server; the leads arm also needs JEV_API_KEY for the pairing gate)

    Hosted, through OpenRouter, pinned to one host (no fallback to another, so precision cannot change mid-run):
    LLAMA_URL=https://openrouter.ai/api/v1 LLAMA_KEY="$OPENROUTER_API_KEY" \
    LLAMA_MODEL=meta-llama/llama-3.1-8b-instruct LLAMA_HOST=coreweave/bf16 python .../run.py llama-plain --workers 4

ARM is one of (or several, comma-separated, which then alternate question by question)
  haiku-plain   claude-haiku-5-5, the substrate alone (no clause base), under the current door
  haiku-leads   claude-haiku-5-5 with the clause base (leads, measure runs, the pairing gate): the 2x2's fourth cell
  llama-plain   Llama 3.1 8B Instruct (LLAMA_MODEL; default the local llama.cpp Q4_K_M), the substrate alone
  llama-leads   the same model with the clause base: leads with each question, measure runs, the pairing gate (Jev)
Llama records carry `llama_endpoint` (URL and pinned host) and `served_by` (turns per host, as the router named it).
Each answer goes to answers/<arm>-r<k>/<bench>/<paper>-<id>.json; a question with no accepted answer within
MAX_TURNS goes to the same name with .error.json (what the loop raised, how many turns). Answered probes are
skipped, so a run resumes.
"""
import hashlib
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

import os  # noqa: E402

from ugrc import ask, llm  # noqa: E402

BENCHES = ("bench-leads", "bench-multistep")
MAX_TURNS = 20             # Haiku never needed more than 13 on these benches; the same cap for every arm
LLAMA_URL = os.environ.get("LLAMA_URL", "http://127.0.0.1:8090/v1")
LLAMA_MODEL = os.environ.get("LLAMA_MODEL", "llama-3.1-8b-instruct-q4_k_m")
LLAMA_HOST = os.environ.get("LLAMA_HOST")     # an OpenRouter endpoint to pin, e.g. coreweave/bf16
ARMS = {"haiku-plain": ("claude-haiku-5-5", "plain", "full"),
        "haiku-leads": ("claude-haiku-5-5", "leads", "full"),
        "llama-plain": (LLAMA_MODEL, "plain", "full"),
        "llama-leads": (LLAMA_MODEL, "leads", "full"),
        # the same two Llama arms with the short prompt written for a small model (ask.SYSTEM_SMALL)
        "llama-plain-sp": (LLAMA_MODEL, "plain", "small"),
        "llama-leads-sp": (LLAMA_MODEL, "leads", "small"),
        # the same, on the 10-paper corpus (runs/papers-corpus) instead of the question's paper alone; the question
        # names its paper, as in direct.py --context (cai2026 is not in the corpus and is skipped)
        "llama-corpus-leads-sp": (LLAMA_MODEL, "corpus", "small")}
lock = threading.Lock()


def _get(block, key):
    return block.get(key) if isinstance(block, dict) else getattr(block, key, None)


def substrate(kind, paper):
    if kind == "corpus":
        return ROOT / "runs" / "papers-corpus"
    if kind == "leads":
        return ROOT / "runs" / "bench" / paper
    return ROOT / "runs" / ("cai2026" if paper == "cai2026" else f"papers/{paper}")


def probes():
    out = []
    for b in BENCHES:
        d = ROOT / "experiments" / b
        frozen = (d / "frozen.sha256").read_text().split()[0]
        if hashlib.sha256((d / "probes.json").read_bytes()).hexdigest() != frozen:
            raise SystemExit(f"{b}/probes.json changed since it was frozen")
        for paper, ps in json.loads((d / "probes.json").read_text())["papers"].items():
            out += [(b, paper, p) for p in ps]
    return out


def log(msg):
    with lock:
        print(msg, flush=True)


class ServerDown(Exception):
    pass


stop = threading.Event()


def _server_failed(e) -> bool:
    """The model server, not the model, failed: no record is written and the run stops."""
    import http.client
    import urllib.error
    return isinstance(e, (llm.ServerError, urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError))


def one(job):
    arm, k, bench, paper, probe, client = job
    if stop.is_set():
        return
    model, kind, prompt = ARMS[arm]
    out = HERE / "answers" / f"{arm}-r{k}" / bench
    out.mkdir(parents=True, exist_ok=True)
    name = f"{paper}-{probe['id']}"
    if (out / f"{name}.json").exists() or (out / f"{name}.error.json").exists():
        return
    t = time.time()
    try:
        q = probe["q"]
        if kind == "corpus":
            from direct import TITLES
            q = f'About the document "{TITLES[paper]}" ({paper}): {q}'
        rec = ask.ask(substrate(kind, paper), q, model=model, cl=client, log=lambda *_: None, prompt=prompt)
        rec = dict(rec, arm=arm, run=k, bench=bench, paper=paper, probe=probe["id"], cat=probe["cat"],
                   expect=probe["expect"], trap=probe.get("trap"), seconds=round(time.time() - t, 1))
        if arm.startswith("llama"):
            rec["llama_endpoint"] = {"url": LLAMA_URL, "host": LLAMA_HOST}
        (out / f"{name}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
        log(f"done  {arm}-r{k} {bench:15} {name:24} turns={rec['turns']} tools={rec['tool_calls']} "
            f"refusals={len(rec['door_refusals'])} {time.time() - t:.0f}s")
    except Exception as e:
        if _server_failed(e):
            stop.set()
            log(f"STOP  {arm}-r{k} {bench:15} {name:24} the model server failed ({type(e).__name__}: {str(e)[:160]}); "
                f"nothing recorded for this question")
            return
        tried = getattr(e, "record", None) or {}
        sent = [_get(b, "input") for m in getattr(e, "messages", []) if m["role"] == "assistant"
                for b in m["content"] if _get(b, "type") == "tool_use" and _get(b, "name") == "submit_answer"]
        (out / f"{name}.error.json").write_text(json.dumps({
            "arm": arm, "run": k, "bench": bench, "paper": paper, "probe": probe["id"], "cat": probe["cat"],
            "error": f"{type(e).__name__}: {e}", "seconds": round(time.time() - t, 1), "model": model,
            "llama_endpoint": {"url": LLAMA_URL, "host": LLAMA_HOST} if arm.startswith("llama") else None,
            "served_by": tried.get("served_by"), "adapter_repairs": tried.get("adapter_repairs"),
            "turns": tried.get("turns"), "tool_calls": tried.get("tool_calls"), "usage": tried.get("usage"),
            "trace": tried.get("trace"), "door_refusals": tried.get("door_refusals"), "submitted": sent,
            "traceback": traceback.format_exc()}, indent=2, ensure_ascii=False, default=str))
        log(f"FAIL  {arm}-r{k} {bench:15} {name:24} {type(e).__name__}: {str(e)[:120]} {time.time() - t:.0f}s")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--") and not (sys.argv[sys.argv.index(a) - 1] in ("--workers", "--only"))]
    arms, runs = args[0].split(","), int(args[1]) if len(args) > 1 else 1
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else \
        (8 if all(a.startswith("haiku") for a in arms) else 1)
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
    ask.MAX_TURNS = MAX_TURNS
    clients = {}
    for arm in arms:
        if arm.startswith("llama"):
            pin = {"provider": {"only": [LLAMA_HOST], "allow_fallbacks": False, "require_parameters": True}} if LLAMA_HOST else None
            clients[arm] = llm.OpenAIChat(LLAMA_URL, os.environ.get("LLAMA_KEY"), extra=pin, one_call_per_turn=True)
        else:
            import anthropic
            clients[arm] = anthropic.Anthropic()
    # several arms alternate question by question, so their comparison fills in as the run goes
    jobs = [(arm, k, b, paper, p, clients[arm]) for k in range(1, runs + 1) for b, paper, p in probes()
            if not only or f"{b}/{paper}-{p['id']}" in only for arm in arms
            if not (ARMS[arm][1] == "corpus" and paper == "cai2026")]
    log(f"{len(jobs)} questions, arm(s) {', '.join(f'{a} ({ARMS[a][0]})' for a in arms)}, {workers} worker(s), "
        f"max {MAX_TURNS} turns")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))
    log("stopped: the model server failed" if stop.is_set() else "all done")
