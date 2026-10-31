"""Fetch close-topic ChemE papers for the big library: for each of cheme2's 20 topics, the next papers of cheme2's own
search hits (cheme2/candidates.json, in their recorded order) that pass cheme2's filters 1-4, skipping every paper of
cheme and cheme2. These papers get no questions; they make routing harder.

    python experiments/big-library/fetch.py [PER_TOPIC]        default 2
Writes ~/Desktop/papers-cheme3/<topic key>-<n>.pdf and cheme3.json (every candidate looked at and its verdict).
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location("cheme2_fetch", ROOT / "experiments" / "cheme2" / "fetch.py")
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)

DEST = Path.home() / "Desktop" / "papers-cheme3"
PER = int(sys.argv[1]) if len(sys.argv) > 1 else 2
CACHE = HERE / "fetch-cache.json"     # pmcid -> verdict and facts, so a rerun after a network error resumes
USED = F.EARLIER | {v["pmcid"] for v in json.loads((ROOT / "experiments" / "cheme2" / "papers.json").read_text()).values()}


def seed_from_log():
    """Papers chosen by an earlier, interrupted run (fetch.log lines '<key> <pmcid> <n>p <title>'): {pmcid: file}."""
    out = {}
    log = HERE / "fetch.log"
    for line in (log.read_text().splitlines() if log.exists() else []):
        parts = line.split()
        if len(parts) > 2 and parts[1].startswith("PMC") and (DEST / f"{parts[0]}.pdf").exists():
            out[parts[1]] = DEST / f"{parts[0]}.pdf"
    return out


def check(pmcid, cache, seeded):
    """F.check with a cache and up to 3 tries; a candidate that never downloads is skipped as 'download failed'."""
    if pmcid in cache and cache[pmcid]["verdict"] != "chosen":
        return cache[pmcid]["verdict"], None, cache[pmcid]["facts"]
    if pmcid in seeded:
        data = seeded[pmcid].read_bytes()
        info = F.subprocess.run(["pdfinfo", str(seeded[pmcid])], capture_output=True, text=True).stdout
        pages = int(next((ln.split()[-1] for ln in info.splitlines() if ln.startswith("Pages:")), "0"))
        facts = {"s3_key": F.pdf_key(pmcid), "pages": pages, "bytes": len(data), "from": "earlier run"}
        return "chosen", data, facts
    for attempt in range(3):
        try:
            verdict, data, facts = F.check(pmcid)
            break
        except OSError as e:                       # timeouts and connection resets
            print(f"   {pmcid}: {type(e).__name__} on try {attempt + 1}", flush=True)
            time.sleep(10)
    else:
        verdict, data, facts = "download failed", None, {}
    cache[pmcid] = {"verdict": verdict, "facts": facts}
    CACHE.write_text(json.dumps(cache, indent=1))
    return verdict, data, facts


def main():
    DEST.mkdir(exist_ok=True)
    cands = json.loads((ROOT / "experiments" / "cheme2" / "candidates.json").read_text())
    chosen, looked, taken = {}, {}, set()
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    seeded = seed_from_log()
    for topic, rows in cands.items():
        key = topic.lower().replace(" ", "-")
        n = 0
        looked[topic] = []
        for r in rows:
            if n >= PER:
                break
            pmcid = r.get("pmcid")
            if not pmcid or pmcid in USED or pmcid in taken:
                continue
            if r.get("verdict") not in ("not reached", "chosen"):   # failed a filter in cheme2: same verdict now
                continue
            verdict, data, facts = check(pmcid, cache, seeded)
            row = {k: r.get(k) for k in ("pmcid", "title", "journal", "year", "doi")} | facts | {"verdict": verdict}
            looked[topic].append(row)
            if pmcid not in seeded:
                time.sleep(1)
            if data:
                n += 1
                k = f"{key}-{n}"
                (DEST / f"{k}.pdf").write_bytes(data)
                chosen[k] = row
                taken.add(pmcid)
                print(f"{k:24} {pmcid} {row['pages']:>3}p {str(row['title'])[:70]}", flush=True)
        if n < PER:
            print(f"{key:24} only {n} found", flush=True)
    (HERE / "cheme3-candidates.json").write_text(json.dumps(looked, indent=1, ensure_ascii=False))
    (HERE / "cheme3.json").write_text(json.dumps(chosen, indent=1, ensure_ascii=False))
    print(f"{len(chosen)} papers")


if __name__ == "__main__":
    main()
