# Settled while grading the fresh-paper test

`GRADING.md` is frozen by hash with the plan, so these are kept here. Written after all 160 answers were graded blind
and before `grade.py unseal`; hashed with `grades.json` in `graded.sha256`. Each was applied to every letter alike.

- **N2. A table that disagrees with itself.** co2-capture Table 3 prints mole fractions (CO2 0.19, N2 0.71) and feed
  rates (7143 and 31,697 kmol/h; 314 and 888 t/h) that do not agree. The key took the mass feed rates (314 / 1202 =
  26.12%). An answer computing the mass share from the printed mole fractions and molar masses (8.36 / 28.24 = 29.6%)
  follows the paper's own numbers with right arithmetic: correct, as rules 20 and 28 treated values printed two ways.
  Both answers did so; notes carry `(N2)`.
- **Rule 3 where the named table holds the row.** wastewater-treatment/B1 "according to Table 8, ... BSA rejection of
  92% and FRR of about 87.9%": Table 8 prints that membrane's row with the 87.9% FRR; the 92% is in the text. Not a
  made-up source: correct. adsorption/T2 and co2-capture/T1 named a table that prints neither asked value (Table 4 for
  Table 3's values): wrong `[label]`, as rule 3 has it.
- **Rule 25 on an unasked conversion.** mass-transfer/X1: 14.8 mgO3/min right, then 14.8 mg / 47.998 g/mol =
  0.000309 mol/min (it is 0.000308). GRADING.md keeps rule 25 strict, so wrong; the note says so, and the report gives
  the count with it right.
