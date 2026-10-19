"""The pairing gate's judge questions from the two benches, as a fixed set: every pairing Jev was asked about in
the leads arm of experiments/bench-leads and experiments/bench-multistep, with Jev's answer.

    python pairings.py build      -> pairings.json (request, Jev's p, where it came from)

Accepted answers keep each verdict's request. A refused submission is not stored, but its refusal names the
sentence, the quote and `of`, so its request is rebuilt with pairing.request() exactly as the gate built it.
"""
import glob
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from ugrc import pairing, store  # noqa: E402

REFUSAL = re.compile(r"the judge reads (\S+) as not giving (.+?) for (.+?) \(yes ([0-9.]+)\)")


def build():
    out, seen = [], set()
    cons = {}
    for bench in ("bench-leads", "bench-multistep"):
        for f in sorted(glob.glob(str(ROOT / f"experiments/{bench}/answers/leads-*/*.json"))):
            r = json.loads(Path(f).read_text())
            name = f.split("answers/")[1]
            for v in r.get("pairings") or []:
                if v.get("by") != "judge":
                    continue
                key = (r["paper"], v["request"]["state"], v["of"])
                if key in seen:
                    continue
                seen.add(key)
                out.append({"id": f"{bench}/{name}#{v['run']}", "paper": r["paper"], "sentence": v["sentence"],
                            "quote": v["quote"], "of": v["of"], "request": v["request"], "jev_p": v["p"]})
            for sub in r["door_refusals"]:
                for x in sub:
                    if x["rule"] != "pairing:judge":
                        continue
                    m = REFUSAL.match(x["why"])
                    sid, quote, of, p = m.group(1), eval(m.group(2)), eval(m.group(3)), float(m.group(4))
                    root = ROOT / "runs/bench" / r["paper"]
                    con = cons.setdefault(r["paper"], store.connect_question(root))
                    text = con.execute("SELECT text FROM sentences WHERE id = ?", [sid]).fetchone()[0]
                    mm = pairing._pattern(quote).search(text)
                    req = pairing.request(text, mm.start(), mm.end(), of)
                    key = (r["paper"], req["state"], of)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({"id": f"{bench}/{name}#refused:{x['where']}", "paper": r["paper"], "sentence": sid,
                                "quote": quote, "of": of, "request": req, "jev_p": p})
    (HERE / "pairings.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(len(out), "distinct pairings;", sum(1 for x in out if x["jev_p"] < 0.5), "refused by Jev")


if __name__ == "__main__":
    build()
