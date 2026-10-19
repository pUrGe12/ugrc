"""Format gaps, found by code: a hidden citation (a support quote, or an absence search) whose mark stands where
the reader expects to see words, so the answer reads "it says that [1]" or "the LOD was OD600 =[3]".

    gaps(record) -> list of (n, the words before the mark)

A support quote stands behind the answerer's words; it is cited, not shown. That is right when the words say
the thing ("CD gave a lower LOD than UV-vis[1]"), and a gap when they only lead into it: the text before the
mark (and before any marks right ahead of it) ends in an opener (":", an opening quotation mark, "(", "=") or
in a lead-in word ("that", "is", "of", "at", ...), and what follows is not a shown quote that completes it
("is[4] 5 L fed-batch fermentation[5]" shows the words at [5]).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ugrc.answer import lead_in_gaps  # noqa: E402   the rule, as door v5 refuses it (text:lead-in)


def gaps(rec: dict) -> list[tuple[int, str]]:
    return lead_in_gaps(rec.get("rendered") or "", rec.get("citations") or [])
