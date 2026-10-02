"""Layer 1 ops — the cheap gates' own checks.

* `is_bot_customer_fn` — regex for an IVR / `trợ lý ảo` / voicemail pickup.
  There is no human customer to be rude to, so the call is not judged.
  A survey of 412 live calls (live_1607+2207) found 10 such pickups (2.4%);
  the patterns cover the clean signatures plus the ASR variants the diariser
  produces on a robot voice — `chủ tế bào` for `chủ thuê bao`, `trợ chỉ no`
  for `trợ lý ảo`.
* `is_kid_fn` — reads the kid-detector's verdict. Calls longer than
  `KID_DETECTOR_TURN_CAP` turns skip the detector; the branch compares
  `fmt["n_turns"]` against the cap directly.
* `proceed_fn` — the layer's hand-on exit when no gate decided.

The pre-filter's ops live in `prefilter/`, beside its subgraph.
"""
from __future__ import annotations

import re
from typing import Any

from operonx.core import op

from ....core.conversation import Conversation
from ..._shared.spec import is_true

_IVR_PATTERNS = re.compile(
    r"tính năng trợ\s*(lý|chỉ)|"                        # tính năng trợ lý / trợ chỉ (ASR)
    r"em\s+(là|nhà)\s+trợ\s*(lý|chỉ)|"                  # em là/nhà trợ lý (ASR: nhà vs là)
    r"em\s+(là|nhà)\s+tính năng|"                       # em là tính năng ...
    r"chủ\s*(thuê|tế|thế)\s*(bao|bào)|"                 # chủ thuê bao + ASR variants
    r"chủê\s*(bao|bào)|"                                # merged ASR
    r"ngoài vùng phủ sóng|"
    r"nhà mạng\s+(việt nam|vinaphone|mobifone|viettel|mobile|vi(na|na phone)?|mo\s*bile)|"
    r"trợ lý ảo|"
    r"ai đang nghe máy giúp\s+(chủ )?(thuê|tế|thế)\s*(bao|bào)",  # IVR greeting template
    re.IGNORECASE,
)

_MAX_CUSTOMER_TURNS_CHECKED = 5


@op
def is_bot_customer_fn(conversation: Conversation = None) -> dict[str, Any]:
    """Check first N CUSTOMER turns for IVR/bot signature. Cheap regex,
    no LLM call. Runs early in the graph so IVR calls skip the whole
    scanner + decider pipeline.
    """
    if conversation is None:
        return {"is_bot": False, "keyword": ""}
    kh_seen = 0
    for turn in conversation.vads:
        if (turn.get("role") or "").lower() != "customer":
            continue
        content = (turn.get("content") or "").strip().lower()
        if not content:
            continue
        m = _IVR_PATTERNS.search(content)
        if m:
            return {"is_bot": True, "keyword": m.group(0)}
        kh_seen += 1
        if kh_seen >= _MAX_CUSTOMER_TURNS_CHECKED:
            break
    return {"is_bot": False, "keyword": ""}


# Cap kid-detector runs to short calls. Pilot data: 7/9 kid-call false
# positives were ≤ 30 turns; longer calls almost never turn out to be a kid
# picking up. Keeps the extra LLM call from firing on the long majority.
KID_DETECTOR_TURN_CAP = 30


@op
def is_kid_fn(result: dict = None) -> bool:
    """The kid detector's `is_kid` as a bool. Anything unreadable is not a
    kid, so the call falls through to the main verify rather than being
    skipped."""
    return isinstance(result, dict) and is_true(result.get("is_kid"))


@op
def proceed_fn(content: str = "", filter_meta: dict = None) -> dict:
    """No gate fired — hand the next layer what it needs.

    `result: None` says "not decided", not "decided clean". The two are
    the same value in a careless reading and opposite in effect, which is
    why `is_decided` checks for an exit stamp rather than truthiness.
    """
    return {"result": None, "content": content, "filter_meta": filter_meta}
