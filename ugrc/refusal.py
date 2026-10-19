"""A door's "no": the rule, where it happened, why, and the legal moves — rendered whole.

Every check in ugrc says no this way. A refusal is read by a model that has to fix one spot, so
it leads with the cause, never truncates it, and always names what would be accepted instead.
"""
from __future__ import annotations


class Refusal(Exception):
    def __init__(self, rule: str, why: str, moves: list[str] | None = None, where: str | None = None):
        super().__init__(rule)
        self.rule = rule
        self.why = why
        self.moves = list(moves or [])
        self.where = where

    def render(self) -> str:
        head = f"[{self.rule}]" + (f" at {self.where}" if self.where else "")
        return "\n".join([f"{head} {self.why}"] + [f"  -> {m}" for m in self.moves])

    def to_json(self) -> dict:
        return {"rule": self.rule, "where": self.where, "why": self.why, "moves": self.moves}

    def __str__(self) -> str:
        return self.render()
