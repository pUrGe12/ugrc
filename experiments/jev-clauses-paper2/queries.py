"""Answer probes from a clause base alone: plain SQL over `measures`, no model.

The SQL is written by hand here, standing in for whatever turns a question into a query (a template or
a small model call; undecided). Every row printed carries its pointer: the line atoms, the sentence, and
the flags the door raised.

    python queries.py RUN_DIR
"""
import sys
from pathlib import Path

import duckdb

ROW = "SELECT m.id, m.text, m.lo, m.hi, m.unit, m.role, m.property, m.about, m.measured_by, m.quantity, m.atoms, m.flags"

PROBES = [
    ("B1", "What is the CD limit of detection for L. monocytogenes?",
     f"""{ROW} FROM measures m WHERE list_contains(m.about, 'L. monocytogenes') AND list_contains(m.measured_by, 'CD')
         AND (list_contains(m.quantity, 'LOD') OR m.property = 'detection limit')"""),
    ("F2", "What UV-vis limit of detection was reported for E. coli?",
     f"""{ROW} FROM measures m WHERE list_contains(m.about, 'E. coli') AND list_contains(m.measured_by, 'UV–vis')
         AND (list_contains(m.quantity, 'LOD') OR m.property = 'detection limit')"""),
    ("X1", "Is the CD LOD lower than UV-vis for every strain where both are reported, and by how much?",
     """WITH lod AS (SELECT * FROM measures WHERE role = 'result'
                     AND (list_contains(quantity, 'LOD') OR property = 'detection limit')),
             subject AS (SELECT DISTINCT unnest(about) AS s FROM lod)
        SELECT s AS subject, c.text AS cd, u.text AS uv_vis, c.lo < u.lo AS cd_lower,
               round(u.lo - c.lo, 6) AS difference, round(u.lo / c.lo, 3) AS ratio, c.atoms || u.atoms AS atoms
        FROM subject, lod c, lod u
        WHERE list_contains(c.about, s) AND list_contains(u.about, s)
          AND list_contains(c.measured_by, 'CD') AND list_contains(u.measured_by, 'UV–vis')
        ORDER BY s"""),
    ("B2", "Which bacterial strain had a viable count of 7.6 × 10^7 CFU/mL?",
     f"{ROW} FROM measures m WHERE m.lo = 7.6e7 AND m.unit = 'CFU/mL'"),
    ("B3", "Which strain had the highest viable count and which the lowest?",
     f"""({ROW} FROM measures m WHERE m.unit = 'CFU/mL' AND m.role = 'result' AND len(m.about) = 1
          ORDER BY m.lo DESC LIMIT 1)
         UNION ALL ({ROW} FROM measures m WHERE m.unit = 'CFU/mL' AND m.role = 'result' AND len(m.about) = 1
          ORDER BY m.lo ASC LIMIT 1)"""),
    ("B6", "What concentration range was used for the concentration-dependent identification?",
     f"{ROW} FROM measures m WHERE list_contains(m.quantity, 'OD600') AND m.lo < m.hi"),
    ("C2", "What was the average length of the AuNRs and of the HGNRs?",
     f"{ROW} FROM measures m WHERE list_contains(m.quantity, 'average length')"),
    ("C3", "What share of the total variance do the two discriminant factors account for?",
     f"{ROW} FROM measures m WHERE m.property = 'share' AND m.role = 'result'"),
    ("C4", "How many signals, bacteria and replicates made up the feature matrix?",
     f"{ROW} FROM measures m WHERE m.role = 'count'"),
    ("C6", "How much NaCl solution was added, and what final NaCl concentration did it reach?",
     f"""{ROW} FROM measures m WHERE m.sentence IN (SELECT sentence FROM measures
         WHERE list_contains(about, 'NaCl solution') AND property = 'amount')"""),
    ("F4", "What classification accuracy did the blind tests achieve on the ternary bacterial mixtures?",
     f"{ROW} FROM measures m WHERE m.property = 'accuracy'"),
    ("F5", "Why did the authors pick 120 μM 4-MPBA as the optimal concentration?",
     f"""{ROW} FROM measures m WHERE (list_contains(m.about, '4-MPBA') OR list_contains(m.quantity, '4-MPBA concentra-tion')
         OR list_contains(m.about, '4-MPBA-derived')) AND m.unit = 'μM'"""),
]


def main(run):
    db = duckdb.connect(str(Path(run) / "clauses.duckdb"), read_only=True)
    for pid, question, sql in PROBES:
        cur = db.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print(f"\n{pid}  {question}")
        if not rows:
            print("    no clause: nothing in the clause base answers this")
        for r in rows:
            d = dict(zip(cols, r))
            flags = d.pop("flags", None)
            print("    " + ", ".join(f"{k}={v}" for k, v in d.items() if v not in (None, [], "")))
            for f in flags or []:
                print(f"        flag: {f}")
    db.close()


if __name__ == "__main__":
    main(sys.argv[1])
