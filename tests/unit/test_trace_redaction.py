"""Traces keep every op; they stop keeping twelve copies of the transcript.

`traces/` reached 6311 files and 8.5 GB — 1.38 MB per call, worst case
12 MB. None of that was op count: 50 records of names, timings and outputs
cost about 420 KB. The bulk was payload stored over and over —

  * `Conversation` is an input to twelve ops, so one call's transcript was
    serialised twelve times into one file (92% of the worst file);
  * the retrieval query vector, 1024 floats, on both sides of the op;
  * the rendered prompt, once as the `.prompt` op's output and again as the
    `.llm` op's input, its static half identical on every call.

Filtering by op was the obvious fix and would have been the wrong one: the
2026-08-24 diagnosis of ten "lost" calls turned on seeing that `skip_verify`
ran and `apply_decider` did not. An "important ops only" list would have
dropped `skip_verify` and cost a pointless rerun of ten files. So the op
list is untouchable; the payload is what gets cut.

These tests pin both halves of that bargain — what must survive, and what
must not be there.

The hook moved with the framework: hush rewrote records in `flush()` after
the fact, operonx reduces in `Consumer.sanitize()` before the row is built.
One case below is new and exists because of that move —
`test_a_conversation_never_reaches_the_base_fallback`.

No LLM, no network.
"""
import json

import pytest

from src.core.conversation import Conversation
from src.jobs.score._tracing import QCLocalConsumer
from src.core.prompts import PROMPTS


@pytest.fixture
def consumer(tmp_path):
    return QCLocalConsumer(config={"root": str(tmp_path)})


def clean(consumer, payload):
    """What the consumer would write for one op's inputs or outputs."""
    return consumer.sanitize(payload)


# -- the transcript becomes a pointer to the file it came from ----------


def test_conversation_becomes_a_pointer(consumer):
    conv = Conversation(
        vads=[{"content": "alo", "turn_idx": 0}, {"content": "vang", "turn_idx": 1}],
        source_path="data/batch/inputs/E_x.json",
    )
    assert clean(consumer, {"conversation": conv})["conversation"] == {
        "_redacted": "Conversation", "n_turns": 2,
        "source": "data/batch/inputs/E_x.json",
    }


def test_no_transcript_text_survives_anywhere(consumer):
    """The point of the exercise: customer speech must not accumulate on
    disk. This project dropped Langfuse over exactly that."""
    conv = Conversation(vads=[{"content": "noi dung nhay cam cua khach"}],
                        source_path="p.json")
    out = [clean(consumer, {"conversation": conv}),
           clean(consumer, {"conversation": conv})]
    assert "nhay cam" not in json.dumps(out, ensure_ascii=False)


def test_a_conversation_never_reaches_the_base_fallback(consumer):
    """operonx does not `asdict` a record, so a Conversation arrives as the
    object. Left to the base class it becomes `{"$unserializable": ...}` —
    no leak, but `source_path` goes with it, and that pointer is the only
    thing making a trace resolvable back to its input."""
    out = clean(consumer, {"conversation": Conversation(vads=[], source_path="p.json")})
    assert "$unserializable" not in json.dumps(out)
    assert out["conversation"]["source"] == "p.json"


def test_pointer_survives_a_conversation_built_in_memory(consumer):
    """The `main()` smoke block in each case graph builds one without a
    file. No source key rather than an empty one that looks like a path."""
    out = clean(consumer, {"conversation": Conversation(vads=[{"content": "alo"}])})
    assert out["conversation"] == {"_redacted": "Conversation", "n_turns": 1}


def test_nested_conversation_is_reduced(consumer):
    """Ops take it as a bare input, but a sub-result can carry one too."""
    conv = Conversation(vads=[{"content": "alo"}], source_path="p.json")
    out = clean(consumer, {"payload": {"inner": conv}})
    assert out["payload"]["inner"]["_redacted"] == "Conversation"


def test_load_records_where_it_read_from(tmp_path):
    """Without this the pointer is a filename stem, and a stem does not say
    which batch directory it came from — 1136 of 1350 existing traces could
    not be resolved back to an input for that reason."""
    p = tmp_path / "E_call.json"
    p.write_text(json.dumps({"transcribed_vads": [{"content": "alo"}]}), encoding="utf-8")
    assert Conversation.load(str(p)).source_path == str(p)


# -- embedding vectors -------------------------------------------------


@pytest.mark.parametrize("value, expected", [
    ([0.1] * 1024,   {"_redacted": "vector", "dim": 1024}),
    ([[0.1] * 1024], {"_redacted": "vector", "dim": 1024, "batch": 1}),
])
def test_vectors_become_a_shape(consumer, value, expected):
    assert clean(consumer, {"vector": value})["vector"] == expected


@pytest.mark.parametrize("value", [
    [1, 2, 3],                        # evidence_idxs — short, and load-bearing
    [0.1] * 10,                       # below the dimension floor
    ["a"] * 200,                      # a long list of strings is not a vector
    [0.1, "a", 0.2],                  # mixed
    [True] * 200,                     # bools are ints in Python; not a vector
    [],
])
def test_short_or_non_numeric_lists_are_untouched(consumer, value):
    assert clean(consumer, {"x": value})["x"] == value


# -- prompts: the static half is a reference, the variables are not -----


def test_static_prompt_becomes_a_reference_with_a_sha(consumer):
    key = "SCANNER_PROMPT"
    static = PROMPTS.split(key).static
    msgs = [{"role": "system", "content": static},
            {"role": "user", "content": "Noi dung cuoc goi: [0] AGENT: alo"}]
    out = clean(consumer, {"messages": msgs})["messages"]
    assert out[0]["content"]["_prompt"] == key and len(out[0]["content"]["sha"]) == 8
    # the per-request half is the part worth reading — it stays verbatim
    assert out[1]["content"] == "Noi dung cuoc goi: [0] AGENT: alo"


def test_rendered_prompt_matches_too(consumer):
    """A trace holds the prompt after `.format()`, so an escaped brace has
    collapsed to a plain one. Indexing only the raw template made this swap
    fire on 14 of 197 system blocks instead of 157."""
    static = PROMPTS.split("SCANNER_PROMPT").static
    rendered = static.replace("{{", "{").replace("}}", "}")
    assert rendered != static, "prompt has no escaped braces — pick another for this test"
    out = clean(consumer, {"messages": [{"role": "system", "content": rendered}]})
    assert out["messages"][0]["content"]["_prompt"] == "SCANNER_PROMPT"


def test_cached_block_keeps_its_cache_control(consumer):
    """Whether a call was cached is a fact about the run, not about the
    prompt text — it has to survive the swap."""
    static = PROMPTS.split("SCANNER_PROMPT").static
    msgs = [{"role": "system", "content": [
        {"type": "text", "text": static, "cache_control": {"type": "ephemeral"}}]}]
    block = clean(consumer, {"messages": msgs})["messages"][0]["content"][0]
    assert block["text"]["_prompt"] == "SCANNER_PROMPT"
    assert block["cache_control"] == {"type": "ephemeral"}


def test_unknown_prompt_text_is_kept_in_full(consumer):
    """An edited or retired prompt has no entry to point at. Keeping the
    text is right; naming a key that would reconstruct different words is
    not."""
    text = "mot prompt khong co trong .prompts/" * 20
    out = clean(consumer, {"messages": [{"role": "system", "content": text}]})
    assert out["messages"][0]["content"] == text


def test_outputs_are_shrunk_too(consumer):
    """A `.prompt` op emits the rendered messages and the `.llm` op beside
    it takes the same list as input — inputs-only would halve the saving."""
    static = PROMPTS.split("SCANNER_PROMPT").static
    out = clean(consumer, {"messages": [{"role": "system", "content": static}]})
    assert out["messages"][0]["content"]["_prompt"] == "SCANNER_PROMPT"


def test_user_messages_are_never_swapped(consumer):
    """Only the system block is a candidate. A user turn carrying the same
    text is per-request data and must read back verbatim."""
    static = PROMPTS.split("SCANNER_PROMPT").static
    out = clean(consumer, {"messages": [{"role": "user", "content": static}]})
    assert out["messages"][0]["content"] == static


# -- what must never be lost -------------------------------------------


def test_every_verdict_survives(consumer):
    """The op list is the diagnostic. Ten calls were nearly rerun for
    nothing because a scanner verdict was missing from the output; the
    trace is what settled it."""
    outputs = {"result": {"violation": False, "category": "none"},
               "evidence_idxs": [3, 7]}
    assert clean(consumer, outputs) == outputs


def test_payloads_with_no_content_do_not_crash(consumer):
    assert clean(consumer, None) is None
    assert clean(consumer, "a string") == "a string"
    assert clean(consumer, {}) == {}
