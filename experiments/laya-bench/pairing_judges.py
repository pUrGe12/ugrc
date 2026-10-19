"""Ask a judge every pairing-gate question of pairings.json and score its verdicts against pairing-labels.json.

    LAYA_URL=... LAYA_KEY=... python pairing_judges.py ask MODEL     -> pairing-<MODEL>.json (noul as the gate asks it,
                                                                       and the same question as a two-option choice)
    python pairing_judges.py report [MODEL ...]                    -> the table, with Jev's recorded answers

The gate accepts at yes >= CONFIRM_MIN (0.5). Laya's card says its English noul can follow its option labels, and
suggests a two-option choice with neutral keys instead; both forms are asked.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from ugrc.clauses import CONFIRM_MIN  # noqa: E402


def call(state, questions, model):
    body = json.dumps({"state": state, "questions": questions, "model": model}).encode()
    r = urllib.request.Request(os.environ["LAYA_URL"], data=body, method="POST", headers={
        "Authorization": f"Bearer {os.environ['LAYA_KEY']}", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=600).read())


def as_choice(q):
    return {"type": "choice", "instructions": q["instructions"],
            "criteria": {"A": q["criteria"]["true"], "B": q["criteria"]["false"]}}


def ask(model):
    P = json.loads((HERE / "pairings.json").read_text())
    out = {}
    for x in P:
        req = x["request"]
        a = call(req["state"], req["questions"], model)["answers"]["c_of"]
        b = call(req["state"], {"c_of": as_choice(req["questions"]["c_of"])}, model)["answers"]["c_of"]
        out[x["id"]] = {"noul": a.get("noul"), "choice_yes": b["probabilities"]["A"]}
    (HERE / f"pairing-{model}.json").write_text(json.dumps(out, indent=1))


def score(yes, labels):
    t = {"T accepted": 0, "T refused": 0, "F accepted": 0, "F refused": 0, "U accepted": 0, "U refused": 0}
    for k, p in yes.items():
        t[f"{labels[k]} {'accepted' if p >= CONFIRM_MIN else 'refused'}"] += 1
    return t


def report(models):
    P = json.loads((HERE / "pairings.json").read_text())
    labels = {k: v["label"] for k, v in json.loads((HERE / "pairing-labels.json").read_text())["labels"].items()}
    rows = [("Jev (recorded)", {x["id"]: x["jev_p"] for x in P})]
    for m in models:
        got = json.loads((HERE / f"pairing-{m}.json").read_text())
        rows += [(f"Laya {m}, noul", {k: v["noul"] for k, v in got.items()}),
                 (f"Laya {m}, choice", {k: v["choice_yes"] for k, v in got.items()})]
    print(f"{'judge':26} {'right accepted':>15} {'right refused':>14} {'wrong refused':>14} {'wrong accepted':>15} {'debatable acc/ref':>18}")
    for name, yes in rows:
        t = score(yes, labels)
        print(f"{name:26} {t['T accepted']:>9}/{t['T accepted'] + t['T refused']:<5} {t['T refused']:>14} "
              f"{t['F refused']:>10}/{t['F accepted'] + t['F refused']:<3} {t['F accepted']:>15} {t['U accepted']:>9}/{t['U refused']}")


if __name__ == "__main__":
    {"ask": lambda: ask(sys.argv[2]), "report": lambda: report(sys.argv[2:])}[sys.argv[1]]()
