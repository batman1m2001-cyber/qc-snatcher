"""A failed soften keeps the verdict: l4 with the primary decider off and
soften's model timing out, end to end on the real LLMOp path (operonx's
`on_failure="error"`). Offline — the model is a stub that raises."""
import asyncio

from operonx.core import Operon, PARENT

from src.core import config
from src.core.conversation import Conversation
from tests._replay import fail_model

VIOLATION = {"violation": True, "category": "C8", "reason": "ĐTV quát khách",
             "evidence": "[00:03]: im đi", "evidence_idxs": [0]}


def test_a_soften_timeout_keeps_the_verdict_and_the_reason(monkeypatch):
    monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "")  # l4 goes straight to soften
    monkeypatch.setattr(config, "LLM_RESOURCE_KEY", "e4b-local")         # resolvable offline
    monkeypatch.setattr(config, "SOFTEN_LLM_RESOURCE_KEY", "e4b-local")
    from src.cases.sentiment_agent.l4_verify.graph import l4_verify

    g = l4_verify(result=PARENT, conversation=PARENT, name="l4")
    calls = fail_model(g, "soften_llm", TimeoutError("LLM exceeded 90s after 2 attempts"))
    out = asyncio.run(Operon(g).run(inputs={"result": dict(VIOLATION), "conversation": Conversation(vads=[])}))

    assert calls["n"] == 1, "soften's model was not reached"
    result = out["result"]
    assert (result["violation"], result["category"], result["reason"]) == (True, "C8", "ĐTV quát khách")
    assert result["_trace_meta"]["soften"]["enabled"] is False
    assert result["_trace_meta"]["soften"]["error"].startswith("TimeoutError")
