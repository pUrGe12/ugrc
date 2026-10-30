"""Leads (the clause-base rows code matches to a question, sent with it) and the measure run (a clause-base
value shown by id, quoted from its line by the machine), through the door, the pairing gate, the loop and
the receipt."""
import json

import duckdb

from tests.fakes import FakeClient, tool_response
from tests.test_routing import Judge, clause_base, reseal
from ugrc import answer, ask, clauses, leads, pairing, store, verify


def _add_measure(root, **row):
    db = duckdb.connect(str(root / clauses.CLAUSE_DB))
    base = {"sentence": "p1.L2:0", "atoms": ["p1.L2"], "role": "result", "role_p": 0.9, "property": "other",
            "property_p": 0.5, "about": [], "measured_by": [], "quantity": []}
    store._insert(db, "measures", [{**base, **row}])
    reseal(db)
    db.close()


def test_leads_find_the_sentence_and_its_values(synth_root):
    clause_base(synth_root)
    con = store.connect_question(synth_root)
    found = leads.find(con, "What yield was obtained over Ni-10?")
    assert found.sentences == ["p1.L2:0"] and found.measures == ["p1.L2:0#14", "p1.L2:0#23"]
    assert "p1.L2:0#14 '85.2%': result; share; of Ni-10; measures yield" in found.text
    assert found.record() == {"sentences": ["p1.L2:0"], "measures": ["p1.L2:0#14", "p1.L2:0#23"], "matched": 1}
    assert leads.find(con, "What yield was obtained over Ni-10?").text == found.text       # code, not a model
    none = leads.find(con, "How many mice were dosed?")
    assert not none.sentences and "No sentence of the prose matched" in none.text


def test_leads_read_the_documents_words_not_the_judges_labels(synth_root):
    clause_base(synth_root)
    con = store.connect_question(synth_root)
    assert not leads.find(con, "Which share was reported?").sentences         # "share" is the judge's label only
    assert leads.find(con, "What was the yiild?").sentences == ["p1.L2:0"]   # a misspelling of a word found nowhere
    assert leads.terms("What is the maximum strain of the V2O5 films?") == ["maximum", "strain", "v2o5", "films"]


def test_a_question_phrase_widens_by_the_name_the_document_defines_for_it(synth_root):
    clause_base(synth_root)
    con = store.connect_question(synth_root)
    texts = [answer.fold("Elastic strains applied to vanadium pentoxide (V2O5), a cathode, and to film (<1%).")]
    assert leads.defined(con, "What strain does the vanadium pentoxide film take?", texts) == ["v2o5"]


def test_without_a_clause_base_the_question_goes_alone(synth_root):
    con = store.connect_question(synth_root)
    text, found = ask.question_message(con, "What was the yield?")
    assert text == "What was the yield?" and found.record() == {"sentences": [], "measures": [], "matched": 0}
    assert '{"measure"' not in ask.system_prompt(con)


def test_a_measure_run_shows_the_value_quoted_from_its_line(synth_root):
    clause_base(synth_root)
    con = store.connect_question(synth_root)
    assert '{"measure": "<id>"}' in ask.system_prompt(con)
    checked = answer.check({"runs": [{"text": "The yield was "}, {"measure": "p1.L2:0#14"}]}, con)
    assert checked.ok, checked.refusal_text()
    assert checked.text == "The yield was 85.2%[1]"
    c = checked.citations[0]
    assert c["kind"] == "quote" and c["quote"] == "85.2%" and c["measure"] == "p1.L2:0#14"
    assert c["source"]["atom"] == "p1.L2" and c["strength"] == "verbatim"
    assert c["reading"] == {"role": "result", "role_p": 0.95, "property": "share", "property_p": 0.8, "about": ["Ni-10"],
                            "method": [], "quantity": ["yield"], "sentence": "p1.L2:0", "read_by": "judge"}


def test_a_measure_run_is_refused_by_name(synth_root, con):
    no_base = answer.check({"runs": [{"measure": "p1.L2:0#14"}]}, con)
    assert no_base.refusals[0].rule == "measure:no-clause-base"
    clause_base(synth_root)
    _add_measure(synth_root, id="p1.L2:0#15", text="5.2", value="5.2")        # a cut through "85.2%"
    qcon = store.connect_question(synth_root)
    bad = answer.check({"runs": [{"measure": "p1.L2:0#99"}, {"measure": "p1.L2:0#15"}, {"measure": "p1.L2:0#14", "x": 1}]}, qcon)
    assert [r.rule for r in bad.refusals] == ["measure:absent", "measure:cut", "run:fields"]
    assert "occurs in p1.L2 only as part of a longer word or number" in bad.refusals[1].why
    found = leads.find(qcon, "What yield over Ni-10?")
    assert "p1.L2:0#15 '5.2'" in found.text and "cannot be shown as it is" in found.text


def test_a_measure_run_names_what_it_is_of_and_the_gate_checks_it(synth_root):
    clause_base(synth_root)
    con = store.connect_question(synth_root)
    runs = [{"measure": "p1.L2:0#14", "of": "Ni-10"}]
    checked = answer.check({"runs": runs}, con)
    refused, verdicts = pairing.check(con, runs, checked.citations, Judge(0.0))
    assert not refused and verdicts[0]["by"] == "clause base" and checked.citations[0]["of"] == "Ni-10"
    runs = [{"text": "Over the other catalyst, "}, {"measure": "p1.L2:0#14", "of": "Ni-20"}]
    checked = answer.check({"runs": runs}, con)
    refused, _ = pairing.check(con, runs, checked.citations, Judge(0.04))
    assert refused[0].rule == "pairing:judge" and refused[0].where == "runs[1]"


def test_the_loop_sends_leads_and_the_receipt_rechecks_a_measure_answer(synth_root):
    clause_base(synth_root)
    runs = [{"text": "Over "}, {"quote": "Ni-10", "atom": "p1.L2"}, {"text": " the yield was "},
            {"measure": "p1.L2:0#14", "of": "Ni-10"}]
    cl = FakeClient([tool_response("submit_answer", {"runs": runs})])
    rec = ask.ask(synth_root, "What was the yield over Ni-10?", model="m", cl=cl, log=lambda *_: None, judge=Judge(0.0))
    sent = cl.calls[0]["messages"][0]["content"]
    assert sent.startswith("What was the yield over Ni-10?\n\n## Leads from the clause base") and "p1.L2:0#14" in sent
    assert rec["question"] == "What was the yield over Ni-10?" and rec["leads"]["measures"][0] == "p1.L2:0#14"
    assert rec["rendered"] == "Over Ni-10[1] the yield was 85.2%[2]" and rec["door_version"] == answer.DOOR_VERSION
    assert rec["clause_seal"] == store.clause_seal(store.connect_question(synth_root))[0]
    path = ask.save(synth_root, rec)
    lines = verify.verify_answer(path, synth_root)
    assert all(ok for ok, _ in lines) and any("clause base holds the rows" in m for _, m in lines)
    db = duckdb.connect(str(synth_root / clauses.CLAUSE_DB))                   # someone edits the judge's reading
    db.execute("UPDATE measures SET about = ['Ni-20'] WHERE id = 'p1.L2:0#14'")
    db.close()
    lines = verify.verify_answer(path, synth_root)
    assert not all(ok for ok, _ in lines) and any("the clause base changed" in m for _, m in lines)


def test_a_session_sends_each_question_its_own_leads(synth_root):
    clause_base(synth_root)
    cl = FakeClient([tool_response("submit_answer", {"runs": [{"measure": "p1.L2:0#14"}]}),
                     tool_response("submit_answer", {"runs": [{"text": "Not said."}]})])
    recs = ask.session(synth_root, ["What was the yield?", "How many mice were dosed?"], model="m", cl=cl,
                       log=lambda *_: None, judge=Judge(0.0))
    second = cl.calls[1]["messages"][-1]["content"][-1]["text"]
    assert second.startswith("How many mice were dosed?\n\n## Leads") and "No sentence of the prose matched" in second
    assert recs[0]["leads"]["measures"] and not recs[1]["leads"]["measures"]


def test_an_answer_of_door_v3_still_rechecks(synth_root, con):
    runs = [{"text": "The yield was "}, {"quote": "85.2%", "atom": "p1.L2"}]
    checked = answer.check({"runs": runs}, con)
    seals = dict(con.execute("SELECT name, sha256 FROM seals").fetchall())
    path = synth_root / "v3.json"
    path.write_text(json.dumps({"runs": runs, "rendered": checked.text, "citations": checked.citations,
                                "seals": seals, "door_version": "3"}))
    assert all(ok for ok, _ in verify.verify_answer(path, synth_root))
    path.write_text(json.dumps({"runs": runs, "rendered": checked.text, "citations": checked.citations,
                                "seals": seals, "door_version": "2"}))
    assert not all(ok for ok, _ in verify.verify_answer(path, synth_root))


def test_the_small_prompt_keeps_the_same_door_in_fewer_words(synth_root):
    # style "small" (for a small open model): every placeholder filled, the measure run and leads only with a
    # clause base, made-up examples only, and shorter than the full prompt
    con = store.connect_question(synth_root)
    plain = ask.system_prompt(con, "small")
    assert "@" not in plain and '{"measure"' not in plain and "## Leads" not in plain
    assert "you never type a number yourself" in plain and "1,250 m^2/g" in plain
    clause_base(synth_root)
    con = store.connect_question(synth_root)
    small, full = ask.system_prompt(con, "small"), ask.system_prompt(con)
    assert "@" not in small and '{"measure": "<id>"}' in small and "## Leads" in small
    assert len(small.split()) < 0.75 * len(full.split())
    assert ask.system_prompt(con, "full") == full
