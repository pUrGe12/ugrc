"""Choose and fetch the ChemE papers by the rule in PLAN.md ("The new papers"). Filters 1-4 here; filter 5 (ingest and
clause base) is prepare.sh, and a paper that fails it is replaced by running this again with --skip PMCID.

    python experiments/cheme/fetch.py [--skip PMCID,...]
Writes ~/Desktop/papers-cheme/<topic key>.pdf, candidates.json (every search hit and its verdict) and papers.json.
"""
import json
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEST = Path.home() / "Desktop" / "papers-cheme"
TOPICS = ["distillation", "adsorption", "reactor", "pyrolysis", "CO2 capture", "membrane separation", "crystallization",
          "heat transfer", "techno-economic", "fluidized bed"]
SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
S3 = "https://pmc-oa-opendata.s3.amazonaws.com"
QUERY = ('TITLE:"{t}" AND (JOURNAL:"RSC Advances" OR JOURNAL:"ACS Omega") AND OPEN_ACCESS:y '
         'AND PUB_YEAR:[2025 TO 2026]')


def get(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "ugrc-research/0.1 (held-out test; one request at a time)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def search(topic):
    q = urllib.parse.urlencode({"query": QUERY.format(t=topic), "format": "json", "pageSize": 25,
                                "resultType": "lite", "sort": "P_PDATE_D desc"})
    return json.loads(get(f"{SEARCH}?{q}"))["resultList"]["result"]


def pdf_key(pmcid):
    """The PDF's key in the open-access dataset (the latest version)."""
    xml = get(f"{S3}/?list-type=2&prefix={pmcid}.&max-keys=200").decode()
    keys = [k.split("</Key>")[0] for k in xml.split("<Key>")[1:]]
    pdfs = sorted((k for k in keys if k.endswith(".pdf")), key=lambda k: int(k.split("/")[0].split(".")[1]))
    return pdfs[-1] if pdfs else None


def check(pmcid):
    """(verdict, pdf bytes, facts) for one candidate: filters 1-4."""
    key = pdf_key(pmcid)
    if not key:
        return "no PDF in the open-access dataset", None, {}
    data = get(f"{S3}/{key}", timeout=300)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.pdf"
        p.write_bytes(data)
        info = subprocess.run(["pdfinfo", str(p)], capture_output=True, text=True).stdout
        pages = int(next((ln.split()[-1] for ln in info.splitlines() if ln.startswith("Pages:")), "0"))
        text = subprocess.run(["pdftotext", "-enc", "UTF-8", str(p), "-"], capture_output=True, text=True).stdout
    facts = {"s3_key": key, "pages": pages, "text_chars": len(text), "bytes": len(data)}
    if not 5 <= pages <= 25:
        return f"{pages} pages", None, facts
    if len(text) < 15_000:
        return f"text layer {len(text)} characters", None, facts
    if not any(ln.strip().startswith("Table 1") for ln in text.splitlines()):
        return "no line starts with 'Table 1'", None, facts
    return "chosen", data, facts


def main():
    skip = set(sys.argv[sys.argv.index("--skip") + 1].split(",")) if "--skip" in sys.argv else set()
    DEST.mkdir(exist_ok=True)
    cands, chosen, taken = {}, {}, set()
    for topic in TOPICS:
        key = topic.lower().replace(" ", "-")
        cands[topic] = []
        for r in search(topic):
            pmcid = r.get("pmcid")
            row = {"pmcid": pmcid, "title": r.get("title"), "journal": r.get("journalTitle"),
                   "year": r.get("pubYear"), "doi": r.get("doi")}
            if not pmcid:
                row["verdict"] = "no PMC id"
            elif pmcid in taken:
                row["verdict"] = "taken for an earlier topic"
            elif pmcid in skip:
                row["verdict"] = "failed ingest or clause base (filter 5)"
            elif key in chosen:
                row["verdict"] = "not reached"
            else:
                verdict, data, facts = check(pmcid)
                row.update(facts, verdict=verdict)
                time.sleep(1)
                if data:
                    (DEST / f"{key}.pdf").write_bytes(data)
                    chosen[key] = row
                    taken.add(pmcid)
            cands[topic].append(row)
        print(f"{topic:16} -> {chosen.get(key, {}).get('pmcid', 'NONE')} {chosen.get(key, {}).get('title', '')[:70]}",
              flush=True)
    (HERE / "candidates.json").write_text(json.dumps(cands, indent=1, ensure_ascii=False))
    (HERE / "papers.json").write_text(json.dumps(chosen, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
