"""The baseline with no ugrc at all: the model gets the PDF's text in its prompt and answers the question in one
reply. No tools, no door, no clause base. Same 154 frozen questions, same model server, same sampling as the
Llama arms (ugrc.llm TEMPERATURE / TOP_P / MAX_OUTPUT).

    LLAMA_URL=https://.../v1 LLAMA_KEY=... python experiments/bench-llama/direct.py [--workers N] [--only b/paper-id,...]

The text is `pdftotext` (poppler, default reading order) of each paper's original PDF, checked against the
sha256 ugrc recorded at ingest; it is saved in direct-text/<paper>.txt and its hash goes in every record.
Tables come out flattened column by column, as any plain PDF-to-text pass gives them. A text-only model sees no
figures here either.

Answers go to answers/llama-direct-r1/<bench>/<paper>-<id>.json in the shape grade.py reads (rendered, turns,
tool_calls, door_refusals, citations, runs). Each record also lists the numbers in its answer that occur nowhere
in the paper's text (`numbers_not_in_text`): typed by the model, either computed or invented.

    --context N   the length test: the question's paper among other bench papers, up to about N tokens of
                  documents in all (arm llama-direct-ctx<N/1000>k). Each paper is wrapped in <document title=...>;
                  the question names its paper's title. The other papers and the target's slot are drawn by a
                  seed made from the paper's key (the same draw at every level, and for every question on that
                  paper, whose jobs run together so the server reuses the prefill). A target longer than N stands
                  alone.
"""
import hashlib
import json
import os
import re
import subprocess
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
from ugrc import llm  # noqa: E402

import run as bench  # noqa: E402  (probes(), BENCHES)

ARM = "llama-direct"
URL = os.environ.get("LLAMA_URL", "").rstrip("/")
KEY = os.environ.get("LLAMA_KEY")
MODEL = os.environ.get("LLAMA_MODEL", "llama-3.1-8b-instruct")
PDF_DIRS = (Path.home() / "Desktop/papers", Path.home() / "Downloads")
SYSTEM = ('You answer questions about one document, "{file}" ({pages} pages), using only what the document '
          "contains. Its text, extracted from the PDF, is below. If the document does not hold what the question "
          "asks, say so.")
SYSTEM_MANY = ('You answer questions about one document, "{title}", using only what that document contains. Its '
               "text, extracted from the PDF, is below among {n} documents. If that document does not hold what "
               "the question asks, say so.")
TITLES = {"acsnano-7b02404": "Tunable Mechanochemistry of Lithium Battery Electrodes",
          "adma-2020": "Lithium Iron Aluminum Nickelate, LiNixFeyAlzO2—New Sustainable Cathodes for Next-Generation Cobalt-Free Li-Ion Batteries",
          "aenm-2022": "Next-Generation Cobalt-Free Cathodes – A Prospective Solution to the Battery Industry's Cobalt Problem",
          "cssc-2020": "Sustainable Direct Recycling of Lithium-Ion Batteries via Solvent Recovery of Electrode Materials",
          "ensm-2020": "Perspectives on the relationship between materials chemistry and roll-to-roll electrode manufacturing for high-energy lithium-ion batteries",
          "ensm-2021": "Valuation of Surface Coatings in High-Energy Density Lithium-ion Battery Cathode Materials",
          "mattod-2020": "Energy and environmental aspects in recycling lithium-ion batteries: Concept of Battery Identity Global Passport",
          "nanolett-6b05172": "A Sugar-Derived Room-Temperature Sodium Sulfur Battery with Long Term Cycling Stability",
          "nanolett-6b05174": "Anode-Free Sodium Battery through in Situ Plating of Sodium Metal",
          "susmat-2020": "Sustainable recycling of cathode scraps via Cyrene-based separation",
          "cai2026": "Engineered nanomaterials for siRNA therapy against tumor metastasis"}
CONTEXT = int(sys.argv[sys.argv.index("--context") + 1]) if "--context" in sys.argv else None
if CONTEXT:
    ARM = f"llama-direct-ctx{CONTEXT // 1000}k"
lock = threading.Lock()
_tokens = {}


def paper_tokens(paper: str) -> int:
    """The paper's length in the model's tokens: /tokenize on the server, once per paper."""
    if paper not in _tokens:
        text, _ = paper_text(paper)
        req = urllib.request.Request(URL.removesuffix("/v1") + "/tokenize", data=json.dumps(
            {"model": MODEL, "prompt": text}).encode(), headers={"Content-Type": "application/json",
                                                                 **({"Authorization": f"Bearer {KEY}"} if KEY else {})})
        with urllib.request.urlopen(req, timeout=120) as r:
            _tokens[paper] = json.loads(r.read())["count"]
    return _tokens[paper]


def documents_for(paper: str) -> list[str]:
    """The question's paper plus other bench papers, in an order seeded by the paper, up to CONTEXT tokens. Every
    question on a paper gets the same documents, so the server reuses their prefill (vLLM prefix caching)."""
    import random
    rng = random.Random(f"{paper}-context")
    others = [p for p in TITLES if p != paper]
    rng.shuffle(others)
    chosen, total = [paper], paper_tokens(paper)
    for p in others:
        if total + paper_tokens(p) <= CONTEXT:
            chosen.append(p)
            total += paper_tokens(p)
    rest = chosen[1:]
    rest.insert(rng.randrange(len(rest) + 1), paper)
    return rest


def paper_text(paper: str) -> tuple[str, dict]:
    man = json.loads((ROOT / ("runs/cai2026" if paper == "cai2026" else f"runs/papers/{paper}") / "manifest.json").read_text())
    out = HERE / "direct-text" / f"{paper}.txt"
    if not out.exists():
        pdf = next(d / man["file"] for d in PDF_DIRS if (d / man["file"]).exists())
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != man["sha256"]:
            raise SystemExit(f"{pdf} is not the PDF ugrc ingested for {paper}")
        out.parent.mkdir(exist_ok=True)
        subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf), str(out)], check=True)
    text = out.read_text()
    return text, {"file": man["file"], "pages": man["pages"], "pdf_sha256": man["sha256"], "tool": "pdftotext",
                  "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "chars": len(text)}


NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(s: str) -> set[str]:
    return {n.replace(",", "") for n in NUM.findall(s)}


def numbers_not_in_text(answer: str, text: str) -> list[str]:
    """Numbers of two or more digits (or with a decimal point) in the answer that occur nowhere in the text."""
    have = _numbers(text.replace(" ", "").replace(" ", " "))
    return sorted(n for n in _numbers(answer) if (len(n) > 1 or "." in n) and n not in have)


def chat(system: str, user: str) -> dict:
    body = json.dumps({"model": MODEL, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                       "max_tokens": llm.MAX_OUTPUT, "temperature": llm.TEMPERATURE, "top_p": llm.TOP_P}).encode()
    for attempt in range(llm.RETRIES + 1):
        req = urllib.request.Request(f"{URL}/chat/completions", data=body, headers={
            "Content-Type": "application/json", **({"Authorization": f"Bearer {KEY}"} if KEY else {})})
        try:
            with urllib.request.urlopen(req, timeout=llm.TIMEOUT_S) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code not in llm.RETRY_CODES or attempt == llm.RETRIES:
                raise llm.ServerError(f"HTTP {e.code}: {e.read()[:300]!r}") from e
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            if attempt == llm.RETRIES:
                raise llm.ServerError(str(e)) from e
        time.sleep(min(2 ** attempt, 60))


def one(job):
    bench_name, paper, probe = job
    out = HERE / "answers" / f"{ARM}-r1" / bench_name
    out.mkdir(parents=True, exist_ok=True)
    name = f"{paper}-{probe['id']}"
    if (out / f"{name}.json").exists():
        return
    text, source = paper_text(paper)
    t = time.time()
    if CONTEXT:
        docs = documents_for(paper)
        body = "\n\n".join(f'<document title="{TITLES[d]}">\n{paper_text(d)[0]}\n</document>' for d in docs)
        source = dict(source, documents=docs, target_slot=docs.index(paper), context_budget=CONTEXT,
                      document_tokens=sum(paper_tokens(d) for d in docs))
        resp = chat(SYSTEM_MANY.format(title=TITLES[paper], n=len(docs)),
                    f'{body}\n\nQuestion (about "{TITLES[paper]}"): {probe["q"]}')
    else:
        resp = chat(SYSTEM.format(file=source["file"], pages=source["pages"]),
                    f"<document>\n{text}\n</document>\n\nQuestion: {probe['q']}")
    choice = resp["choices"][0]
    answer = choice["message"].get("content") or ""
    rec = {"question": probe["q"], "model": MODEL, "arm": ARM, "run": 1, "bench": bench_name, "paper": paper,
           "probe": probe["id"], "cat": probe["cat"], "expect": probe["expect"], "trap": probe.get("trap"),
           "rendered": answer, "finish_reason": choice.get("finish_reason"), "turns": 1, "tool_calls": 0,
           "door_refusals": [], "citations": [], "runs": [], "trace": [], "adapter_repairs": [],
           "numbers_not_in_text": numbers_not_in_text(answer, text), "source": source,
           "prompt": {"style": "direct-many" if CONTEXT else "direct", "system": SYSTEM_MANY if CONTEXT else SYSTEM},
           "sampling": {"temperature": llm.TEMPERATURE, "top_p": llm.TOP_P, "max_tokens": llm.MAX_OUTPUT},
           "usage": resp.get("usage"), "llama_endpoint": {"url": URL}, "seconds": round(time.time() - t, 1)}
    (out / f"{name}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    with lock:
        print(f"done  {bench_name:15} {name:24} {rec['usage'].get('prompt_tokens') if rec['usage'] else '?':>6} in "
              f"{time.time() - t:5.1f}s  invented?={rec['numbers_not_in_text'][:4]}", flush=True)


if __name__ == "__main__":
    if not URL:
        raise SystemExit("set LLAMA_URL (the server's /v1)")
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 6
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
    jobs = [(b, paper, p) for b, paper, p in bench.probes() if not only or f"{b}/{paper}-{p['id']}" in only]
    if CONTEXT:
        jobs.sort(key=lambda j: j[1])   # a paper's questions together: one prefill of its documents
    print(f"{len(jobs)} questions, {ARM} ({MODEL}), {workers} workers", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))
    print("all done", flush=True)
