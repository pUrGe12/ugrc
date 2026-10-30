"""A corpus: two papers' substrates read as one, with every id prefixed by its paper's key."""
import duckdb
import pytest

from tests import synth
from ugrc import answer, corpus, store


@pytest.fixture
def two(tmp_path):
    a = synth.make(tmp_path / "alpha")
    b = synth.make(tmp_path / "beta")
    out = corpus.build(tmp_path / "both", [b, a], log=lambda *_: None)
    return a, b, out


def test_every_id_carries_its_papers_key_and_documents_lists_the_papers(two):
    a, _, out = two
    con = store.connect_readonly(out)
    single = store.connect_readonly(a)
    assert con.execute("SELECT count(*) FROM atoms").fetchone()[0] == \
        2 * single.execute("SELECT count(*) FROM atoms WHERE kind <> 'const'").fetchone()[0] + 11
    assert con.execute("SELECT id FROM documents ORDER BY id").fetchall() == [("alpha",), ("beta",)]
    assert con.execute("SELECT text FROM atoms WHERE id = 'beta:p1.T1.r3c2'").fetchone()[0] == "91.0"
    assert con.execute("SELECT table_id, doc FROM cells WHERE id = 'alpha:p1.T1.r2c2'").fetchone() == ("alpha:p1.T1", "alpha")
    assert con.execute("SELECT figure_id FROM figure_facts WHERE id = 'alpha:p2.F1.k1'").fetchone()[0] == "alpha:p2.F1"
    assert corpus.is_corpus(con) and not corpus.is_corpus(single)


def test_the_door_cites_the_paper_and_never_runs_a_quote_across_papers(two):
    _, _, out = two
    con = store.connect_readonly(out)
    ok = answer.check({"runs": [{"quote": "91.0", "atom": "beta:p1.T1.r3c2"}]}, con)
    assert ok.ok and ok.citations[0]["source"]["doc"] == "beta"
    across = answer.check({"runs": [{"quote": "Particles were spe-cific to tumors", "atom": "alpha:p1.L5"}]}, con)
    assert across.ok and across.citations[0]["source"]["atoms"] == ["alpha:p1.L5", "alpha:p1.L6"]
    table = answer.check({"runs": [{"table": "alpha:p1.T1"}]}, con)
    assert table.ok and table.citations[0]["source"]["doc"] == "alpha"


def test_the_corpus_receipt_is_green_and_catches_a_changed_substrate(two):
    a, _, out = two
    assert all(ok for ok, _ in corpus.verify(out))
    db = duckdb.connect(str(store.db_path(a)))
    db.execute("UPDATE lines SET text = 'The yield was 95.2% at 350 °C over Ni-10.' WHERE id = 'p1.L2'")
    store.reseal(db, "extraction")
    db.close()
    bad = [m for ok, m in corpus.verify(out) if not ok]
    assert any("alpha: substrate seals CHANGED" in m for m in bad)


def test_a_corpus_is_built_once_and_needs_plain_keys(two, tmp_path):
    a, b, out = two
    with pytest.raises(SystemExit):
        corpus.build(out, [a, b], log=lambda *_: None)
    with pytest.raises(SystemExit):
        corpus.build(tmp_path / "x", [tmp_path / "missing"], log=lambda *_: None)


def test_the_small_prompt_has_a_corpus_form(two):
    # ask.system_prompt(con, "small") on a corpus: the documents listed, ids carry a document key in the made-up
    # example, every placeholder filled; no leads without a clause base
    from ugrc import ask
    _, _, out = two
    con = store.connect_question(out)
    s = ask.system_prompt(con, "small")
    assert "@" not in s and "a collection of 2 documents" in s
    assert "- alpha:" in s and "- beta:" in s and "### alpha" in s
    assert '"atom": "paper-a:p4.L22"' in s and "When the documents do not answer" in s
    assert "## Leads" not in s and '{"measure"' not in s
