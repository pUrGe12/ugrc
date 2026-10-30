# Facts plus prose: plan

Written 2026-10-30, before any answer of this arm exists. Asked by the user ("try 1"): add to the condensed clause base
the few number-free sentences that best match the question, to win back what the facts form loses.

## Why

In the ChemE test (`experiments/cheme/`) the facts form tied the pasted PDF (297 against 294 of 444) at about a third
of its length, but trailed it on chained questions (22 against 40 of 45). Its losses there sit in sentences that state
no value: an algorithm's name, whose parameters a model used, what a clone is derived from, a list of causes. The facts
form leaves those sentences out, and Llama then says the paper does not say.

This idea came from reading those losses, on these same 148 questions. So this is not a held-out test: a gain on the
chained questions is expected by construction. What it can show is whether adding sentences costs anything elsewhere,
and how far the facts form then gets against the pasted PDF. A held-out check, if the arm looks worth it, needs new
questions.

## The arm

`llama-facts-prose`: the facts form of the ChemE test (`scaling.condensed(con, "facts")`) with, added in their place in
page order, the top sentences without a value ranked by BM25 against the question:

- candidates: the clause base's sentences that the facts form leaves out (no value Jev reads as other than an
  identifier);
- ranking: `hybrid.bm25`'s formula (k1 = 1.5, b = 0.75) over the candidates, the question as the query; only sentences
  with a score above 0;
- amount: up to 30 sentences and 5,000 characters (about 1.4k tokens), taken in rank order, a sentence that would pass
  5,000 characters skipped;
- prompt: the facts arm's, with its description of the document changed to say the few best-matching other sentences
  are included.

With no sentence added the document is byte for byte the facts form (checked by `run.py check`).

Everything else as in the ChemE test: the 148 frozen questions (`../cheme/probes.json`, `../new6/probes.json`), the
v5 stores (`runs/cheme`, `runs/new6-v5`), Llama 3.1 8B on the Modal server with the same sampling, one free reply, three
runs.

## Grading

Blind to arm: each question's 6 answers (this arm's three and the facts arm's three, `../cheme/answers/llama-facts-r*`)
under letters shuffled by a fixed seed, graded by the ChemE rules (`../cheme/GRADING.md`, rules 1-23), grades hashed
before unsealing. The facts answers are graded a second time this way; set against their ChemE grades, that measures
the grader's drift.

## Reported

- Primary: facts+prose against facts, right answers summed over the three runs, paired sign-flip test over the 148
  questions (both graded in this test).
- Then: by category (chained expected to gain; false premises and absences watched for loss), by paper, new6 against
  ChemE; against the pasted PDF and the hybrid using their ChemE grades (graded in an earlier session: a looser
  comparison); prompt sizes; whether the sentence each chained loss needed was among those added; Modal cost.
