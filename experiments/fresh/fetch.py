"""Choose and fetch the fresh papers (PLAN.md, "The papers"): cheme2's search re-run today, newest first, for cheme2's
20 topics in an order drawn by the seed "fresh-paper"; per topic the newest hit that is in none of the 120 library
papers' sets (cheme, cheme2, cheme3) and passes cheme2's filters 1-4 (5-25 pages, at least 15,000 characters of text,
a line starting "Table 1"); stop at 10 papers. Filter 5 (ingest and clause base) is prepare.sh; a paper that fails it
is replaced by running this again with --skip PMCID.

    python experiments/fresh/fetch.py [--skip PMCID,...]
Writes ~/Desktop/papers-fresh/<topic key>.pdf, candidates.json (every hit looked at and its verdict) and papers.json.
"""
import importlib.util
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location("cheme2_fetch", ROOT / "experiments" / "cheme2" / "fetch.py")
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)

DEST = Path.home() / "Desktop" / "papers-fresh"
WANT = 10
SEED = "fresh-paper"
LIBRARY = (F.EARLIER
           | {v["pmcid"] for v in json.loads((ROOT / "experiments" / "cheme2" / "papers.json").read_text()).values()}
           | {v["pmcid"] for v in json.loads((ROOT / "experiments" / "big-library" / "cheme3.json").read_text()).values()})
# Hits the big library's fetch already downloaded and rejected by the same filters: same verdict now, no download.
KNOWN = {k: v["verdict"] for k, v in json.loads((ROOT / "experiments" / "big-library" / "fetch-cache.json")
                                                .read_text()).items() if v["verdict"] != "chosen"}


def main():
    skip = set(sys.argv[sys.argv.index("--skip") + 1].split(",")) if "--skip" in sys.argv else set()
    DEST.mkdir(exist_ok=True)
    order = random.Random(SEED).sample(F.TOPICS, len(F.TOPICS))
    looked, chosen, taken = {}, {}, set()
    for topic in order:
        if len(chosen) >= WANT:
            break
        key = topic.lower().replace(" ", "-")
        looked[topic] = []
        for r in F.search(topic):
            pmcid = r.get("pmcid")
            row = {"pmcid": pmcid, "title": r.get("title"), "journal": r.get("journalTitle"), "year": r.get("pubYear"),
                   "doi": r.get("doi"), "published": r.get("firstPublicationDate")}
            if not pmcid:
                row["verdict"] = "no PMC id"
            elif pmcid in LIBRARY:
                row["verdict"] = "already in the library"
            elif pmcid in taken:
                row["verdict"] = "taken for an earlier topic"
            elif pmcid in skip:
                row["verdict"] = "failed ingest or clause base (filter 5)"
            elif pmcid in KNOWN:
                row["verdict"] = KNOWN[pmcid] + " (big-library fetch)"
            else:
                verdict, data, facts = F.check(pmcid)
                row |= facts | {"verdict": verdict}
                time.sleep(1)
                if data:
                    (DEST / f"{key}.pdf").write_bytes(data)
                    chosen[key] = {k: v for k, v in row.items() if k != "verdict"} | {"topic": topic}
                    taken.add(pmcid)
                    looked[topic].append(row)
                    print(f"{key:22} {pmcid} {row['pages']:>3}p {row['published']} {str(row['title'])[:70]}", flush=True)
                    break
            looked[topic].append(row)
        else:
            print(f"{key:22} no eligible paper", flush=True)
    (HERE / "candidates.json").write_text(json.dumps({"order": order, "looked": looked}, indent=1, ensure_ascii=False))
    (HERE / "papers.json").write_text(json.dumps(chosen, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(chosen)} papers")


if __name__ == "__main__":
    main()
