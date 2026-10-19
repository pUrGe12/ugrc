"""SQL over atoms, with every result traced back to the atoms it read.

Three things live here.

THE GATE. A query is one read-only SELECT (CTEs allowed) over the substrate's relations
(store.QUERYABLE). No table functions, no files, no DDL; the connection itself is read-only with
external access off, so this is the second lock, not the only one.

THE LITERAL BAN (from mesh). SQL may CHOOSE with any constant — `WHERE page = 6`,
`regexp_extract(text, '([0-9.]+) nm', 1)`, `round(x, 2)` — but may not put a number INTO a value:
`SELECT 42`, `amount*0 + 4200000`, `CASE WHEN ... THEN '85 %'` and `x / 1000` are refused. The only
numbers a value may contain are 0, 1 and 100; any other factor comes from the `consts` relation,
which is an atom like any other and shows up in the lineage.

WHY-PROVENANCE BY REWRITING (Perm/GProM, as mesh's freesql_lineage). Every relation the query
reads is wrapped to carry `[id] AS __prov`; every SELECT level adds a `__prov` column combining
its sources' (flattened over the group when it aggregates); scalar subqueries get a "twin" that
carries their rows' ids. The rewrite is then VERIFIED BY EXECUTION: the rewritten query's
original columns must reproduce the original query's rows. A rewriter bug therefore reads as a
refusal, never as a wrong source list. Shapes the rewrite cannot trace exactly (set operations,
window functions, IN/EXISTS subqueries, DISTINCT inside a subquery) are refused by name, with
the equivalent shape that it can trace.

Lineage is per ROW: a cited value's sources are the atoms that fed its row — exact for a
single-column read, a superset when one row carries several columns from different atoms.
"""
from __future__ import annotations

import json
import threading

import duckdb
import sqlglot
from sqlglot import exp

from ugrc.refusal import Refusal
from ugrc.store import CLAUSE_RELATIONS, QUERYABLE, has_clauses

PROV = "__prov"
UNIVERSAL_NUMBERS = (0.0, 1.0, 100.0)   # identity, unit and percent base: not facts about anything
MAX_SQL_BYTES = 20_000
SQL_TIMEOUT_S = 20.0
CITE_MAX_ROWS = 10_000                  # a cited query returning more rows is too broad to trace

_PREDICATES = tuple(c for c in (getattr(exp, n, None) for n in (
    "EQ", "NEQ", "GT", "GTE", "LT", "LTE", "Between", "In", "Is", "Like", "ILike", "SimilarTo",
    "RegexpLike", "RegexpILike", "NullSafeEQ", "NullSafeNEQ", "Glob")) if c is not None)
_TRANSPARENT = tuple(c for c in (getattr(exp, n, None) for n in ("Paren", "Cast", "TryCast")) if c)
# argument names under which a literal BECOMES (part of) the value, rather than steering how a
# value is read; and functions any of whose arguments flow into the value
_VALUE_ARGS = {"this", "expressions", "replacement", "true", "false", "default", "format",
               "fill_pattern", "separator"}
_VALUE_FUNCS = tuple(c for c in (getattr(exp, n, None) for n in (
    "Coalesce", "Greatest", "Least", "Concat", "ConcatWs", "If", "Case", "Array", "Struct",
    "Anonymous", "Repeat", "Pad", "DateAdd", "DateSub", "TimestampAdd", "TimestampSub",
    "DatetimeAdd", "DatetimeSub", "TsOrDsAdd", "Nvl2")) if c is not None)

ALLOWED_RELATIONS = ", ".join(QUERYABLE)


# ─────────────────────────── parsing and the gate ───────────────────────────

def _parse(sql: str) -> exp.Expression:
    if not isinstance(sql, str) or not sql.strip():
        raise Refusal("sql:empty", "the query is empty", ["send one SELECT statement"])
    if len(sql.encode()) > MAX_SQL_BYTES:
        raise Refusal("sql:size", f"the query is longer than {MAX_SQL_BYTES} bytes",
                      ["split it into smaller questions"])
    try:
        trees = [t for t in sqlglot.parse(sql, read="duckdb") if t is not None]
    except sqlglot.errors.SqlglotError as e:
        raise Refusal("sql:parse", f"the query does not parse: {str(e)[:400]}",
                      ["single quotes delimit text, double quotes delimit names; send one SELECT"])
    if len(trees) != 1:
        raise Refusal("sql:one-statement", f"{len(trees)} statements were sent", ["send exactly one SELECT"])
    tree = trees[0]
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        raise Refusal("sql:select-only", f"only SELECT is allowed, got {type(tree).__name__.upper()}",
                      ["the substrate is read-only: query it with SELECT"])
    return tree


def _check_relations(tree: exp.Expression, clauses: bool = False):
    """Every relation read must be one of the substrate's; `clauses` also admits the clause base's, which a
    looking query may read but a cited one may not (its rows are judgments, not the document)."""
    allowed = QUERYABLE + (CLAUSE_RELATIONS if clauses else ())
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            raise Refusal("sql:table-function", f"{t.sql(dialect='duckdb')[:120]} is not a relation of the substrate",
                          [f"read only these relations: {ALLOWED_RELATIONS}"])
        if t.args.get("db") or t.args.get("catalog"):
            raise Refusal("sql:qualified-name", f"{t.sql(dialect='duckdb')} names a schema or database",
                          [f"use the bare relation names: {ALLOWED_RELATIONS}"])
        if t.name.lower() in CLAUSE_RELATIONS and not clauses and t.name.lower() not in ctes:
            raise Refusal("sql:clause-base", f"{t.name} is the clause base: what a judge read from the prose, for "
                          "finding things; a value in the answer comes from the document itself",
                          ["quote the value from the atom its `atoms` column names: {\"quote\": \"<text>\", \"atom\": \"<id>\"}",
                           "or compute it over lines, cells or figure_facts"])
        if t.name.lower() not in allowed and t.name.lower() not in ctes:
            raise Refusal("sql:unknown-relation", f"there is no relation {t.name!r}",
                          [f"read only these relations: {', '.join(allowed)}"])


def _execute(con, sql: str, limit: int):
    """(columns, rows, truncated) — interrupted after SQL_TIMEOUT_S; engine errors become refusals."""
    timer = threading.Timer(SQL_TIMEOUT_S, con.interrupt)
    timer.start()
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(limit + 1)
    except duckdb.InterruptException:
        raise Refusal("sql:timeout", f"the query ran longer than {SQL_TIMEOUT_S:g}s",
                      ["narrow it: filter before joining, avoid cross joins of large relations"])
    except duckdb.Error as e:
        raise Refusal("sql:engine", f"DuckDB refused the query: {str(e).strip()[:600]}",
                      ["fix the query; DESCRIBE <relation> lists a relation's columns"])
    finally:
        timer.cancel()
    return cols, rows[:limit], len(rows) > limit


# ─────────────────────────── exploration ───────────────────────────

def _cell(v, width):
    if v is None:
        return "NULL"
    s = json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (list, dict)) else str(v)
    return s if len(s) <= width else s[:width] + f"…[+{len(s) - width} chars]"


def explore(con, sql: str, max_rows: int = 150, width: int = 400) -> str:
    """Run a looking query and return its rows as text. DESCRIBE <relation> is allowed too."""
    stripped = (sql or "").strip().rstrip(";")
    if stripped.lower().startswith("describe "):
        name = stripped[9:].strip().strip('"').lower()
        allowed = QUERYABLE + (CLAUSE_RELATIONS if has_clauses(con) else ())
        if name not in allowed:
            raise Refusal("sql:unknown-relation", f"there is no relation {name!r}",
                          [f"DESCRIBE one of: {', '.join(allowed)}"])
        cols, rows, _ = _execute(con, f'DESCRIBE "{name}"', 200)
        return "\n".join(f"{r[0]} {r[1]}" for r in rows)
    tree = _parse(sql)
    _check_relations(tree, clauses=has_clauses(con))
    cols, rows, more = _execute(con, sql, max_rows)
    out = [" | ".join(cols)] + [" | ".join(_cell(v, width) for v in r) for r in rows]
    if more:
        try:
            total = _execute(con, f"SELECT count(*) FROM ({sql.strip().rstrip(';')}) AS __all", 1)[1][0][0]
            out.append(f"... {total} rows in all; only the first {max_rows} are shown — narrow the query or page with OFFSET")
        except Refusal:
            out.append(f"... more than {max_rows} rows; only the first {max_rows} are shown — narrow the query")
    if not rows:
        out.append("(no rows)")
    return "\n".join(out)


# ─────────────────────────── the literal ban ───────────────────────────

def _owner(node) -> exp.Select | None:
    return node.find_ancestor(exp.Select)


def _is_parameter(lit: exp.Literal) -> bool:
    """True when the literal steers HOW a value is computed (a comparison operand, a regex pattern
    or group, a rounding digit count, a type parameter) rather than becoming part of the value."""
    child, node = lit, lit.parent
    while isinstance(node, _TRANSPARENT):
        if not isinstance(node, exp.Paren) and child.arg_key != "this":
            return True                                    # inside the cast's type, e.g. DECIMAL(10,2)
        child, node = node, node.parent
    if node is None:
        return False
    if isinstance(node, (exp.DataType, exp.DataTypeParam)) or isinstance(node, _PREDICATES):
        return True
    if isinstance(node, exp.Func) and not isinstance(node, _VALUE_FUNCS):
        return child.arg_key not in _VALUE_ARGS
    return False


def _literal_value(lit: exp.Literal):
    try:
        return float(lit.this)
    except (TypeError, ValueError):
        return None


def check_literals(tree: exp.Expression):
    """Refuse a number written into a value position of any SELECT's projection."""
    for sel in tree.find_all(exp.Select):
        for proj in sel.expressions:
            for lit in proj.find_all(exp.Literal):
                if _owner(lit) is not sel:
                    continue                               # a nested query's own projection checks it
                if lit.is_number:
                    if _literal_value(lit) in UNIVERSAL_NUMBERS or _is_parameter(lit):
                        continue
                    why = f"the number {lit.this} is written into the value {proj.sql(dialect='duckdb')[:160]!r}"
                elif lit.is_string and any(ch.isdigit() for ch in lit.this):
                    if _is_parameter(lit):
                        continue
                    why = f"the text {lit.sql(dialect='duckdb')!r} puts digits into the value {proj.sql(dialect='duckdb')[:160]!r}"
                else:
                    continue
                raise Refusal("sql:literal", why + " — a value may only carry numbers read from atoms", [
                    "read the number from the atom that holds it (e.g. regexp_extract over its text) instead of typing it",
                    "for a unit factor or physical constant, read it from consts: "
                    "(SELECT value FROM consts WHERE id = 'K.per_kilo')",
                    "0, 1 and 100 are allowed as written; constants in WHERE/ON (choosing) are always allowed"])


def _refuse_untraceable(tree: exp.Expression):
    if isinstance(tree, exp.SetOperation) or any(True for _ in tree.find_all(exp.SetOperation)):
        raise Refusal("lineage:set-operation", "UNION/INTERSECT/EXCEPT cannot be traced to one row's sources",
                      ["cite each branch as its own query"])
    for w in tree.find_all(exp.Window):
        raise Refusal("lineage:window", f"window function {w.sql(dialect='duckdb')[:120]!r} cannot be traced",
                      ["compute it with GROUP BY or a JOIN, or cite the rows it reads"])
    for node in tree.find_all(exp.In):
        if node.args.get("query") is not None:
            raise Refusal("lineage:in-subquery", "IN (SELECT ...) cannot be traced to the rows that matched",
                          ["write it as a JOIN on the same condition"])
    for node in tree.find_all(exp.Exists):
        raise Refusal("lineage:exists", "EXISTS (SELECT ...) cannot be traced to the rows that matched",
                      ["write it as a JOIN on the same condition"])
    for w in tree.find_all(exp.With):
        if w.args.get("recursive"):
            raise Refusal("lineage:recursive", "a recursive CTE cannot be traced", ["query without recursion"])
    for sel in tree.find_all(exp.Select):
        if sel is not tree and sel.args.get("distinct"):
            raise Refusal("lineage:inner-distinct", "DISTINCT inside a subquery cannot be traced",
                          ["use GROUP BY on the same columns instead of DISTINCT"])
        group = sel.args.get("group")
        if group is not None and group.args.get("all"):
            raise Refusal("lineage:group-by-all", "GROUP BY ALL hides the keys", ["name the GROUP BY columns"])
        if sel.args.get("qualify") is not None:
            raise Refusal("lineage:qualify", "QUALIFY filters on a window", ["filter with WHERE or HAVING"])
        for j in sel.args.get("joins") or []:
            if "NATURAL" in (j.args.get("method") or "").upper():
                raise Refusal("lineage:natural-join", "NATURAL JOIN joins on every same-named column",
                              ["write the join condition with ON"])


# ─────────────────────────── the rewrite ───────────────────────────

def _is_aggregate(sel: exp.Select) -> bool:
    if sel.args.get("group") is not None:
        return True
    return any(_owner(n) is sel for p in sel.expressions for n in p.find_all(exp.AggFunc))


def _exclude_prov(sel: exp.Select):
    """`*` and `t.*` must not pick up the sources' __prov columns."""
    for proj in sel.expressions:
        star = proj if isinstance(proj, exp.Star) else (
            proj.this if isinstance(proj, exp.Column) and isinstance(proj.this, exp.Star) else None)
        if star is not None:
            star.set("except_", list(star.args.get("except_") or []) + [exp.column(PROV)])


class _Rewriter:
    def __init__(self):
        self.n = 0

    def _alias(self, prefix):
        self.n += 1
        return f"__{prefix}{self.n}"

    def source(self, node, scope) -> str:
        """Make one FROM/JOIN item expose __prov; return the alias to read it through."""
        if isinstance(node, exp.Table):
            alias = node.args.get("alias")
            if alias is not None and alias.args.get("columns"):
                raise Refusal("lineage:column-alias", f"{node.sql(dialect='duckdb')} renames columns in its alias",
                              ["alias the columns in the SELECT list instead"])
            name, ref = node.name.lower(), node.alias_or_name
            if name in scope:
                return ref                                   # a CTE: already carries __prov
            wrapped = sqlglot.parse_one(f'SELECT *, [id] AS {PROV} FROM "{name}"', read="duckdb")
            sub = exp.Subquery(this=wrapped, alias=exp.TableAlias(this=exp.to_identifier(ref)))
            node.replace(sub)
            return ref
        if isinstance(node, exp.Subquery) and isinstance(node.this, exp.Select):
            if not node.alias:
                node.set("alias", exp.TableAlias(this=exp.to_identifier(self._alias("src"))))
            self.select(node.this, scope)
            return node.alias
        raise Refusal("lineage:source", f"{node.sql(dialect='duckdb')[:120]!r} is not a relation lineage can follow",
                      ["read from the substrate's relations, a CTE, or a (SELECT ...) subquery"])

    def select(self, sel: exp.Select, scope: set):
        scope = set(scope)
        with_ = sel.args.get("with_")
        if with_ is not None:
            for cte in with_.expressions:
                if not isinstance(cte.this, exp.Select):
                    raise Refusal("lineage:set-operation", "a CTE that is not a single SELECT cannot be traced",
                                  ["make each branch its own CTE and JOIN them"])
                self.select(cte.this, scope)
                scope.add(cte.alias_or_name.lower())
        from_ = sel.args.get("from_")
        if from_ is None:
            raise Refusal("lineage:no-source", "a SELECT without FROM reads no atom, so its value has no source",
                          ["read the value from the relation that holds it"])
        items = [from_.this] + [j.this for j in sel.args.get("joins") or []]
        scalars = [s for s in sel.find_all(exp.Subquery)
                   if _owner(s) is sel and not any(s is i for i in items)]
        refs = [self.source(i, scope) for i in items]
        parts = [f'coalesce("{r}".{PROV}, [])' for r in refs]
        for s in scalars:
            body = s.this.copy()
            if not isinstance(body, exp.Select):
                raise Refusal("lineage:set-operation", "a scalar subquery that is not a single SELECT cannot be traced",
                              ["make it a CTE and JOIN it"])
            self.select(body, scope)
            twin = self._alias("twin")
            parts.append(f"coalesce((SELECT flatten(list({twin}.{PROV})) FROM ({body.sql(dialect='duckdb')}) AS {twin}), [])")
        row = f"flatten([{', '.join(parts)}])"
        prov = f"list_distinct(flatten(list({row})))" if _is_aggregate(sel) else row
        _exclude_prov(sel)
        sel.append("expressions", exp.alias_(sqlglot.parse_one(prov, read="duckdb"), PROV))


def trace_sql(sql: str) -> str:
    """The lineage-carrying rewrite of a citable query (raises Refusal when it cannot be traced)."""
    tree = _parse(sql)
    _check_relations(tree)
    _refuse_untraceable(tree)
    check_literals(tree)
    tree = tree.copy()
    _Rewriter().select(tree, set())
    return tree.sql(dialect="duckdb")


def _key(row) -> str:
    return repr(tuple(row))


def cited_value(con, sql: str, column: str, row: int = 0):
    """(value, source atom ids, output columns) for one cell of a citable query's result.
    Every failure is a Refusal naming the rule and the legal move."""
    rewritten = trace_sql(sql)
    cols, rows, more = _execute(con, sql, CITE_MAX_ROWS)
    if more:
        raise Refusal("sql:too-broad", f"the query returns more than {CITE_MAX_ROWS} rows",
                      ["aggregate or filter so the cited value comes from a small result"])
    if not isinstance(column, str) or column not in cols:
        raise Refusal("cite:column", f"the result has no column {column!r}; its columns are {cols}",
                      ["set column to one of the result's column names (alias the expression with AS)"])
    if not isinstance(row, int) or isinstance(row, bool) or not 0 <= row < len(rows):
        raise Refusal("cite:row", f"row {row!r} does not exist; the result has {len(rows)} row(s) (0-based)",
                      ["cite an existing row, or filter so the value is in row 0"])
    if len(rows) > 1 and not _parse(sql).args.get("order"):
        raise Refusal("cite:unordered", f"the result has {len(rows)} rows and no ORDER BY, so row {row} is not stable",
                      ["add an ORDER BY, or filter the result down to the one row you cite"])
    ci = cols.index(column)
    value = rows[row][ci]
    if value is None:
        raise Refusal("cite:null", f"the cited value is NULL", ["cite a cell that holds a value"])
    rcols, rrows, _ = _execute(con, rewritten, CITE_MAX_ROWS * 4)
    if rcols[:-1] != cols or rcols[-1] != PROV:
        raise Refusal("lineage:shape", "the traced query does not reproduce the query's columns",
                      ["simplify the query (name every column explicitly)"])
    sources = set()
    want = _key(rows[row])
    for r in rrows:
        if _key(r[:-1]) == want:
            sources.update(r[-1] or [])
    if not any(_key(r[:-1]) == want for r in rrows):
        raise Refusal("lineage:mismatch", "the traced query did not reproduce the cited row",
                      ["make ORDER BY total (add a tiebreaker such as id) or simplify the query"])
    if not sources:
        raise Refusal("lineage:unsourced", "the cited value was computed from no atom",
                      ["compute the value from the atoms that hold its inputs"])
    return value, sorted(sources), cols
