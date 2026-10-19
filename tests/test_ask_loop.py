"""The question loop, against a scripted model: look, get refused, fix, get accepted."""
import json

import pytest

from tests.fakes import FakeClient, text_response, tool_response
from ugrc import ask, llm, verify


def test_refused_then_accepted(synth_root):
    cl = FakeClient([
        tool_response("sql", {"query": "SELECT id, text FROM cells WHERE col_no = 2 ORDER BY row_no"}),
        tool_response("submit_answer", {"runs": [{"text": "The best yield was 91.0 percent."}]}),
        text_response("I will fix it."),
        tool_response("submit_answer", {"runs": [{"text": "The best yield was "},
                                                 {"quote": "91.0", "atom": "p1.T1.r3c2"},
                                                 {"text": " percent, over "}, {"quote": "Ni-20", "atom": "p1.T1.r3c1"},
                                                 {"text": " ("}, {"table": "p1.T1"}, {"text": ")."}]}),
    ])
    rec = ask.ask(synth_root, "Which catalyst gave the best yield?", model="test-model", cl=cl, log=lambda *_: None)
    assert rec["rendered"] == "The best yield was 91.0[1] percent, over Ni-20[2] (Table 1[3])."
    assert len(rec["door_refusals"]) == 1 and rec["door_refusals"][0][0]["rule"] == "text:number"
    # what the model saw: the sql rows, then the refusal as a tool error with its moves, then a nudge
    second = cl.calls[2]["messages"]
    sql_result = cl.calls[1]["messages"][-1]["content"][0]
    assert "p1.T1.r3c2 | 91.0" in sql_result["content"] and not sql_result["is_error"]
    refusal = second[-1]["content"][0]
    assert refusal["is_error"] and "[text:number]" in refusal["content"] and "quote run" in refusal["content"]
    assert cl.calls[3]["messages"][-1]["content"].startswith("Only an answer sent through submit_answer")
    assert "p1.T1 Table 1" in cl.calls[0]["system"] and cl.calls[0]["fallbacks"] == "default"
    # and the stored answer passes the receipt
    path = ask.save(synth_root, rec)
    assert all(ok for ok, _ in verify.verify_answer(path, synth_root))
    assert json.loads(path.read_text())["citations"][0]["source"]["column_header"] == "Yield (%)"


def test_view_figure_returns_the_image_and_facts(synth_root):
    cl = FakeClient([tool_response("view_figure", {"figure_id": "p2.F1"}),
                     tool_response("submit_answer", {"runs": [{"text": "See "}, {"figure": "p2.F1"}]})])
    ask.ask(synth_root, "q", model="m", cl=cl, log=lambda *_: None)
    result = cl.calls[1]["messages"][-1]["content"][0]["content"]
    assert result[0]["type"] == "image" and "p2.F1.k1" in result[1]["text"]


def test_a_refusal_is_raised_not_read():
    from types import SimpleNamespace
    cl = FakeClient([SimpleNamespace(stop_reason="refusal", stop_details=SimpleNamespace(category="bio"), content=[])])
    with pytest.raises(llm.ModelRefused):
        llm.create(cl, model="m", max_tokens=10, messages=[])


def test_a_session_keeps_history_and_answers_each_question(synth_root):
    cl = FakeClient([
        tool_response("submit_answer", {"runs": [{"text": "Best: "}, {"quote": "Ni-20", "atom": "p1.T1.r3c1"}]}),
        tool_response("submit_answer", {"runs": [{"text": "Its yield: "}, {"quote": "91.0", "atom": "p1.T1.r3c2"}]}),
    ])
    recs = ask.session(synth_root, ["Which catalyst is best?", "What is its yield?"], model="m", cl=cl,
                       log=lambda *_: None)
    assert [r["rendered"] for r in recs] == ["Best: Ni-20[1]", "Its yield: 91.0[1]"]
    assert [r["session_index"] for r in recs] == [0, 1] and recs[0]["session"] == recs[1]["session"]
    second = cl.calls[1]["messages"]
    assert second[0]["content"][0]["text"] == "Which catalyst is best?"       # the first question is still there
    last = second[-1]["content"]                                                # ... the accepted tool_result, then the new question
    assert last[0]["type"] == "tool_result" and last[0]["content"] == "accepted"
    assert last[1] == {"type": "text", "text": "What is its yield?"}
