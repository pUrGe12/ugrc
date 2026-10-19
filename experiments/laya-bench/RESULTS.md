# Laya against Jev: the same clause-base bench and the pairing gate

**Question.** Can Laya (Convai Innovations' open, non-generative judge) replace Jev in ugrc? Measured three
ways: (1) the same questions Jev answered, decision by decision; (2) the pairing gate's yes/no questions,
against hand labels; (3) the whole clause base rebuilt with Laya as the judge, graded with the answer keys of
`experiments/jev-bench` and `experiments/jev-questions`, against Jev v8.

**Setup.** `laya` 0.4.11 from PyPI (`pip install "laya[serve]"`, its own venv `.venv-laya`, CPU torch), the
checkpoints of `convaiinnovations/laya` at revision 7b928d8: `english` (ModernBERT-large, 421M, 512 tokens)
and `multilingual` (mmBERT-base, 322M, 1,024 tokens). `laya-serve` on 127.0.0.1 with a bearer key: the same
`POST /v1/systemone` request and response as Jev, so ugrc needs no code change, only `JEV_URL`, `JEV_MODEL`
(the checkpoint) and, on a CPU, `JEV_TIMEOUT_S` (added to `ugrc/jev.py`; default unchanged). No GPU on this
machine: 0.5–1.5 s per call.

**What Laya's own model card says** (convaiinnovations/laya README, read 2026-10-19): the base checkpoints are
"near chance on typed-decisions zero-shot" (0.362 against Jev's 0.727 and a 0.461 majority baseline); the
0.766 headline is a checkpoint fine-tuned on that benchmark's training split; "Laya is a fast base to
specialise, not a zero-shot decision engine"; the English `noul` "can follow its option labels instead of the
state"; it ships over-confident and needs temperatures refitted. ugrc uses it zero-shot, so this bench
measures exactly the setting the card warns about.

## 1. The same questions, decision by decision (`agree.py`, `agree_report.py`)

400 of Jev's recorded clause-base requests (seeded sample over the 12 v8 bases), sent unchanged to Laya:

| | same decision as Jev | where Jev's confidence ≥ 0.8 | truncated requests |
|---|---|---|---|
| Laya english | 547/1187 = 0.46 | 373/781 = 0.48 | 0 |
| Laya multilingual | 538/1187 = 0.45 | 371/781 = 0.48 | 0 |

Agreement is not accuracy, but where the right answer is not in doubt Laya is wrong: of the 177 sentences
Jev read as affirmed, Laya English calls 102 "negated" (multilingual 100). The sentences of a research paper
are overwhelmingly affirmed. No request was truncated: the clause questions are short (median state ~180
characters), so the 512-token context is not the cause.

## 2. The pairing gate (`pairings.py`, `pairing_judges.py`)

Every pairing question Jev answered in the leads arms of `experiments/bench-leads` and
`experiments/bench-multistep`: 132 distinct ones (requests of refused submissions rebuilt with
`pairing.request`). Hand labels (`pairing-labels.json`) written before any Laya answer was seen: 113 right, 5
wrong (three pair a citation superscript "^35" with sulfur; "4 mA/cm² of the carbon nucleation layer"; "87
ppm of NMP"), 14 debatable. The gate accepts at yes ≥ 0.5.

| judge | right pairings accepted | wrong pairings refused | AUROC right vs wrong |
|---|---|---|---|
| Jev (recorded) | 99/113 | 5/5 | 0.95 |
| Laya english, noul (as the gate asks) | 112/113 | 0/5 | 0.59 |
| Laya english, two-option choice (the card's advice) | 113/113 | 0/5 | 0.30 |
| Laya multilingual, noul | 107/113 | 1/5 | 0.72 |
| Laya multilingual, two-option choice | 62/113 | 2/5 | 0.52 |

Laya English answers yes ≈ 0.82 to nearly everything (the label-following the card describes), so as a gate it
refuses nothing: it would have let all 5 wrong pairings through. Jev's cost is the other way: 14 right
pairings refused (each cost a turn, none an error). Only 5 wrong pairings exist in the set, so the refusal
column is small; the AUROC and the flat yes are the clearer signal.

## 3. The clause base rebuilt with Laya (`run_builds.sh`, graded by `experiments/jev-bench/grade.py`)

(in progress)

## Files

`agree.py` / `agree_report.py` + `agree-<checkpoint>.jsonl`; `pairings.py` + `pairings.json`,
`pairing-labels.json`, `pairing_judges.py` + `pairing-<checkpoint>.json`; `run_builds.sh`, `runs/<checkpoint>/`,
`run-<checkpoint>.log`.
