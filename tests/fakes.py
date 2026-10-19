"""A scripted stand-in for the Anthropic client: returns canned responses, records every request."""
from __future__ import annotations

import itertools
import json
from types import SimpleNamespace

_ids = itertools.count(1)


def text_response(text, stop_reason="end_turn"):
    return SimpleNamespace(id=f"msg_{next(_ids)}", stop_reason=stop_reason, stop_details=None,
                           content=[SimpleNamespace(type="text", text=text)],
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0))


def json_response(data):
    return text_response(json.dumps(data))


def tool_response(name, inp):
    return SimpleNamespace(id=f"msg_{next(_ids)}", stop_reason="tool_use", stop_details=None,
                           content=[SimpleNamespace(type="tool_use", id=f"tu_{next(_ids)}", name=name, input=inp)],
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0))


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(dict(kwargs, messages=list(kwargs.get("messages", []))))   # snapshot: the loop appends
        if not self.script:
            raise AssertionError("the fake client ran out of scripted responses")
        return self.script.pop(0)
