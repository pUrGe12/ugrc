# Pointers for numbers on the winning setup: frozen plan

Written 2026-11-01, frozen by hash (`frozen.sha256`: this plan and `check.py`) before the checker ran on any of these
answers.

## The question

The winning setup (search picks the paper, then Llama answers freely from its facts+prose form) gave up ugrc's
original promise that every number in an answer points into the paper. The user asked to bring that back with the
best setting. Two parts:

1. **This test: pointers and the checker after the answer.** No new answers. For each number in a graded answer,
   code finds the passages of the paper that print it (its pointer), and Jev judges whether the passage gives that
   number for what the answer says. A number printed nowhere passes only if the answer writes out arithmetic that
   yields it, or one step over the answer's other numbers does.
2. **Separately (`../door-routed/`): the door itself**, where the model must write the pointers.

## What runs

`../jev-check/check.py`, unchanged (hash `3b4bf71c…`, its own `frozen.sha256`), on:

| set | answers | graded in |
|---|---|---|
| `fresh` | the 80 top1 answers (10 unseen papers among 120) | `../fresh/hand.json` |
| `big` | the 388 top1 answers on the 120-paper library | `../big-library/hand.json` |

Each answer is checked against the paper search picked for it (`routed`), as a deployed system would: it does not
know the question's paper. 7 of the 388 were misrouted. The checker's passages are the paper's clause-base
sentences, its table rows (caption and column names first) and its figure facts. Jev replies are cached in
`jev_cache.jsonl` here. The checker has not seen these answers: it was built on `dev` and tested once on `test`
(the hybrid's answers).

## What gets reported

- **Pointers:** numbers per answer; the share printed in the paper (given a pointer), recomputed from written
  arithmetic, derived from the answer's other numbers, or printed nowhere.
- **The checker against the blind grades:** passed / flagged / no claim × right / partial / wrong.
- **What a user would get** if flagged answers are held back and shown as unchecked: of the answers delivered, the
  share right and the share wrong, against all answers; the right answers held back.
- Per set. Earlier: wrong answers delivered 19% → 8% (bench hybrid), holding back 22–32% of right answers.
