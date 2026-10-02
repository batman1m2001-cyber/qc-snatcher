"""Customer sentiment analysis workflow."""

from operonx.core.ops import if_
from operonx.core import START, END, GraphOp, graph
from operonx.providers import LLMOp
from ...core.config import LLM_RESOURCE_KEY
from ...core.prompts import PROMPTS
from .._shared.ops import exit_fn, expand_evidence_fn, format_fn, parsed
from ...core.conversation import Conversation


@graph
def verify_sentiment_customer(conversation: Conversation) -> GraphOp:
    """Verify customer sentiment violations. Cite customer turns → mask agent."""

    fmt = format_fn(conversation=conversation, cite_role="customer")

    quiet = exit_fn(category="im_lang")

    verify = LLMOp.of(
        description="Verify customer sentiment violation",
        resource=LLM_RESOURCE_KEY,
        prompt=PROMPTS["CUSTOMER_SENTIMENT_PROMPT"],
        transcript=fmt["content"],
        fields=["result: dict"],
        parser="xml",
    )
    verify_parsed = parsed(error=verify["error"])

    mapping = expand_evidence_fn(
        llm_result=verify["result"],
        conversation=conversation,
        role="customer",
    )

    START >> fmt >> if_(fmt["customer_silent"], quiet).else_(verify)
    verify >> verify_parsed >> mapping >> END
    quiet >> END
