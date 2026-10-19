"""TypeSafe's Jev: a non-generative judge. It is given a passage ("state") and closed questions, and
returns, for each question, one of the offered options with probabilities. It never writes text, so
it can only choose among candidates the caller built from the document.

    POST https://api.typesafe.ai/v1/systemone   (Authorization: Bearer $JEV_API_KEY)

Question types used here:
    choice  {"instructions", "criteria": {label: description}}  -> choice, confidence, probabilities

Binary questions are asked as two-label choices, never as a free score, so that a re-run compares
DECISIONS (labels), not floating-point scores, which jitter in the second decimal between calls.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

URL = os.environ.get("JEV_URL", "https://api.typesafe.ai/v1/systemone")
MODEL = os.environ.get("JEV_MODEL", "jev-latest")
TIMEOUT_S = float(os.environ.get("JEV_TIMEOUT_S", 60))   # a self-hosted judge on a CPU may need longer
RETRIES = 4


class JevError(Exception):
    pass


def ask(state: str, questions: dict, model: str = MODEL) -> dict:
    """One call: the full response ({"model", "answers", "usage"}). Retries transient failures."""
    key = os.environ.get("JEV_API_KEY") or os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise JevError("no Jev credentials: set JEV_API_KEY")
    body = json.dumps({"state": state, "model": model, "questions": questions}).encode()
    last = None
    for attempt in range(RETRIES):
        req = urllib.request.Request(URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read()[:300]!r}"
            if e.code not in (408, 429) and e.code < 500:
                break                                   # a client error will not fix itself
        except (urllib.error.URLError, TimeoutError) as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(1.5 * (attempt + 1))
    raise JevError(f"Jev call failed: {last}")


def choice(instructions: str, labels: dict) -> dict:
    return {"type": "choice", "instructions": instructions, "criteria": labels}
