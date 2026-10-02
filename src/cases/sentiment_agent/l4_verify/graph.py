"""Layer 4 — the primary decider's strict re-verify, and the wording pass after it.

**It is not post-processing.** `resolve_cited_severity` runs here, and the
severity of the corpus entry it resolves *outranks the scanner's category*
— it is what turns a flagged call into `Thái độ warning` / `cao` /
`nghiêm trọng`, which is `Score_offset`. The diagram calls this stage a
refinement after the "filter decider"; the code says it decides the score.

Both stages gate themselves; `models.yaml` decides whether they can fire:

* `llm.primary_decider: null` ⇒ the strict re-verify never fires, the
  severity is never resolved, and **no call can score `Thái độ warning`**.
  Switching it off takes an explicit `null` in a reviewed file, so a deploy
  cannot lose a whole tier silently.
* `llm.soften` rewrites the wording of a kept verdict and never changes it;
  `null` falls back to the default model.

Every path reaches this layer, including the ones an earlier gate already
decided. Both stages check `violation` first, so a call that exited at the
bot gate passes through untouched.
"""
from operonx.core import END, START, GraphOp, graph
from operonx.core.ops import if_
from operonx.providers import LLMOp

from ..._shared.ops import parsed
from ....core import config
from ....core.conversation import Conversation
from ....core.prompts import PROMPTS
from ..retrieval.graph import retrieve_corpus
from .ops import (
    apply_primary_fn,
    apply_soften_fn,
    build_primary_inputs_fn,
    build_soften_inputs_fn,
    format_primary_pools_fn,
)

__all__ = ["l4_verify"]


@graph
def l4_verify(conversation: Conversation, result: dict = None) -> GraphOp:
    """Primary decider → severity → soften. Passthrough when not flagged."""

    # ── primary decider ─────────────────────────────────────────────────
    primary_gate = build_primary_inputs_fn(raw_result=result, conversation=conversation)
    # Same corpus, same graph, same backends as the filter decider.
    retrieval = retrieve_corpus(query=primary_gate["retrieval_query"])
    pools = format_primary_pools_fn(
        query=primary_gate["retrieval_query"],
        positives=retrieval["positives"],
        carveouts=retrieval["carveouts"],
    )
    # With `llm.primary_decider: null` the LLMOp is still registered — graph
    # validation needs a resource — but the gate always routes past it, so
    # it never fires. The default model keeps the resource valid at build time.
    primary_llm = LLMOp.of(
        description="Primary decider — strict re-verify with stronger LLM",
        resource=config.PRIMARY_DECIDER_LLM_RESOURCE_KEY or config.LLM_RESOURCE_KEY,
        # No prompt caching: the primary fires on ~1-2% of live traffic, so the
        # saving is trivial, and the cache_control marker correlated with Result
        # flips on borderline calls (`── DYNAMIC no-cache ──` in the prompt).
        prompt=PROMPTS.pair("PRIMARY_DECIDER_PROMPT"),
        parser="json",
        # `category` is deliberately NOT passed: taxonomy codes (C1..C11,
        # N1..N5) collide with the carveout pool ids (C1, C2, ...), and the
        # model then cited a taxonomy code as if it were policy. The pools
        # are the only policy the model sees.
        ai_reason=primary_gate["ai_reason"],
        evidence=primary_gate["evidence"],
        context=primary_gate["context"],
        positives=pools["positives_indexed"],
        carveouts=pools["carveouts_indexed"],
        fields=["result: dict"],
    )
    primary_llm_parsed = parsed(error=primary_llm["error"])
    apply_primary = apply_primary_fn(
        raw_result=result,
        primary_out=primary_llm["result"],
        severity_by_id=pools["severity_by_id"],
        pool_map=pools["pool_map"],
    )

    # ── soften ──────────────────────────────────────────────────────────
    soften_gate = build_soften_inputs_fn(raw_result=apply_primary["result"])
    soften_llm = LLMOp.of(
        description="Soften reason tone for QC business readability (C*/N* only)",
        resource=config.SOFTEN_LLM_RESOURCE_KEY,
        prompt=PROMPTS.pair("SOFTEN_REASON_PROMPT"),  # no caching either: same small slice
        parser="json",
        category=soften_gate["category"],
        evidence=soften_gate["evidence_text"],
        original_reason=soften_gate["original_reason"],
        fields=["result: dict"],
        # Soften only rewords the reason; it never touches the verdict. A
        # timeout or a bad reply must not cost the call its verdict, so the
        # failure arrives as `error` and apply_soften keeps the reason as is.
        on_failure="error",
    )
    apply_soften = apply_soften_fn(raw_result=apply_primary["result"], soften_out=soften_llm["result"],
                                   soften_error=soften_llm["error"])

    # Each `apply_*` is a branch merge: the skip arm reaches it straight from
    # its gate, the work arm after the LLM, and only one fires per call. Both
    # arms are plain edges — `GraphOp.build()` auto-softens exactly this
    # shape, so the merge fires on whichever arm arrives instead of waiting
    # for a node that never ran.
    START >> primary_gate >> if_(primary_gate["needs_verify"], retrieval).else_(apply_primary)
    retrieval >> pools >> primary_llm >> primary_llm_parsed >> apply_primary
    apply_primary >> soften_gate >> if_(soften_gate["needs_soften"], soften_llm).else_(apply_soften)
    soften_llm >> apply_soften >> END
