"""The clause base in the question loop: attached only to its own substrate, readable to find things but
never cited, and the pairing gate that checks what a quoted value is `of`."""
import json

import duckdb
import pytest

from tests.fakes import FakeClient, tool_response
from ugrc import answer, ask, clauses, lineage, pairing, store, verify
from ugrc.refusal import Refusal

SENTENCE = "The yield was 85.2% at 350 °C over Ni-10."


def clause_base(root, seals=None):
    con = store.connect_readonly(root)
    real = dict(con.execute("SELECT name, sha256 FROM seals").fetchall())
    con.close()
    db = duckdb.connect(str(root / clauses.CLAUSE_DB))
    db.execute(clauses.CLAUSE_SCHEMA)
    db.executemany("INSERT INTO clause_meta VALUES (?, ?)", [
        ("clause_version", clauses.CLAUSE_VERSION), ("substrate_seals", json.dumps(seals or real, sort_keys=True)),
        ("substrate", str(root.resolve())), ("requested_model", "jev-latest"), ("served_models", "jev-test"),
        ("built_at", "2026-10-13T00:00:00+00:00"), ("calls", "3"), ("questions", "5"),
        ("input_tokens", "100"), ("output_tokens", "10")])
    store._insert(db, "sentences", [{"id": "p1.L2:0", "page": 1, "kind": "body", "text": SENTENCE, "atoms": ["p1.L2"],
                                     "modality": "result", "modality_p": 0.97, "polarity": "affirmed", "polarity_p": 0.99}])
    store._insert(db, "measures", [
        {"id": "p1.L2:0#14", "sentence": "p1.L2:0", "atoms": ["p1.L2"], "text": "85.2%", "value": "85.2", "unit": "%",
         "role": "result", "role_p": 0.951, "property": "share", "property_p": 0.8, "about": ["Ni-10"],
         "measured_by": [], "quantity": ["yield"]},
        {"id": "p1.L2:0#23", "sentence": "p1.L2:0", "atoms": ["p1.L2"], "text": "350 °C", "value": "350", "unit": "°C",
         "role": "setting", "role_p": 0.9, "property": "temperature", "property_p": 0.9, "about": [],
         "measured_by": [], "quantity": []}])
    reseal(db)
    db.close()
    return root


def reseal(db):
    db.execute("DELETE FROM seals WHERE name = 'clauses'")
    db.execute("INSERT INTO seals VALUES ('clauses', ?, ?)",
               [store.rows_sha(db, clauses.CLAUSE_COVERS), ",".join(clauses.CLAUSE_COVERS)])


class Judge:
    """A scripted judge: answers every pairing question with the same probability, and records them."""
    def __init__(self, p):
        self.p, self.asked = p, []

    def __call__(self, state, questions):
        self.asked.append((state, questions))
        return {"model": "fake-judge", "answers": {"c_of": {"type": "noul", "noul": self.p}}, "usage": {"input_tokens": 40}}


def test_clause_base_attaches_only_to_its_own_substrate(synth_root):
    con = store.connect_question(synth_root)
    assert not store.has_clauses(con)
    con.close()
    clause_base(synth_root, seals={"extraction": "0" * 64, "readings": "0" * 64})      # built on another substrate
    con = store.connect_question(synth_root)
    assert not store.has_clauses(con)
    con.close()


def test_clause_relations_can_be_read_but_not_cited(synth_root):
    clause_base(synth_root)
    con = store.connect_question(synth_root)
    assert store.has_clauses(con)
    out = lineage.explore(con, "SELECT text, about, role_p, atoms FROM measures WHERE role = 'result'")
    assert '85.2% | ["Ni-10"] | 0.95 | ["p1.L2"]' in out
    assert "role" in lineage.explore(con, "DESCRIBE measures")
    with pytest.raises(Refusal) as e:
        lineage.cited_value(con, "SELECT value FROM measures WHERE role = 'result'", "value")
    assert e.value.rule == "sql:clause-base"
    with pytest.raises(Refusal):                                    # the files beside it stay out of reach
        lineage.explore(con, "SELECT * FROM c.main.jev_calls")
    with pytest.raises(duckdb.Error):
        con.execute("SELECT * FROM read_csv('/etc/passwd')")
    assert "## Facts already read from the prose" in ask.system_prompt(con)
    assert "## Facts already read" not in ask.system_prompt(store.connect_readonly(synth_root))


def test_the_door_keeps_of_with_the_citation(con):
    doc = {"runs": [{"text": "The yield was "}, {"quote": "85.2%", "atom": "p1.L2", "of": "Ni-10"}]}
    checked = answer.check(doc, con)
    assert checked.ok and checked.text == "The yield was 85.2%[1]" and checked.citations[0]["of"] == "Ni-10"
    plain = answer.check({"runs": [{"quote": "85.2%", "atom": "p1.L2"}]}, con)
    assert "of" not in plain.citations[0]
    bad = answer.check({"runs": [{"quote": "85.2%", "atom": "p1.L2", "of": " "}]}, con)
    assert not bad.ok and bad.refusals[0].rule == "quote:of"


def _gate(root, runs, judge):
    con = store.connect_question(root)
    checked = answer.check({"runs": runs}, con)
    assert checked.ok, checked.refusal_text()
    return pairing.check(con, runs, checked.citations, judge)


def test_the_clause_base_settles_a_pairing_without_the_judge(synth_root):
    clause_base(synth_root)
    judge = Judge(0.0)
    refused, verdicts = _gate(synth_root, [{"text": "It gave "}, {"quote": "85.2%", "atom": "p1.L2", "of": "the Ni-10 catalyst"}], judge)
    assert not refused and verdicts[0]["verdict"] == "agrees" and verdicts[0]["by"] == "clause base" and not judge.asked


def test_the_judge_refuses_a_wrong_pairing_and_names_the_right_one(synth_root):
    clause_base(synth_root)
    judge = Judge(0.04)
    runs = [{"text": "The yield of the other catalyst was "}, {"quote": "85.2%", "atom": "p1.L2", "of": "Ni-20"}]
    refused, verdicts = _gate(synth_root, runs, judge)
    assert verdicts[0]["verdict"] == "refused" and verdicts[0]["run"] == 1
    assert refused[0].rule == "pairing:judge" and refused[0].where == "runs[1]" and "Ni-10" in refused[0].why
    state, questions = judge.asked[0]
    assert state == "The yield was [[85.2%]] at 350 °C over Ni-10."
    assert questions["c_of"]["instructions"] == "Is [[85.2%]] a value of “Ni-20”?"
    refused, verdicts = _gate(synth_root, runs, Judge(0.9))
    assert not refused and verdicts[0]["by"] == "judge" and verdicts[0]["response"]["model"] == "fake-judge"


def test_quotes_outside_the_prose_are_left_unchecked(synth_root):
    clause_base(synth_root)
    refused, verdicts = _gate(synth_root, [{"quote": "91.0", "atom": "p1.T1.r3c2", "of": "Ni-20"}], Judge(0.0))
    assert not refused and verdicts[0]["verdict"] == "unchecked"


def test_the_loop_refuses_a_wrong_pairing_then_accepts_the_fix(synth_root):
    clause_base(synth_root)
    wrong = [{"text": "The yield over "}, {"quote": "Ni-20", "atom": "p1.L4"}, {"text": " was "},
             {"quote": "85.2%", "atom": "p1.L2", "of": "Ni-20"}]
    right = [{"text": "The yield over "}, {"quote": "Ni-10", "atom": "p1.L2"}, {"text": " was "},
             {"quote": "85.2%", "atom": "p1.L2", "of": "Ni-10"}]
    cl = FakeClient([tool_response("sql", {"query": "SELECT text, about, atoms FROM measures"}),
                     tool_response("submit_answer", {"runs": wrong}), tool_response("submit_answer", {"runs": right})])
    rec = ask.ask(synth_root, "What was the yield over Ni-20?", model="m", cl=cl, log=lambda *_: None, judge=Judge(0.04))
    assert rec["clause_base"] and rec["door_refusals"][0][0]["rule"] == "pairing:judge"
    assert rec["pairings"][0]["by"] == "clause base" and rec["citations"][1]["of"] == "Ni-10"
    assert rec["trace"][1]["pairings"][0]["verdict"] == "refused"
    assert "Facts already read from the prose" in cl.calls[0]["system"]
    path = ask.save(synth_root, rec)
    assert all(ok for ok, _ in verify.verify_answer(path, synth_root))


def test_the_corpus_clause_base_prefixes_every_id_and_attaches_to_the_corpus(tmp_path):
    from tests import synth
    from ugrc import corpus
    a, b = clause_base(synth.make(tmp_path / "alpha")), clause_base(synth.make(tmp_path / "beta"))
    both = corpus.build(tmp_path / "both", [a, b], log=lambda *_: None)
    with pytest.raises(SystemExit):                                  # every paper needs its clause base
        corpus.merge_clauses(both, [a])
    corpus.merge_clauses(both, [b, a])
    con = store.connect_question(both)
    assert store.has_clauses(con)
    assert con.execute("SELECT doc, id, sentence, atoms FROM measures WHERE text = '85.2%' ORDER BY doc").fetchall() == [
        ("alpha", "alpha:p1.L2:0#14", "alpha:p1.L2:0", ["alpha:p1.L2"]), ("beta", "beta:p1.L2:0#14", "beta:p1.L2:0", ["beta:p1.L2"])]
    assert "measures(doc, id, text" in ask.system_prompt(con)
    runs = [{"quote": "85.2%", "atom": "beta:p1.L2", "of": "Ni-10"}]
    checked = answer.check({"runs": runs}, con)
    refused, verdicts = pairing.check(con, runs, checked.citations, Judge(0.0))
    assert not refused and verdicts[0]["by"] == "clause base" and verdicts[0]["sentence"] == "beta:p1.L2:0"
