"""The SQL gate, the literal ban and why-provenance — including hostile queries."""
import pytest

from ugrc import lineage
from ugrc.refusal import Refusal


def value(con, sql, col, row=0):
    v, src, _ = lineage.cited_value(con, sql, col, row)
    return v, src


def refused(con, sql, col="x", row=0):
    with pytest.raises(Refusal) as e:
        lineage.cited_value(con, sql, col, row)
    return e.value.rule


def test_a_read_traces_to_the_one_cell(con):
    v, src = value(con, "SELECT text AS t FROM cells WHERE id = 'p1.T1.r2c2'", "t")
    assert v == "85.2" and src == ["p1.T1.r2c2"]


def test_a_join_traces_to_both_cells(con):
    sql = ("SELECT y.text AS y FROM cells y JOIN cells c ON c.table_id = y.table_id AND c.row_no = y.row_no "
           "WHERE c.col_no = 1 AND y.col_no = 2 AND c.text = 'Ni-20'")
    assert value(con, sql, "y") == ("91.0", ["p1.T1.r3c1", "p1.T1.r3c2"])


def test_an_aggregate_traces_to_every_row_it_folded(con):
    v, src = value(con, "SELECT max(CAST(text AS DOUBLE)) AS m FROM cells WHERE col_no = 2 AND NOT is_header", "m")
    assert v == 91.0 and src == ["p1.T1.r2c2", "p1.T1.r3c2", "p1.T1.r4c2"]


def test_a_scalar_subquery_constant_appears_in_the_lineage(con):
    sql = ("SELECT CAST(text AS DOUBLE) / (SELECT value FROM consts WHERE id = 'K.per_kilo') AS g "
           "FROM cells WHERE id = 'p1.T1.r2c2'")
    v, src = value(con, sql, "g")
    assert v == pytest.approx(0.0852) and src == ["K.per_kilo", "p1.T1.r2c2"]


def test_ctes_and_derived_tables_and_star(con):
    v, src = value(con, "WITH c AS (SELECT * FROM cells WHERE col_no = 2) SELECT count(*) AS n FROM (SELECT * FROM c) s", "n")
    assert v == 4 and len(src) == 4
    v, src = value(con, "SELECT * FROM figures WHERE id = 'p2.F1'", "label")
    assert v == "Fig. 1" and src == ["p2.F1"]


def test_regex_parameters_are_choosing_not_values(con):
    sql = "SELECT CAST(regexp_extract(text, '([0-9.]+)%', 1) AS DECIMAL(10,2)) AS y FROM lines WHERE id = 'p1.L2'"
    v, src = value(con, sql, "y")
    assert float(v) == 85.2 and src == ["p1.L2"]


@pytest.mark.parametrize("sql", [
    "SELECT 42 AS x FROM lines LIMIT 1",
    "SELECT count(*) * 0 + 4200000 AS x FROM lines",
    "SELECT count(*) / 1000 AS x FROM lines",
    "SELECT CASE WHEN page = 1 THEN '85 %' END AS x FROM lines WHERE id = 'p1.L1'",
    "SELECT text || ' 98' AS x FROM lines WHERE id = 'p1.L1'",
    "SELECT concat(text, '98') AS x FROM lines WHERE id = 'p1.L1'",
    "SELECT replace(text, 'Results', '98') AS x FROM lines WHERE id = 'p1.L1'",
    "SELECT coalesce(NULL, 98) AS x FROM lines WHERE id = 'p1.L1'",
    "SELECT lpad('', 2, '98') AS x FROM lines WHERE id = 'p1.L1'",
    "WITH k AS (SELECT 98 AS v FROM lines) SELECT max(v) AS x FROM k",
])
def test_the_literal_ban(con, sql):
    assert refused(con, sql) == "sql:literal"


@pytest.mark.parametrize("sql,rule", [
    ("SELECT 1 AS x", "lineage:no-source"),
    ("SELECT text AS x FROM lines UNION SELECT text FROM cells", "lineage:set-operation"),
    ("SELECT rank() OVER (ORDER BY page) AS x FROM lines", "lineage:window"),
    ("SELECT count(*) AS x FROM cells WHERE table_id IN (SELECT id FROM tables)", "lineage:in-subquery"),
    ("SELECT count(*) AS x FROM cells WHERE EXISTS (SELECT 1 FROM tables)", "lineage:exists"),
    ("SELECT count(*) AS x FROM (SELECT DISTINCT col_no FROM cells) s", "lineage:inner-distinct"),
    ("SELECT * FROM read_csv('/etc/passwd')", "sql:table-function"),
    ("SELECT * FROM seals", "sql:unknown-relation"),
    ("SELECT * FROM main.lines", "sql:qualified-name"),
    ("DROP TABLE lines", "sql:select-only"),
    ("SELECT 1; SELECT 2", "sql:one-statement"),
    ("SELEC nonsense", "sql:select-only"),
    ("SELECT (", "sql:parse"),
    ("", "sql:empty"),
    (None, "sql:empty"),
])
def test_hostile_and_untraceable_queries_are_refused_by_name(con, sql, rule):
    assert refused(con, sql) == rule


def test_row_and_column_must_exist_and_be_stable(con):
    assert refused(con, "SELECT text AS t FROM cells WHERE col_no = 1", "t", 1) == "cite:unordered"
    assert refused(con, "SELECT text AS t FROM cells ORDER BY id", "t", 99) == "cite:row"
    assert refused(con, "SELECT text AS t FROM cells ORDER BY id", "nope") == "cite:column"
    assert refused(con, "SELECT region AS r FROM lines WHERE id = 'p1.L1'", "r") == "cite:null"
    v, _ = value(con, "SELECT text AS t FROM cells WHERE col_no = 1 ORDER BY id", "t", 1)
    assert v == "Ni-10"


def test_explore_looks_but_never_writes(con):
    out = lineage.explore(con, "SELECT id, text FROM cells WHERE col_no = 2 ORDER BY row_no")
    assert "p1.T1.r2c2 | 85.2" in out
    assert "id VARCHAR" in lineage.explore(con, "DESCRIBE cells")
    for bad in ("DELETE FROM lines", "SELECT * FROM read_text('/etc/hosts')", "DESCRIBE seals"):
        with pytest.raises(Refusal):
            lineage.explore(con, bad)
