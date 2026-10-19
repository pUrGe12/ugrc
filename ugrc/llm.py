"""The one place a model is called.

Claude through the official SDK by default. Credentials resolve the SDK's way: ANTHROPIC_API_KEY, or an
`ant auth login` profile. Server-side refusal fallback is on (a declined request is re-run on Anthropic's
recommended fallback model inside the same call); a refusal that survives it is raised by name, never read as
an answer.

With UGRC_LLM_URL set (an OpenAI-compatible server, e.g. llama.cpp's `llama-server --jinja`, at
http://127.0.0.1:8090/v1), the same calls go to an open model instead: the request ugrc builds in the Messages
API's shape (system, tools, content blocks, tool_use / tool_result) is translated to chat completions and the
reply back into the same blocks, so the loop in ask.py does not change. Images (view_figure) are replaced by a
note: a text-only model sees the figure's caption and facts, not its pixels. One encoding quirk of small models
is undone (decode_nested: an array argument sent as a string of JSON) and counted in the record, never hidden.
"""
from __future__ import annotations

import ast
import json
import os
import urllib.error
import urllib.request
from types import SimpleNamespace

MODEL = os.environ.get("UGRC_MODEL", "claude-opus-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
LLM_URL = os.environ.get("UGRC_LLM_URL")
# Sampling for an open model, from its own generation config when it ships one (Llama 3.1: 0.6 / 0.9)
TEMPERATURE = float(os.environ.get("UGRC_TEMPERATURE", 0.6))
TOP_P = float(os.environ.get("UGRC_TOP_P", 0.9))
MAX_OUTPUT = int(os.environ.get("UGRC_MAX_OUTPUT", 4096))
TIMEOUT_S = float(os.environ.get("UGRC_LLM_TIMEOUT_S", 1800))
NO_IMAGE = "[an image was here; this model reads text only]"
UNREADABLE = "does not match the expected"     # llama.cpp: the model's output fits neither text nor its tool-call format
UNREADABLE_NOTE = "[this reply could not be read as text or as a tool call]"


class ModelRefused(Exception):
    pass


class OpenAIChat:
    """A chat-completions endpoint that speaks for the Messages API in create()."""

    def __init__(self, url: str, key: str | None = None):
        self.url = url.rstrip("/") + "/chat/completions"
        self.key = key


def client():
    if LLM_URL:
        return OpenAIChat(LLM_URL, os.environ.get("UGRC_LLM_KEY"))
    import anthropic
    return anthropic.Anthropic()


def create(cl, **kwargs):
    """One Messages API call (or its translation). Raises ModelRefused when the whole fallback chain declined."""
    if isinstance(cl, OpenAIChat):
        return _openai_create(cl, **kwargs)
    resp = cl.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
    if resp.stop_reason == "refusal":
        details = getattr(resp, "stop_details", None)
        cat = getattr(details, "category", None) if details else None
        raise ModelRefused(f"the model declined the request (category: {cat})")
    return resp


def text_of(resp) -> str:
    return "".join(b.text for b in resp.content if b.type == "text")


# ─────────────────────────── Messages API <-> chat completions ───────────────────────────

def _get(block, key, default=None):
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


def _text_of_content(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        kind = _get(b, "type")
        parts.append(_get(b, "text", "") if kind == "text" else NO_IMAGE if kind == "image" else "")
    return "\n".join(p for p in parts if p)


def to_openai(system, messages, tools) -> tuple[list, list]:
    """(chat messages, tools) for a Messages-API request."""
    out = [{"role": "system", "content": system if isinstance(system, str) else _text_of_content(system)}] if system else []
    for m in messages:
        content = m["content"]
        if m["role"] == "assistant":
            blocks = [content] if isinstance(content, str) else list(content)
            text = "".join(_get(b, "text", "") for b in blocks if not isinstance(b, str) and _get(b, "type") == "text")
            text += "".join(b for b in blocks if isinstance(b, str))
            calls = [{"id": _get(b, "id"), "type": "function",
                      "function": {"name": _get(b, "name"), "arguments": json.dumps(_get(b, "input") or {}, ensure_ascii=False)}}
                     for b in blocks if not isinstance(b, str) and _get(b, "type") == "tool_use"]
            if not text and not calls:                  # an empty turn: chat servers refuse a message with neither
                continue
            msg = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
            continue
        if isinstance(content, str):
            out.append({"role": "user", "content": content})
            continue
        texts = []
        for b in content:                              # tool results first, each its own message, then any text
            if _get(b, "type") == "tool_result":
                body = _text_of_content(_get(b, "content"))
                if _get(b, "is_error"):
                    body = "ERROR: " + body
                out.append({"role": "tool", "tool_call_id": _get(b, "tool_use_id"), "content": body})
            elif _get(b, "type") == "text":
                texts.append(_get(b, "text"))
            elif _get(b, "type") == "image":
                texts.append(NO_IMAGE)
        if texts:
            out.append({"role": "user", "content": "\n\n".join(texts)})
    fns = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                             "parameters": t["input_schema"]}} for t in tools or []]
    return out, fns


def from_openai(data: dict):
    """A Messages-API-shaped response (content blocks, stop_reason, usage) from a chat completion."""
    choice = data["choices"][0]
    msg = choice.get("message") or {}
    blocks = []
    if msg.get("content"):
        blocks.append(SimpleNamespace(type="text", text=msg["content"]))
    for k, call in enumerate(msg.get("tool_calls") or []):
        fn = call.get("function") or {}
        args = fn.get("arguments")
        try:
            inp = json.loads(args) if isinstance(args, str) else (args or {})
        except json.JSONDecodeError:
            inp = {"_unparsed_arguments": args}        # the tool or the door refuses it, with what it needs
        if not isinstance(inp, dict):
            inp = {"_unparsed_arguments": args}
        blocks.append(SimpleNamespace(type="tool_use", id=call.get("id") or f"call_{k}", name=fn.get("name"), input=inp))
    stop = {"tool_calls": "tool_use", "length": "max_tokens", "stop": "end_turn"}.get(choice.get("finish_reason"), "end_turn")
    if any(b.type == "tool_use" for b in blocks):
        stop = "tool_use"
    u = data.get("usage") or {}
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
    usage = SimpleNamespace(input_tokens=(u.get("prompt_tokens") or 0) - cached, output_tokens=u.get("completion_tokens") or 0,
                            cache_read_input_tokens=cached, cache_creation_input_tokens=0)
    return SimpleNamespace(id=data.get("id"), stop_reason=stop, stop_details=None, content=blocks, usage=usage,
                           model=data.get("model"), repairs=[])


def _literal(text):
    """The list or object a string holds, as JSON or as a Python literal (single quotes); None if neither."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        got = ast.literal_eval(text.strip())
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None
    try:
        return json.loads(json.dumps(got))             # only what JSON can hold (no sets, tuples become lists)
    except (TypeError, ValueError):
        return None


def decode_nested(resp, tools):
    """Undo one encoding quirk of small open models: an argument the tool's schema types as an array or object,
    sent as a string holding it (as JSON, or as a Python literal). Each one undone is listed in resp.repairs as "<tool>.<argument>"."""
    schemas = {t["name"]: t["input_schema"].get("properties", {}) for t in tools or []}
    for b in resp.content:
        if b.type != "tool_use":
            continue
        for name, val in list(b.input.items()):
            want = {"array": list, "object": dict}.get((schemas.get(b.name, {}).get(name) or {}).get("type"))
            if want and isinstance(val, str):
                got = _literal(val)
                if isinstance(got, want):
                    b.input[name] = got
                    resp.repairs.append(f"{b.name}.{name}")
    return resp


def _openai_create(cl: OpenAIChat, *, model, max_tokens, messages, system=None, tools=None, **_ignored):
    msgs, fns = to_openai(system, messages, tools)
    body = {"model": model, "messages": msgs, "max_tokens": min(max_tokens, MAX_OUTPUT),
            "temperature": TEMPERATURE, "top_p": TOP_P}
    if fns:
        body["tools"] = fns
    headers = {"Content-Type": "application/json"}
    if cl.key:
        headers["Authorization"] = f"Bearer {cl.key}"
    req = urllib.request.Request(cl.url, data=json.dumps(body).encode(), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return decode_nested(from_openai(json.loads(resp.read())), tools)
    except urllib.error.HTTPError as e:
        body = e.read()[:500]
        if e.code == 500 and UNREADABLE in body.decode(errors="replace"):
            # the model's own output could not be parsed (e.g. a tool call cut off at the output limit): a bad
            # turn of the model, not a failed server. The loop sees a text turn and asks for a submit_answer.
            resp = from_openai({"choices": [{"finish_reason": "stop", "message": {"content": UNREADABLE_NOTE}}]})
            resp.repairs.append("unreadable-reply")
            return resp
        raise RuntimeError(f"the model server answered HTTP {e.code}: {body!r}") from e
