"""Door v6: a pct-formatted value whose sql already multiplies by 100 is refused, since the reader would see it
scaled twice ("3,333%" for 33.3%). Older doors' answers re-check under their own rules."""
import json

from ugrc import answer, store, verify

# 85.2 and 91.0 are cells of the synthetic Table 1; their ratio is 0.936...
RATIO = ("SELECT {e} AS r FROM (SELECT CAST(text AS DOUBLE) AS v FROM cells WHERE id = 'p1.T1.r2c2') a, "
         "(SELECT CAST(text AS DOUBLE) AS v FROM cells WHERE id = 'p1.T1.r3c2') b")


def run(expr, fmt):
    return {"sql": RATIO.format(e=expr), "column": "r", "fmt": fmt}


def test_a_percent_scaled_twice_is_refused(con):
    c = answer.check({"runs": [{"text": "The ratio is "}, run("100.0 * a.v / b.v", "pct1")]}, con)
    assert not c.ok and [r.rule for r in c.refusals] == ["sql:pct-scaled"] and c.refusals[0].where == "runs[1]"
    assert "would show 9,362.6% where the value is 93.6%" in c.refusals[0].why
    assert "fixed1" in c.refusals[0].moves[0]
    for expr in ("a.v / b.v * 100", "a.v*100/b.v", "100*a.v/b.v", "a.v / b.v * 100.0"):
        assert [r.rule for r in answer.check({"runs": [run(expr, "pct0")]}, con).refusals] == ["sql:pct-scaled"], expr


def test_a_percent_shown_once_passes(con):
    c = answer.check({"runs": [run("a.v / b.v", "pct1")]}, con)                  # pct over the fraction
    assert c.ok and c.text == "93.6%[1]"
    c = answer.check({"runs": [run("100.0 * a.v / b.v", "fixed1"), {"text": "%"}]}, con)   # fixed over the percent
    assert c.ok and c.text == "93.6[1]%"
    sql = RATIO.format(e="a.v / b.v") + " WHERE 'x * 100' <> ''"                 # inside a string it is no multiplication
    assert answer.check({"runs": [{"sql": sql, "column": "r", "fmt": "pct1"}]}, con).ok


def test_door_v5_answers_still_recheck(synth_root, tmp_path):
    runs = [run("100.0 * a.v / b.v", "pct1")]
    con = store.connect_question(synth_root)
    c = answer.check({"runs": runs}, con, door="5")
    seals = dict(con.execute("SELECT name, sha256 FROM seals").fetchall())
    con.close()
    assert c.ok and c.text == "9,362.6%[1]"                                          # what door v5 accepted
    path = tmp_path / "v5.json"
    path.write_text(json.dumps({"runs": runs, "rendered": c.text, "citations": c.citations, "seals": seals,
                                "door_version": "5"}))
    assert all(ok for ok, _ in verify.verify_answer(path, synth_root))
