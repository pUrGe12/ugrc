"""The open-model path of ugrc/llm.py: Messages-API requests translated to chat completions and back."""
from types import SimpleNamespace

from ugrc import llm

TOOLS = [{"name": "sql", "description": "Run a query.", "strict": True,
          "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}]


def test_a_conversation_is_translated_to_chat_messages():
    messages = [
        {"role": "user", "content": "What was the yield?"},
        {"role": "assistant", "content": [SimpleNamespace(type="text", text="Looking."),
                                          SimpleNamespace(type="tool_use", id="tu_1", name="sql", input={"query": "SELECT 1"})]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu_1", "content": "1 row", "is_error": False},
            {"type": "tool_result", "tool_use_id": "tu_2", "is_error": True,
             "content": [{"type": "image", "source": {}}, {"type": "text", "text": "Fig. 1 caption"}]},
            {"type": "text", "text": "Next question?"}]},
    ]
    msgs, fns = llm.to_openai("You answer questions.", messages, TOOLS)
    assert msgs[0] == {"role": "system", "content": "You answer questions."}
    assert msgs[1] == {"role": "user", "content": "What was the yield?"}
    assert msgs[2]["content"] == "Looking." and msgs[2]["tool_calls"][0]["function"] == {
        "name": "sql", "arguments": '{"query": "SELECT 1"}'}
    assert msgs[3] == {"role": "tool", "tool_call_id": "tu_1", "content": "1 row"}
    assert msgs[4] == {"role": "tool", "tool_call_id": "tu_2", "content": f"ERROR: {llm.NO_IMAGE}\nFig. 1 caption"}
    assert msgs[5] == {"role": "user", "content": "Next question?"}
    assert fns == [{"type": "function", "function": {"name": "sql", "description": "Run a query.",
                                                     "parameters": TOOLS[0]["input_schema"]}}]


def test_a_chat_completion_comes_back_as_content_blocks():
    resp = llm.from_openai({"id": "c1", "model": "llama", "choices": [{"finish_reason": "tool_calls", "message": {
        "content": None, "tool_calls": [
            {"id": "call_a", "type": "function", "function": {"name": "sql", "arguments": '{"query": "SELECT 2"}'}},
            {"id": "call_b", "type": "function", "function": {"name": "submit_answer", "arguments": '{"runs": [ broken'}}]}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30, "prompt_tokens_details": {"cached_tokens": 100}}})
    assert resp.stop_reason == "tool_use"
    assert [(b.type, b.name, b.input) for b in resp.content] == [
        ("tool_use", "sql", {"query": "SELECT 2"}), ("tool_use", "submit_answer", {"_unparsed_arguments": '{"runs": [ broken'})]
    assert (resp.usage.input_tokens, resp.usage.cache_read_input_tokens, resp.usage.output_tokens) == (20, 100, 30)
    text = llm.from_openai({"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]})
    assert text.stop_reason == "max_tokens" and llm.text_of(text) == "partial"


def test_the_client_follows_the_environment(monkeypatch):
    monkeypatch.setattr(llm, "LLM_URL", "http://127.0.0.1:8090/v1/")
    cl = llm.client()
    assert isinstance(cl, llm.OpenAIChat) and cl.url == "http://127.0.0.1:8090/v1/chat/completions"


def test_an_empty_model_turn_is_left_out():
    messages = [{"role": "user", "content": "Q?"}, {"role": "assistant", "content": []},
                {"role": "user", "content": "Only an answer sent through submit_answer reaches the user; submit it there."}]
    msgs, _ = llm.to_openai(None, messages, [])
    assert [m["role"] for m in msgs] == ["user", "user"]


def test_an_array_argument_sent_as_a_string_is_decoded_and_counted():
    tools = TOOLS + [{"name": "submit_answer", "description": "",
                      "input_schema": {"type": "object", "properties": {"runs": {"type": "array"}}}}]
    def reply(args):
        return {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [
            {"id": "c", "type": "function", "function": {"name": "submit_answer", "arguments": args}}]}}]}
    resp = llm.decode_nested(llm.from_openai(reply('{"runs": "[{\\"text\\": \\"No.\\"}]"}')), tools)
    assert resp.content[0].input == {"runs": [{"text": "No."}]} and resp.repairs == ["submit_answer.runs"]
    # a string that is not that JSON, and a string the schema asks for, are left as sent
    for args in ('{"runs": "[{broken"}', '{"runs": "{\\"text\\": \\"No.\\"}"}'):
        resp = llm.decode_nested(llm.from_openai(reply(args)), tools)
        assert isinstance(resp.content[0].input["runs"], str) and resp.repairs == []
    q = llm.decode_nested(llm.from_openai({"choices": [{"message": {"tool_calls": [
        {"id": "c", "function": {"name": "sql", "arguments": '{"query": "[1]"}'}}]}}]}), tools)
    assert q.content[0].input == {"query": "[1]"} and q.repairs == []


def test_a_python_literal_list_is_decoded_too_and_a_cut_one_is_not():
    tools = [{"name": "submit_answer", "description": "",
              "input_schema": {"type": "object", "properties": {"runs": {"type": "array"}}}}]
    def reply(runs):
        import json
        return {"choices": [{"message": {"tool_calls": [{"id": "c", "function": {
            "name": "submit_answer", "arguments": json.dumps({"runs": runs})}}]}}]}
    ok = llm.decode_nested(llm.from_openai(reply("[{'text': 'No.'}]")), tools)
    assert ok.content[0].input["runs"] == [{"text": "No."}] and ok.repairs == ["submit_answer.runs"]
    cut = llm.decode_nested(llm.from_openai(reply("[{'text': 'No.'}")), tools)
    assert cut.content[0].input["runs"] == "[{'text': 'No.'}" and cut.repairs == []


def test_the_door_says_when_runs_arrived_as_a_string():
    from ugrc import answer
    checked = answer.check({"runs": '[{"text": "No."}]'}, None)
    assert not checked.ok and "arrived as a string" in checked.refusals[0].why


def test_an_unreadable_model_reply_is_a_turn_not_a_server_failure(monkeypatch):
    import io
    import urllib.error
    def refuse(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 500, "x", {}, io.BytesIO(
            b'{"error":{"code":500,"message":"The model produced output that does not match the expected peg-native format"}}'))
    monkeypatch.setattr(llm.urllib.request, "urlopen", refuse)
    resp = llm.create(llm.OpenAIChat("http://127.0.0.1:1/v1"), model="m", max_tokens=10, messages=[{"role": "user", "content": "Q"}])
    assert resp.stop_reason == "end_turn" and llm.text_of(resp) == llm.UNREADABLE_NOTE and resp.repairs == ["unreadable-reply"]
