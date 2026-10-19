"""The answer door: numbers only by pointer, quotes verbatim and whole, every refusal named."""
import pytest

from ugrc import answer


def ok(con, *runs):
    c = answer.check({"runs": list(runs)}, con)
    assert c.ok, c.refusal_text()
    return c


def rules(con, *runs):
    c = answer.check({"runs": list(runs)}, con)
    assert not c.ok
    return [r.rule for r in c.refusals]


@pytest.mark.parametrize("text,nums", [
    ("CO2 over Al2O3 with IL-6 and PD-L1 and TGF-β1", []),
    ("held for 2 h", ["2"]),
    ("(n = 5)", ["5)"]),
    ("about ~98 nm", ["~98"]),
    ("at −20 °C", ["−20"]),
    ("Table 2 shows", ["2"]),
    ("a 3D scaffold", ["3D"]),
    ("four trials and Twenty-five mice", ["four", "Twenty", "five"]),
    ("someone noticed nothing", []),
    ("double-stranded RNA in triple-negative cancer, a long half-life", []),
    ("1. Local invasion", []),
    ("intro\n  2) second step", []),
    ("Step 1. Local", ["1."]),
])
def test_prose_numbers(text, nums):
    assert answer.prose_numbers(text) == nums


def test_a_full_answer_renders_with_one_citation_per_pointer(con):
    c = ok(con,
           {"text": "Over "}, {"quote": "Ni-20", "atom": "p1.T1.r3c1"}, {"text": " the yield was "},
           {"quote": "91.0", "atom": "p1.T1.r3c2"}, {"text": " percent, the best in "}, {"table": "p1.T1"},
           {"text": "; the catalysts tested number "},
           {"sql": "SELECT count(*) AS n FROM cells WHERE col_no = 1 AND NOT is_header", "column": "n", "fmt": "int"},
           {"text": ". See ", "support": [{"atom": "p1.L4", "quote": "were both tested"}]}, {"figure": "p2.F1"},
           {"text": "."})
    assert c.text == ("Over Ni-20[1] the yield was 91.0[2] percent, the best in Table 1[3]; the catalysts tested "
                      "number 3[4]. See[5] Fig. 1[6].")
    kinds = [x["kind"] for x in c.citations]
    assert kinds == ["quote", "quote", "table", "computed", "support", "figure"]
    assert c.citations[1]["source"]["column_header"] == "Yield (%)"
    assert c.citations[3]["strength"] == "computed from verbatim" and c.citations[3]["n_sources"] == 3


def test_numbers_in_own_words_are_refused_with_the_moves(con):
    c = answer.check({"runs": [{"text": "the yield was 91.0 percent"}]}, con)
    assert [r.rule for r in c.refusals] == ["text:number"]
    assert "quote run" in c.refusal_text()


def test_a_quote_may_not_cut_a_number_or_a_word(con):
    assert rules(con, {"quote": "1.0", "atom": "p1.T1.r3c2"}) == ["quote:absent"]     # out of 91.0
    assert rules(con, {"quote": "55", "atom": "p1.T1.r4c2"}) == ["quote:absent"]      # out of 1.55
    assert rules(con, {"quote": "5", "atom": "p1.T1.r4c2"}) == ["quote:absent"]       # out of 1.55
    assert rules(con, {"quote": "i-1", "atom": "p1.T1.r2c1"}) == ["quote:absent"]     # out of Ni-10
    assert rules(con, {"quote": "10", "atom": "p1.T1.r2c1"}) == ["quote:absent"]      # out of Ni-10
    c = ok(con, {"quote": "85.2", "atom": "p1.L2"})          # not in "85.2%" — but the table cell holds it
    assert c.citations[0]["source"]["atom"] == "p1.T1.r2c2"
    assert rules(con, {"quote": "3", "atom": "p1.L3"}) == ["quote:absent"]            # out of 3,45
    assert rules(con, {"quote": "45", "atom": "p1.L3"}) == ["quote:absent"]           # out of 3,45
    ok(con, {"quote": "85.2%", "atom": "p1.L2"})
    ok(con, {"quote": "350 °C", "atom": "p1.L2"})


@pytest.mark.parametrize("text,quote,holds", [
    ("yield 85.2% at", "85.2", False), ("yield 85.2% at", "85.2%", True),
    ("90–100 nm", "100 nm", False), ("90–100 nm", "90", False), ("90–100 nm", "90–100 nm", True),
    ("~98 nm", "98 nm", False), ("~98 nm", "~98 nm", True), ("pH 7.4 buffer", "7.4", True),
    ("ratio 1:2", "1", False), ("(n = 5)", "5", True), ("Co-5", "5", False),
])
def test_number_boundaries(text, quote, holds):
    assert answer._holds(text, quote) is holds


def test_you_quote_the_harness_locates(con):
    c = ok(con, {"quote": "Rate per kg: USD 3,45", "atom": "p1.L1"})
    assert c.citations[0]["source"]["atom"] == "p1.L3"
    assert c.citations[0]["source"]["relocated_from"] == "p1.L1"


def test_an_ambiguous_phrase_names_its_candidates(con):
    c = answer.check({"runs": [{"quote": "the rods", "atom": "p1.L1"}]}, con)
    assert c.refusals[0].rule == "quote:absent"
    assert "p2.L2" in c.refusal_text() and "p2.L3" in c.refusal_text()


def test_a_name_resolves_to_its_first_occurrence(con):
    c = ok(con, {"quote": "Ni-10", "atom": "p1.L1"}, {"text": " and "}, {"quote": "4-MPBA", "atom": "p1.L1"})
    assert c.citations[0]["source"]["atom"] == "p1.L2" and c.citations[0]["source"]["occurrences"] == 3
    assert c.citations[1]["source"]["atom"] == "p2.L2" and c.citations[1]["source"]["occurrences"] == 2
    # a number that occurs in several places still has to name its place
    assert answer._is_name("4-MPBA") and answer._is_name("Ni-10") and not answer._is_name("0.0034")
    assert not answer._is_name("the rods")


def test_a_refused_name_comes_back_with_its_quote(con):
    c = answer.check({"runs": [{"text": "We used 4-MPBA, as before."}]}, con)
    assert [r.rule for r in c.refusals] == ["text:number"]
    assert '{"quote": "4-MPBA", "atom": "p2.L2"}' in c.refusal_text() and "never shorten it" in c.refusal_text()


def test_an_absence_term_said_another_way_is_refused(con):
    c = answer.check({"runs": [{"text": "Nobody tested both.", "absent": ["tested both"]}]}, con)
    assert [r.rule for r in c.refusals] == ["absent:near"] and "p1.L4" in c.refusal_text()
    c = answer.check({"runs": [{"text": "Tumor targeting is not discussed.", "absent": ["tumors specific"]}]}, con)
    assert [r.rule for r in c.refusals] == ["absent:near"]        # across the line break, "spe-" + "cific"
    ok(con, {"text": "No dose regimen is given.", "absent": ["mg/kg", "dose regimen"]})


def test_figure_facts_and_ocr_lines_are_quotable_with_their_strength(con):
    c = ok(con, {"quote": "85.2%", "atom": "p2.F1.k1"}, {"quote": "350 °C", "atom": "p2.F1.o1"})
    assert c.citations[0]["strength"] == "model-read, ocr-confirmed"
    assert c.citations[0]["source"]["figure"] == "Fig. 1"
    assert c.citations[1]["strength"] == "ocr"


@pytest.mark.parametrize("fmt,shown", [("raw", "91.0"), ("int", "91"), ("fixed2", "91.00"), ("pct1", "9,100.0%")])
def test_formats(con, fmt, shown):
    c = ok(con, {"sql": "SELECT CAST(text AS DOUBLE) AS v FROM cells WHERE id = 'p1.T1.r3c2'", "column": "v", "fmt": fmt})
    assert c.text == f"{shown}[1]"


@pytest.mark.parametrize("doc", [
    None, [], {}, {"runs": []}, {"runs": "x"}, {"runs": [None]}, {"runs": [1, "a", []]},
    {"runs": [{"text": 5}]}, {"runs": [{"quote": None}]}, {"runs": [{"quote": "x", "atom": 7}]},
    {"runs": [{"sql": 5, "column": "x"}]}, {"runs": [{"sql": "SELECT text AS t FROM lines WHERE id='p1.L1'", "column": "t", "fmt": "%.2f"}]},
    {"runs": [{"sql": "SELECT text AS t FROM lines WHERE id='p1.L1'", "column": "t", "fmt": "int"}]},
    {"runs": [{"figure": ["p2.F1"]}]}, {"runs": [{"table": None}]}, {"runs": [{"text": "a", "support": "b"}]},
    {"runs": [{"text": "a", "support": [{"atom": "p1.L1"}]}]}, {"runs": [{"text": "a", "extra": 1}]},
    {"runs": [{"quote": "a" * 100000, "atom": "p1.L1"}]},
    {"runs": [{"text": "a", "absent": "mg"}]}, {"runs": [{"text": "a", "absent": [5]}]},
    {"runs": [{"text": "a", "absent": [""]}]}, {"runs": [{"text": "a", "absent": []}]},
])
def test_hostile_answers_are_refused_never_crash(con, doc):
    c = answer.check(doc, con)
    assert not c.ok and c.refusals and all(r.rule != "checker:error" for r in c.refusals), c.refusal_text()


def test_a_list_may_be_numbered_only_at_line_starts(con):
    ok(con, {"text": "Steps:\n1. heat\n2. cool\n"})
    ok(con, {"text": "Steps:\n"}, {"text": "1. heat"})
    assert rules(con, {"text": "Steps:"}, {"text": "1. heat"}) == ["text:number"]


def test_quotes_run_across_line_breaks(con):
    c = ok(con, {"quote": "specific to tumors", "atom": "p1.L5"},          # line-break hyphen dropped
           {"quote": "were spe-cific", "atom": "p1.L5"},                 # ... or kept
           {"quote": "PLGA/PLA blend", "atom": "p1.L6"})                 # a slash at a line end joins tight
    assert [x["source"].get("atoms") for x in c.citations] == [
        ["p1.L5", "p1.L6"], ["p1.L5", "p1.L6"], ["p1.L6", "p1.L7"]]
    c = ok(con, {"quote": "specific to tumors", "atom": "p1.L1"})          # relocated from a wrong line
    assert c.citations[0]["source"]["relocated_from"] == "p1.L1"


def test_a_quote_never_runs_down_a_table_column(con):
    # consecutive printed rows may be one wrapped cell or two table rows; the drawing does not say which
    assert rules(con, {"quote": "Ni-10 Ni-20", "atom": "p1.T1.r2c1"}) == ["quote:absent"]
    assert rules(con, {"quote": "143.47 ± 10.34 nm", "atom": "p1.T1.r2c3"}) == ["quote:absent"]
    c = ok(con, {"quote": "143.47 ±", "atom": "p1.T1.r2c3"}, {"text": " "}, {"quote": "10.34 nm", "atom": "p1.T1.r3c3"})
    assert c.text == "143.47 ±[1] 10.34 nm[2]"
    c = ok(con, {"quote": "10.34 nm", "atom": "p1.L1"})                     # a cell is still found when misnamed
    assert c.citations[0]["source"]["atom"] == "p1.T1.r3c3"


def test_a_search_reads_down_a_column_and_errs_toward_finding(con):
    c = answer.check({"runs": [{"text": "No error bars are given.", "absent": ["± 10.34"]}]}, con)
    assert [r.rule for r in c.refusals] == ["absent:found"]


def test_absent_is_a_search_that_finds_nothing(con):
    c = ok(con, {"text": "No dose is reported.", "absent": ["mg/kg", "dose regimen"]})
    assert c.text == "No dose is reported.[1]"
    assert c.citations[0]["kind"] == "search" and c.citations[0]["matches"] == 0
    assert c.citations[0]["terms"] == ["mg/kg", "dose regimen"]


def test_absent_refuses_a_term_the_document_contains(con):
    c = answer.check({"runs": [{"text": "There is no yield data.", "absent": ["YIELD"]}]}, con)
    assert [r.rule for r in c.refusals] == ["absent:found"] and "p1.L2" in c.refusal_text()
    c = answer.check({"runs": [{"text": "Nothing is said about specificity.", "absent": ["specific to"]}]}, con)
    assert [r.rule for r in c.refusals] == ["absent:found"]                   # found across the line break


def test_a_citation_mark_sits_before_a_trailing_line_break(con):
    c = ok(con, {"text": "Ni-20 was tested\n", "support": [{"atom": "p1.L4", "quote": "were both tested"}]})
    assert c.text == "Ni-20 was tested[1]\n"


def test_a_search_unifies_unicode_forms(con):
    # the document writes Greek mu; a search typed with the micro sign must still find it
    c = answer.check({"runs": [{"text": "No mass of siRNA is given.", "absent": ["\u00b5g"]}]}, con)
    assert [r.rule for r in c.refusals] == ["absent:found"] and "p1.L8" in c.refusal_text()


def test_a_number_after_an_unmapped_glyph_keeps_the_glyph():
    t = "the g-factors were (cid:0) 0.0151 and 0.0150"
    assert not answer._holds(t, "0.0151")            # the glyph may be its minus sign
    assert answer._holds(t, "(cid:0) 0.0151") and answer._holds(t, "0.0150")
