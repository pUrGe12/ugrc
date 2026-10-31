"""Routing of the short questions (PLAN.md): BM25 over every page of the big-library papers, as the big-library test's
router, on the short and the long form of each question. No model.

    python experiments/short-route/route.py
"""
import collections
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("big_run", ROOT / "experiments" / "big-library" / "run.py")
run = importlib.util.module_from_spec(_spec)
sys.modules["big_run"] = run
_spec.loader.exec_module(run)


def frozen():
    for line in (HERE / "frozen.sha256").read_text().splitlines():
        digest, name = line.split()
        assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == digest, f"{name} changed since it was frozen"


def main():
    frozen()
    lib = run.library()
    ix = run.index(lib)
    qs = run.questions()
    short = json.loads((HERE / "short.json").read_text())["questions"]
    libs10 = json.loads((ROOT / "experiments" / "library" / "libraries.json").read_text())["libraries"]
    old = json.loads((ROOT / "experiments" / "library" / "questions.json").read_text())["questions"]
    asked = {d for d, v in lib.items() if v["asked"]}
    rows = {}
    for key, q in qs.items():
        target = f"{q['set']}/{q['paper']}"
        r = {"target": target, "unchanged": short[key]["short"] == q["q"]}
        for form, text in (("long", q["q"]), ("short", short[key]["short"])):
            order = run.paper_order(ix.rank(text))
            r[form] = {"whole": order.index(target) + 1, "routed": order[0],
                       "asked": run.paper_order(ix.rank(text, asked)).index(target) + 1}
            if key in old:
                sub = set(libs10[old[key]["library"]]["documents"])
                r[form]["10"] = run.paper_order(ix.rank(text, sub)).index(target) + 1
        rows[key] = r
    (HERE / "routing.json").write_text(json.dumps(rows, indent=1) + "\n")

    def line(keys, form, view):
        ks = [k for k in keys if view in rows[k][form]]
        top = [sum(rows[k][form][view] <= n for k in ks) for n in (1, 2, 5)]
        return f"{len(ks):3}  top1 {top[0]:3} ({top[0] / max(1, len(ks)):.1%})  top2 {top[1]:3}  top5 {top[2]:3}"

    print(f"library: {len(lib)} papers ({len(asked)} asked about)")
    for view, name in (("whole", "whole library"), ("asked", "45 papers asked about"), ("10", "10-paper libraries")):
        for form in ("long", "short"):
            print(f"{name:22} {form:5} " + line(list(rows), form, view))
    groups = collections.defaultdict(list)
    for k in rows:
        groups["set " + k.split("/")[0]].append(k)
        groups["cat " + qs[k]["cat"]].append(k)
    print("by set and category, whole library (long -> short, right paper first):")
    for g, ks in sorted(groups.items()):
        a = sum(rows[k]["long"]["whole"] == 1 for k in ks)
        b = sum(rows[k]["short"]["whole"] == 1 for k in ks)
        print(f"  {g:18} {a:3} -> {b:3} of {len(ks):3}")
    changed = [k for k in rows if not rows[k]["unchanged"]]
    print(f"changed questions only ({len(changed)}): long " + line(changed, "long", "whole")
          + f"\n{'':28}short " + line(changed, "short", "whole"))
    lost = [k for k in rows if rows[k]["long"]["whole"] == 1 and rows[k]["short"]["whole"] > 1]
    won = [k for k in rows if rows[k]["long"]["whole"] > 1 and rows[k]["short"]["whole"] == 1]
    where = collections.Counter(rows[k]["short"]["routed"].split("/")[0] + ("" if lib[rows[k]["short"]["routed"]]["asked"]
                                                                            else " (added)") for k in lost)
    print(f"lost by shortening: {len(lost)}; gained: {len(won)}; lost questions went to: " +
          ", ".join(f"{s} {n}" for s, n in where.most_common()))
    same = sum(rows[k]["short"]["routed"].split("/")[0] == rows[k]["target"].split("/")[0] for k in lost)
    print(f"  of the lost, sent to a paper of the same set: {same}")


if __name__ == "__main__":
    main()
