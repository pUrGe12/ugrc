import json

import duckdb
import pytest

from ugrc import clauses
from ugrc.clauses import Sentence


def S(text, sid="p1.L1:0", kind="body"):
    return Sentence(id=sid, page=1, kind=kind, text=text, atoms=[(sid.split(":")[0], 0)])


def values(text):
    s = S(text)
    return [(s.text[m.start:m.end], m.lo, m.hi, m.unit, m.key) for m in clauses.mentions(s)]


# ─────────────── mentions: what is a number, and what it reads as ───────────────

def test_units_ranges_and_scientific_notation():
    assert values("cultured at 37 ◦C for 24 h") == [("37 ◦C", 37, 37, "◦C", None), ("24 h", 24, 24, "h", None)]
    assert values("values of 7.6 × 10^7 CFU/mL") == [("7.6 × 10^7 CFU/mL", 7.6e7, 7.6e7, "CFU/mL", None)]
    assert values("across the range of 45 to 120 μM") == [("45 to 120 μM", 45, 120, "μM", None)]
    assert values("a gradient (OD600 =0.02–0.2).") == [("0.02–0.2", 0.02, 0.2, None, "OD600")]
    assert values("a KOH solution (pH 11).") == [("11", 11, 11, None, "pH")]
    assert values("a size of 143.47 ± 10.34 nm")[0][1:4] == (pytest.approx(133.13), pytest.approx(153.81), "nm")
    assert values("median OS was 7 months") == [("7 months", 7, 7, "months", None)]


def test_a_ratio_has_no_interval():
    assert values("ratios of 1:0, 1:4 and 0:1") == [("1:0", None, None, None, None), ("1:4", None, None, None, None),
                                                   ("0:1", None, None, None, None)]


def test_references_names_and_links_hold_no_quantity():
    assert values("as shown (Fig. S17a, Tables S4-S8) and before [40], [8–10].") == []
    assert values("OD600 and 4-MPBA were used in 2D plots, see https://doi.org/10.1016/j.x.2026.1") == []
    assert values("E-mail: 53408829@qq.com") == []


def test_chemical_locants_are_names_not_quantities():
    assert values("acetoin and 2,3-butanediol (2,3-BD), 1,8-cineole and the 3′ UTRs") == []
    assert [v for v, *_ in values("a 1,000-fold rise")] == ["1,000-fold"]


def test_an_unmapped_minus_in_a_unit_exponent_is_part_of_the_unit():
    got = values("R82 reached 11.4 g L^(cid:0) 1 prodigiosin")
    assert got == [("11.4 g L^(cid:0) 1", 11.4, 11.4, "g L^(cid:0) 1", None)]   # no phantom "1"


def test_a_unit_printed_once_after_a_list_belongs_to_every_number_in_it():
    got = values("Maximum titers of 70.50, 60.32, and 102.3 g L^-1 were reported")
    assert [u for *_, u, _ in got] == ["g L^-1"] * 3


def test_an_unmapped_glyph_before_a_number_makes_its_sign_unknown():
    s = S("the g-factors were (cid:0) 0.0151 and 0.0150")
    ms = clauses.mentions(s)
    assert [m.value for m in ms] == ["0.0151", "0.0150"]          # the 0 of "(cid:0)" is not a value
    assert ms[0].lo is None and ms[0].hi is None and "sign is unknown" in ms[0].note
    assert ms[1].lo == 0.015


# ─────────────── sentences, terms, definitions, phrases ───────────────

def _sentences(texts):
    class Con:                                                    # the two queries `blocks` makes
        def execute(self, sql, *_):
            rows = ([(f"p1.L{i}", 1, i, t, 8.0, 50.0 + 10 * i) for i, t in enumerate(texts, 1)]
                    if "FROM lines" in sql else [])
            return type("R", (), {"fetchall": lambda self: rows})()
    return clauses.sentences(Con())


def test_a_period_after_an_abbreviation_does_not_end_a_sentence():
    got = [s.text for s in _sentences(["P. aeruginosa grew (Fig. 2a). The LOD was", "low, et al. [4] said."])]
    assert got == ["P. aeruginosa grew (Fig. 2a).", "The LOD was low, et al. [4] said."]


def test_a_sentence_maps_back_to_its_line_atoms():
    s = _sentences(["The LOD was", "0.0034 in water."])[0]
    m = clauses.mentions(s)[0]
    assert m.atoms == ["p1.L2"] and s.atoms_at(0, len(s.text)) == ["p1.L1", "p1.L2"]


def test_terms_species_materials_codes_and_slashed_parts():
    got = [t for t, _ in clauses.terms("P. aeruginosa met BA@L-HGNRs by UV–vis and CD/RGB, mail a@b.com")]
    assert got == ["P. aeruginosa", "BA@L-HGNRs", "UV–vis", "CD/RGB", "CD", "RGB"]
    assert [t for t, _ in clauses.terms("strain R82 and S. marcescens H32 made 2,3-BD")] == \
        ["R82", "S. marcescens", "H32", "2,3-BD"]
    assert [t for t, _ in clauses.terms("the Cys level", known={"Cys"})] == ["Cys"]


def test_definitions_are_spelled_letter_by_letter_and_shared_in_one_parenthesis():
    got = {a["term"]: a["long_form"] for a in clauses.aliases(S(
        "lower limit of detection (LOD) and 4-mercaptophenyl-boronic acid (4-MPBA, BA) were used"))}
    assert got == {"LOD": "limit of detection", "4-MPBA": "4-mercaptophenyl-boronic acid",
                   "BA": "4-mercaptophenyl-boronic acid"}


@pytest.mark.parametrize("text, expected", [
    ("Then 320 μL of the above solution was mixed in a 1.5 mL tube", ["above solution", "tube"]),
    ("these bacteria are tested across a gradient", ["bacteria", "gradient"]),
    ("4 signals × 7 bacteria ×5 replicates", ["signals", "bacteria", "replicates"]),
    ("titers for (E)-nerolidol and ((cid:0) )-α-bisabolol, respectively", ["titers", "(E)-nerolidol", "((cid:0) )-α-bisabolol"]),
    ("the engineered strain PG yielded more than S. marcescens strains", ["strain PG", "S. marcescens strains"]),
    ("achieved 2976.2 mg L^-1 geraniol using two-phase fermentation", ["geraniol", "two-phase fermentation"]),
])
def test_nominal_phrases(text, expected):
    s = S(text)
    spans = [(m.start, m.end) for m in clauses.mentions(s)]
    assert [p for p, _ in clauses.noun_phrases(s.text, spans)] == expected


def test_head_words_settle_the_kind_a_word_list_can():
    assert clauses.lexicon_kind("limit of detection") == "measure"
    assert clauses.lexicon_kind("4-MPBA concentra-tion") == "measure"
    assert clauses.lexicon_kind("S. marcescens strains") == "organism"
    assert clauses.lexicon_kind("linear discriminant analysis") == "method"
    assert clauses.lexicon_kind("above solution") is None          # left to the judge
    assert clauses.term_kind_by_rule("P. aeruginosa", None) == "organism"


# ─────────────── the layout and the unit decide what they can ───────────────

def _plan(text, kinds=None):
    s = S(text)
    P = clauses.read_paper([s])
    k = {}
    for t, _ in clauses.terms(s.text, P.genus, P.known):
        k[t] = ((kinds or {}).get(t) or clauses.term_kind_by_rule(t, P.long_forms.get(t)) or clauses.THING,
                None, None, "test", s.id)
    for p, _ in clauses.noun_phrases(s.text, clauses._value_spans(s.text, P.ms[s.id])):  # the judge types phrases
        k.setdefault((s.id, p), ((kinds or {}).get(p) or clauses.lexicon_kind(p) or clauses.THING, None, None, "test", s.id))
    plans = clauses.plan_value(P, s, k)
    return {s.text[pl["mention"].start:pl["mention"].end]: pl for pl in plans.values()}


def _laid(pl):
    return {k: [x for x, _ in v] if isinstance(v, list) else v for k, v in pl["layout"].items()}


def test_the_layout_names_quantity_subject_and_method():
    got = _plan("P. aeruginosa had an LOD of OD600 =0.0034 (CD, Fig. S17a) and 9.2 × 10^7 CFU/mL (E. coli).",
                {"CD": "method", "OD600": "measure", "CFU": "other", "LOD": "measure"})
    assert _laid(got["0.0034"]) == {"quantity": ["LOD", "OD600"], "method": ["CD"]}
    assert got["0.0034"]["property"] == ["detection limit"] and set(got["0.0034"]["ask"]) == {"who"}
    assert _laid(got["9.2 × 10^7 CFU/mL"])["who"] == ["E. coli"]


@pytest.mark.parametrize("text, value, slot, span", [
    ("Thus, 65 mM NaCl was set as the condition.", "65 mM", "what", "NaCl"),
    ("Then 320 μL of the above solution was mixed.", "320 μL", "what", "above solution"),
    ("mixed with 6.4 μL of 4-MPBA solution (10 mM in ethanol)", "10 mM", "what", "4-MPBA solution"),
    ("Further increasing NaCl from 65 mM to 95 mM only caused a decrease.", "95 mM", "what", "NaCl"),
    ("a 4-MPBA concentra-tion of 165 μM was chosen", "165 μM", "what", "4-MPBA"),
])
def test_the_layout_names_the_subject(text, value, slot, span):
    assert span in _laid(_plan(text)[value])[slot]


def test_a_count_names_what_it_counts_and_asks_nothing_else():
    got = _plan("reactions were run (4 signals × 7 bacteria ×5 replicates, Table S1) and analysed by LDA.")
    assert _laid(got["4"]) == {"what": ["signals"], "count": True} and got["4"]["ask"] == {}
    assert _laid(got["7"])["who"] == ["bacteria"] and got["7"]["property"] == ["count"]


def test_dates_and_names_are_labels_not_counts():
    got = _plan("Received 25 June 2026; a Phase II trial began with Cohort 2, and 12 September passed.")
    assert all(pl["layout"].get("label") for v, pl in got.items() if v in ("25", "2026", "2"))
    assert not got["12"]["layout"].get("count")                   # "12 September" counts no September


def test_respectively_pairs_two_lists_in_order():
    got = _plan("limonene and nerolidol reached 14.12 g L^-1 and 32.33 g L^-1, respectively.")
    assert _laid(got["14.12 g L^-1"])["what"] == ["limonene"] and _laid(got["32.33 g L^-1"])["what"] == ["nerolidol"]


def test_the_unit_narrows_the_property():
    got = _plan("kept at 37 ◦C for 24 h, spun at 6800 rpm, 2.9-fold higher, peaks at 585 nm and 90% of cells")
    assert got["37 ◦C"]["property"] == ["temperature"] and got["24 h"]["property"] == ["duration"]
    assert got["6800 rpm"]["property"] == ["speed"] and got["2.9-fold"]["property"] == ["ratio"]
    assert got["585 nm"]["property"] == ["size", "wavelength"]
    assert "share" in got["90%"]["property"] and "temperature" not in got["90%"]["property"]


def test_a_slot_offers_only_its_kind_nearest_first_and_a_list_as_one_option():
    got = _plan("Each strain (P. aeruginosa, E. coli, S. aureus) was cultured in LB broth at 37 ◦C by CD.",
                {"CD": "method"})
    ask = got["37 ◦C"]["ask"]
    assert [clauses.option_label(o) for o in ask["who"]][-1] == "all of: P. aeruginosa, E. coli, S. aureus"
    assert all(o.kind == "organism" for o in ask["who"] if not isinstance(o, tuple))
    assert [clauses.option_label(o) for o in ask["method"]] == ["CD"]


# ─────────────── the requests a judge sees ───────────────

def test_requests_hold_one_marked_sentence_typed_options_and_a_way_out():
    pl = _plan("P. aeruginosa and E. coli had an LOD of 0.0034 by CD.", {"CD": "method", "LOD": "measure"})["0.0034"]
    s = S("P. aeruginosa and E. coli had an LOD of 0.0034 by CD.")
    req = clauses.value_request(pl["mention"], s, pl)
    assert req["state"].count("[[0.0034]]") == 1 and "\n" not in req["state"]
    who = req["questions"]["who"]
    assert set(who["criteria"]) == {"P. aeruginosa", "E. coli", "all of: P. aeruginosa, E. coli", clauses.NONE}
    assert "[[0.0034]]" in who["instructions"] and "reported for" in who["instructions"]
    assert all(len(q["criteria"]) <= clauses.MAX_OPTIONS + 3 for q in req["questions"].values())
    json.dumps(req)                                              # what is sent is plain JSON


# ─────────────── decisions: confirm, withhold, flag ───────────────

def judge(script=None, yes=0.9):
    """A scripted judge: every choice question takes its first label unless `script(state, key, question)`
    names another (probability 0.9); every yes/no answers `yes`, or what `script` returns for it."""
    def ask(state, questions, model=None):
        answers = {}
        for key, q in questions.items():
            if q["type"] == "noul":
                v = script and script(state, key, q)
                answers[key] = {"type": "noul", "noul": yes if v is None else v}
                continue
            labels = list(q["criteria"])
            pick = (script and script(state, key, q)) or labels[0]
            answers[key] = {"type": "choice", "choice": pick, "confidence": 0.9,
                            "probabilities": {l: (0.9 if l == pick else 0.1 / (len(labels) - 1)) for l in labels}}
        return {"model": "jev-test", "answers": answers, "usage": {"input_tokens": 10, "output_tokens": 2}}
    return ask


def _decide(texts, script=None, yes=0.9):
    P = clauses.read_paper([S(t, sid=f"p1.L{i}:0") for i, t in enumerate(texts, 1)])
    answer = lambda items: clauses.ask_all(items, ask=judge(script, yes), model="m", workers=2, log=lambda *_: None)
    rounds, responses = clauses.run_rounds(P, answer, "m")
    return clauses.decide(P, rounds, responses, "m")


def _pick(slot, label):
    return lambda state, key, q: label if key == slot else None


def test_an_organism_is_asked_for_as_what_the_value_is_reported_for():
    # a titer is the product's concentration, made by the strain: never "the concentration of R82"
    def script(state, key, q):
        if "prodigiosin" in q["instructions"] and "what is" in q["instructions"]:
            return clauses.THING                  # the kind question: prodigiosin is a material
        return "R82" if key == "who" else None
    *_, ms = _decide(["In fed-batch fermentation, R82 reached 11.4 g L^-1 prodigiosin."], script)
    assert ms[0]["about"] == ["R82", "prodigiosin"]


def test_a_confirmed_choice_is_kept():
    *_, ms = _decide(["P. aeruginosa and E. coli had an LOD of 0.0034 by CD."], _pick("who", "E. coli"))
    assert ms[0]["about"] == ["E. coli"] and not any("did not confirm" in f for f in ms[0]["flags"])


def test_an_unconfirmed_choice_is_withheld_and_flagged():
    *_, ms = _decide(["P. aeruginosa and E. coli had an LOD of 0.0034 by CD."], _pick("who", "E. coli"), yes=0.2)
    assert ms[0]["about"] == [] and any("did not confirm" in f for f in ms[0]["flags"])


def test_none_of_these_binds_nothing():
    *_, ms = _decide(["P. aeruginosa and E. coli had an LOD of 0.0034 by CD."], _pick("who", clauses.NONE))
    assert ms[0]["about"] == []


def test_a_list_option_binds_every_member():
    *_, ms = _decide(["Each strain (P. aeruginosa, E. coli) was cultured at 37 ◦C."],
                     _pick("who", "all of: P. aeruginosa, E. coli"))
    assert ms[0]["about"] == ["P. aeruginosa", "E. coli"]


def test_a_label_answer_makes_an_identifier_and_binds_nothing():
    *_, ms = _decide(["The protocol code is 4471 for P. aeruginosa."], _pick("amount", "label"))
    assert ms[0]["role"] == "identifier" and ms[0]["about"] == []


def test_a_hedge_word_judged_as_a_result_is_flagged():
    _, _, sents, _, _ = _decide(["The probe may bind the rods."])
    assert sents[0]["modality"] == "result" and "hedge word (may)" in sents[0]["flags"][0]


def test_one_subject_with_two_values_is_flagged():
    *_, ms = _decide(["AuNRs had a length of 90 nm and AuNRs had a length of 95 nm."],
                     lambda st, k, q: "measured" if k == "origin" else None)
    assert all(any("different value" in f for f in m["flags"]) for m in ms)


# ─────────────── build, replay, receipt ───────────────

def test_build_pins_every_judgment_and_the_receipt_reproduces_it(synth_root, tmp_path):
    out = clauses.build(synth_root, tmp_path / "c1", ask=judge(), model="m", workers=2, log=lambda *_: None)
    assert all(ok for ok, _ in clauses.recheck(synth_root, tmp_path / "c1"))
    with pytest.raises(SystemExit):
        clauses.build(synth_root, tmp_path / "c1", ask=judge(), model="m", log=lambda *_: None)
    clauses.replay(synth_root, tmp_path / "c1", tmp_path / "c2", log=lambda *_: None)
    a, b = (duckdb.connect(str(p), read_only=True) for p in (out, tmp_path / "c2" / clauses.CLAUSE_DB))
    assert a.execute("SELECT * FROM measures ORDER BY ALL").fetchall() == \
        b.execute("SELECT * FROM measures ORDER BY ALL").fetchall()
    a.close(), b.close()


def test_the_receipt_catches_an_edited_clause(synth_root, tmp_path):
    clauses.build(synth_root, tmp_path / "c", ask=judge(), model="m", workers=2, log=lambda *_: None)
    db = duckdb.connect(str(tmp_path / "c" / clauses.CLAUSE_DB))
    db.execute("UPDATE measures SET about = ['Ni-20'] WHERE id = (SELECT min(id) FROM measures)")
    db.close()
    bad = [m for ok, m in clauses.recheck(synth_root, tmp_path / "c") if not ok]
    assert any("seal" in m for m in bad) and any("reproduces measures" in m for m in bad)


def test_rerun_compares_decisions_by_label(synth_root, tmp_path):
    clauses.build(synth_root, tmp_path / "c", ask=judge(), model="m", workers=2, log=lambda *_: None)
    flip = judge(lambda st, k, q: list(q["criteria"])[1] if k == "origin" else None)
    lines = clauses.recheck(synth_root, tmp_path / "c", rerun=True, ask=flip, log=lambda *_: None)
    assert any("re-asked: origin" in m for ok, m in lines if not ok)
    assert "decisions identical" in lines[-1][1] and not lines[-1][0]


def test_replay_refuses_questions_the_source_never_asked(synth_root, tmp_path):
    clauses.build(synth_root, tmp_path / "c", ask=judge(), model="m", workers=2, log=lambda *_: None)
    db = duckdb.connect(str(tmp_path / "c" / clauses.CLAUSE_DB))
    db.execute("DELETE FROM jev_calls WHERE kind = 'mention'")
    db.close()
    with pytest.raises(SystemExit, match="never asked"):
        clauses.replay(synth_root, tmp_path / "c", tmp_path / "d", log=lambda *_: None)


# ─────────────── v8: battery papers ───────────────

@pytest.mark.parametrize("text, expected", [
    ("sodium loading up to 12 mAh/cm^2, and more", [("12 mAh/cm^2", "mAh/cm^2", 12)]),
    ("at 0.1C (≈184 mAh g^− 1) prior", [("≈184 mAh g^− 1", "mAh g^− 1", 184)]),
    ("a range of 260 miles", [("260 miles", "miles", 260)]),
    ("By 2030, 11 million metric tons of LIBs", [("2030", None, 2030), ("11 million metric tons", "metric tons", 1.1e7)]),
    ("achieve 10-15 min fast charging", [("10-15 min", "min", 10)]),
    ("bands at 1402, 1172, and 871 cm^−1, which", [("1402", "cm^−1", 1402), ("1172", "cm^−1", 1172), ("871 cm^−1", "cm^−1", 871)]),
    ("conductivity 1.74 ×10^− 5 S cm^− 1 here", [("1.74 ×10^− 5 S cm^− 1", "S cm^− 1", pytest.approx(1.74e-5))]),
    ("Materials Today d Volume 41 d December", [("41", None, 41)]),
])
def test_battery_units_exponents_scales_and_ranges(text, expected):
    s = S(text)
    assert [(s.text[m.start:m.end], m.unit, m.lo) for m in clauses.mentions(s)] == expected


@pytest.mark.parametrize("ref", ["■ REFERENCES", "References", "[1] A. Manthiram, J. C. Knight, Adv. Energy Mater.",
                                 "[1] a) D. Song, X. Wang, J. Power Sources 2013", "(1) Li, H.; Peng, L. Energy Environ."])
def test_the_reference_list_ends_the_prose_however_it_is_headed(ref):
    texts = ["The capacity was 200 mAh/g."] * 4 + [ref, "Nano Lett. 2016, 16, 543."]
    got = _sentences(texts)
    assert all("2016" not in s.text and "Manthiram" not in s.text for s in got)


def test_a_label_stays_inside_its_name_so_a_respectively_list_pairs():
    got = _plan("The capacities for NFA 811, NFA-F, and NFA-A are ≈205, 199, and 192 mAh g^− 1, respectively.")
    assert _laid(got["≈205"])["what"] == ["NFA 811"] and _laid(got["192 mAh g^− 1"])["what"] == ["NFA-A"]
