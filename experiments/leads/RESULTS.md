# Leads and measure runs: Haiku, 71 questions

**Question.** Does a weak answering model do better when code hands it the clause base's matching rows with
each question (leads, `ugrc/leads.py`) and lets it show a clause-base value by id, with the machine copying
the value from its line (the measure run, door v4)?

**Run.** The same 71 questions as the two earlier Haiku runs: the 60 probes of `experiments/claude-capability`
(papers 2 and 3) and the professor's 11 over the 10-paper corpus (`experiments/prof-rag`). `claude-haiku-5-5`,
effort high, one fresh conversation per question; Jev answers the pairing gate. Answers in
`answers-haiku-leads/` of both experiments. Graded by the assistant against each probe's expected answer and
trap, written before any run, by the rubric of the earlier runs (a gap where a hidden support quote should be
shown is a format partial); `grades-haiku-leads.json`. Receipt GREEN for all 71.

## Results (`compare.py`)

| Haiku in the loop | correct | partial | wrong | refused | tools (median) | turns max | cost |
|---|---|---|---|---|---|---|---|
| plain | 58 | 13 | 0 | 88 | 6 | 13 | $0.26 |
| clause base attached | 64 | 6 | 1 | 93 | 6 | 10 | $0.26 |
| **leads + measure runs** | **55** | **14** | **2** | 92 | 6 | 8 | $0.26 |

**No arm is better than another on this evidence.** 27 of the 71 questions are graded differently in at least
one of the three runs, in every direction, and the arms differ by fewer answers than that. One run per arm
of a weak model cannot separate them; it needs several runs per arm.

## What worked

- **Measure runs were used and never failed.** 67 in 29 answers, zero `measure:*` refusals: every value
  shown that way is the paper's characters, from the line the clause base read it in.
- **The pairing gate caught real errors, for the first time.** 6 refusals, all right. In p2-F5 Haiku paired
  the 120, 165 and 225 μM sweep values with BA@L-HGNRs; the judge read them as 4-MPBA concentrations, the
  refusal named 4-MPBA, and the accepted answer pairs all four correctly. In p3-C4 a strain name was paired
  with "endogenous promoters". In the two earlier runs the gate never refused.
- At most 8 turns (13 and 10 before).

## What did not

- **Haiku still searches.** Only 3 of 71 answers came from the leads alone; median 6 tool calls, as before.
- **The format problem is untouched.** 10 of the 14 partials are gaps where a support quote is hidden ("it
  says that [1] economic justification"; p3-G1 hides 59.74%, r = 0.57 and p < 0.001). The plain run had 10
  too. Measure runs replace quote runs; the gaps come from `support` quotes, which they do not replace.
  `text:number` refusals: 151 (plain 160).
- **Leads can anchor the model on the prose.** prof-T1 ("how many cathodes are compared"): all 12 leads were
  prose sentences, since table cells are not in the clause base; Haiku searched only `sentences`, never
  `cells`, and answered with aenm-2022's four cathode classes, the RAG answer the professor marked wrong.
  The plain run counted ensm-2021 Table 4's 23 entries. prof-T2 (7 references, counted as reference-list
  lines) did not use its leads.

## Leads recall, no model (`ugrc/leads.py`)

Of the prose lines Opus's answers to the same questions cited, the share inside a sentence the leads show:
paper 2 88/128 (26 of 28 answers with a hit), paper 3 79/142 (20 of 21), 10-paper corpus 16/93 (6 of 11).

## What follows

1. **Fix the format in the door, not the model:** refuse a text run that leads into a hidden support quote
   (ends in ":", "that", "of", "=", …, or its support quote holds a number), with the move "show it as a
   quote run". That is 10 of this run's 14 partials, and 10 of the plain run's 13.
2. **Put table cells in the clause base (step 3)**, so the leads cover tables. Until then, say in the leads
   when a table's caption or headers match the question.
3. **Measure with repeated runs** (3+ per arm) before reading a difference of a few answers.

## Files

`compare.py`, `grades-haiku-leads.json`; answers in `experiments/claude-capability/answers-haiku-leads/` and
`experiments/prof-rag/answers-haiku-leads/`; logs `run-haiku-leads.log` beside them.
