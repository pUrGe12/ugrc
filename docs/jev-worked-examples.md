# When the clause base earns its place, and when it doesn't

Two worked examples, both real, both reproducible from the committed runs. They are the concrete
reference for what a non-generative judge (Jev) buys us and what it costs.

The shared idea: **a clause's arguments are spans the paper already contains.** Code finds every
candidate; the layout decides what it can; Jev only *chooses* among what it is offered. It cannot write
an argument, so it cannot invent one. It can only pick a wrong one.

---

## Case A — Jev is load-bearing

**Run:** `experiments/jev-clauses-paper2/run1` (paper 2, Liu et al., Chem. Eng. J. 549 (2026) 182243)
**Question:** *What is the CD limit of detection for L. monocytogenes?*

### The sentence (`p6.L59:19`, atoms `p6.L59`–`p6.L61`)

> P. aeruginosa had an LOD of OD600 =**0.0034** (CD, Fig. S17a) versus **0.0066** (UV–vis, Fig. S17b),
> while L. monocytogenes presented an LOD of **0.0123** (CD, Fig. S17c) versus **0.0125** (UV–vis, Fig. S17d).

Four values, two strains, two methods, one sentence. Both strains are equally present in the text. The
question's answer depends entirely on which number belongs to which organism.

### What the deterministic rules settle on their own

For `0.0123`, `structural_bindings` returns:

| term | role | why |
|---|---|---|
| `LOD` | quantity | the words before "of" the value |
| `CD` | bound | in parentheses right after the value |

For `0.0034` it additionally gets `OD600` as a quantity, from the `KEY =value` rule.

So layout gives the quantity and says *that* CD is attached — but not **which strain owns the value**, and
not **how** CD is attached (method, or the thing measured?). Those are the gaps.

### What Jev decided (one call, 1,790 input / 508 output tokens)

Every question is a choice among spans the code already found:

| question | choice | probabilities |
|---|---|---|
| How is "**L. monocytogenes**" related to [[0.0123]]? | **about** | about **0.98**, measured by 0.02 |
| How is "**P. aeruginosa**" related to [[0.0123]]? | **unrelated** | unrelated **0.88**, about 0.11 |
| How is "**CD**" related to [[0.0123]]? | **measured by** | measured by **0.93**, about 0.07 |
| How is "**UV–vis**" related to [[0.0123]]? | **unrelated** | unrelated **0.96** |
| What kind of number is it? | result | 1.0 |
| What property? | detection limit | 0.96 |

**The first two rows are the irreducible judgment.** Choosing *L. monocytogenes* over *P. aeruginosa* for
this particular number is a reading decision no layout rule can make. Jev made it at 0.98/0.88, and made
the mirrored call for `0.0034` in the other direction.

### The resulting clause rows

```
0.0034 | about=[P. aeruginosa]            | by=[CD]     | qty=[LOD, OD600] | at=p6.L59
0.0066 | about=[P. aeruginosa, LOD, OD600]| by=[UV–vis] | qty=[]           | at=p6.L60
0.0123 | about=[OD600, L. monocytogenes]  | by=[CD]     | qty=[LOD]        | at=p6.L61
0.0125 | about=[LOD, OD600, L. monocytogenes] | by=[UV–vis] | qty=[]       | at=p6.L61
```

### The payoff: no model at answer time

```sql
SELECT text FROM measures
WHERE list_contains(about,'L. monocytogenes')
  AND list_contains(measured_by,'CD')
  AND (list_contains(quantity,'LOD') OR property='detection limit')
-- → 0.0123   (p6.L61)
```

All four strain/method pairings in this sentence are correct, and so are the 7 viable-cell counts
elsewhere in the paper. 10 of 12 probes were answered from the clause base by SQL alone.

### The cost, in the same example

Ask the comparison question and the weakness shows:

```sql
-- Is the CD LOD lower than UV–vis for every strain?
('L. monocytogenes', 0.0123, 0.0125, lower=True,  1.02)   ✓
('P. aeruginosa',    0.0034, 0.0066, lower=True,  1.94)   ✓
('OD600',            0.0123, 0.0066, lower=False, 0.54)   ✗ spurious
('OD600',            0.0123, 0.0125, lower=True,  1.02)   ✗ spurious
```

`OD600` is a unit-like quantity name that Jev also marked `about` on two of the four rows. One bad binding
produces two false pairs, one of which claims CD is *not* lower. **A wrong binding made once is inherited
by every query over it.** That is the structural cost of reading a paper only once.

---

## Case B — Jev contributes nothing, and why

**Run:** `runs/paper3/clauses` (paper 3, Wang et al., Chem. Eng. J. 549 (2026) 182355, a review)
**Question:** *Which strain reached 11.4 g/L prodigiosin, how was it obtained, and in what fermentation scale?*

### What actually answered it

The Claude question loop, in 5 tool calls with no door refusals, reading `atoms.duckdb`. It returned R82,
evolved from SDSPY-136 over 120 generations, 5 L fed-batch, 830 genes — and flagged a genuine
text/table contradiction (text says "5 L fed-batch"; Table 2 row says "shake flask", 48 h).

**The clause base played no part.** The three tools are `sql`, `view_figure`, `submit_answer`, and the SQL
tool connects to `atoms.duckdb`. `clauses/clauses.duckdb` is a separate file that nothing in the answering
path reads. Zero of the 29 paper-3 answers reference a clause.

### What the clause base holds for the same sentence (`p9.L20:21`)

> In 5 L fed-batch fermentation, R82 reached 11.4 g L^(cid:0) 1 prodigiosin (~double the original strain),
> with transcriptomic analysis revealing global reprogramming of 830 genes…

| clause | unit | about | flags |
|---|---|---|---|
| `11.4 g` | `g` | prodigiosin, "transcriptomic analysis revealing global reprogramming" | quantity withheld |
| `5 L` | `L` | — | a setting about nothing named |
| `1` | — | prodigiosin | — |
| `120` | — | SDSPY-136, generations | quantity withheld |
| `830` | — | genes, SDSPY-136 | bound across sentences |

**The question cannot be answered from this.** It asks *which strain*, and `R82` appears in no `about`
list. Three defects, in order of severity:

1. **`R82` was never offered as a candidate.** `clauses._is_term` requires **two or more capital letters**:

   | token | is_term | capitals |
   |---|---|---|
   | `R82` | **False** | 1 |
   | `H32` | **False** | 1 |
   | `G12` | **False** | 1 |
   | `P6` | **False** | 1 |
   | `MG1` | True | 2 |
   | `SN3` | True | 2 |
   | `HBQA7` | True | 4 |
   | `SDSPY-136` | True | 5 |

   Half this paper's strain names are invisible to the candidate generator. Jev can only choose from what
   it is given, so this is not a judge error — it is a one-line generator bug.

2. **The unit is `g`, not `g/L`.** The journal renders the exponent minus as an unmapped glyph
   (`mg L^(cid:0) 1` = `mg L⁻¹`), and the unit regex stops at it. **35 of 156 measures** on this paper have
   a truncated unit. Values and pointers stay correct; units do not.

3. **`1` is a phantom clause.** The `1` of `L^(cid:0) 1` became a measured value in its own right, role
   `result`, property `concentration`, about `prodigiosin`. Pure noise manufactured by the typesetting.

### The fourth defect: tables

**0 of 156 measures come from a table cell.** `clauses.blocks()` reads only the `lines` relation. For
paper 2 that cost nothing (no tables). For a review it is fatal: Table 2's 27 titers — the densest numeric
content in the article — are absent, so the clause route cannot answer any of the five table probes. The
Claude loop reads them fine (17 table citations, 20 SQL computations).

---

## What the two cases establish

| | Claude loop | clause base |
|---|---|---|
| model runs | every question | once per paper |
| cost | ~10¢ per question (paper 3: $3.05 / 29) | ~1–2¢ per paper, then free (paper 3: $0.018 for 541 calls) |
| reproducible | no | 1,123 of 1,138 decisions identical on re-run; every flip a near tie (max winning p 0.58) |
| can invent an argument | no (door blocks it) | structurally impossible — it only selects spans |
| covers tables | yes | **no** |
| covers prose values | yes | yes, where candidates are offered |

**Use the clause base when** the facts are in prose, the question is a lookup or a filter over
subject/method/quantity, and you will ask many questions of one paper. Case A is the shape that works.

**Do not rely on it when** the facts are in tables, the entity names are short strain codes, or the
question is a comparison over rows whose bindings have not been confirmed. Case B is the shape that fails.

**Three fixes would turn Case B into Case A**, in priority order:
1. extend `blocks()` to table rows, so cells become clauses;
2. widen `_is_term` so a single capital followed by digits (`R82`, `H32`) is a candidate;
3. treat `^(cid:N) 1` after a unit as an exponent, killing both the truncated unit and the phantom `1`.

None changes what Jev does. All three change what it is **offered** — which both cases show is the
binding constraint, not the judge's accuracy.
