"""Card-number heuristics — pre-filter + post-LLM digit-count gate.

Two @ops the main graph wires in, plus the constants + word-counting
helpers they share:

  - `is_suspicious`     — cheap pre-filter that decides whether the LLM
                          call is even worth paying for. Fires only when
                          agent turns show a dense digit run in a
                          card-context turn (no "nhập/kiểm tra" instruction
                          phrasing, no letter-spelled masked IDs, no
                          money/time-unit dominance).
  - `gate_digit_count`  — hard post-op gate that recounts raw Vietnamese
                          digits in the LLM's evidence text and overrides
                          `violation=false` when the count is < 16. Catches
                          "đủ 16 số" hallucinations against transcripts
                          that only carry 10–12 digits or letter-masked IDs.
"""

import re

from operonx.core import op

from ...core.conversation import Conversation
from .._shared.ops import _build_turn_map
from .._shared.spec import turn_idxs

# Vietnamese spoken digits 0-9 (raw — no letter spellouts).
DIGIT_MAP = {
    'không': '0', 'linh': '0',
    'một': '1', 'mốt': '1',
    'hai': '2',
    'ba': '3',
    'bốn': '4', 'tư': '4',
    'năm': '5', 'lăm': '5',
    'sáu': '6',
    'bảy': '7', 'bẩy': '7',
    'tám': '8',
    'chín': '9',
}

#: Digits in a card number. Fewer than this in the evidence is not a card read.
CARD_DIGITS = 16
#: One turn with at least this many digits (plus a card keyword) is a dense read.
DENSE_READ_DIGITS = 12
#: A next turn with at least this many digits continues a split read.
SPLIT_READ_DIGITS = 6

# Card-context keywords that must accompany a 16-digit reading.
CARD_KEYWORDS = [
    'số thẻ', 'thẻ tín dụng số', 'card number',
    'in nổi', 'in dập', 'mặt trước thẻ', 'số trên thẻ',
    'số in trên thẻ', '16 số', 'mười sáu số',
]

# Words that strongly indicate the digits are NOT a card number — money/time
# amounts, etc. If a window is dominated by these, skip it.
NON_CARD_UNIT_WORDS = {
    'triệu', 'nghìn', 'trăm', 'mươi', 'tỷ', 'đồng',
    'tháng', 'ngày', 'giờ', 'phút', 'giây', 'năm',
}

# Letter spellouts in Vietnamese (used when reading masked card IDs like
# "ba hai năm pê" → 325P). Their presence near a digit run signals a masked
# contract ID, NOT 16 raw digits.
LETTER_SPELLOUTS = {
    'a', 'bê', 'tê', 'pê', 'phê', 'ê', 'em', 'ô', 'đê', 'i',
    'cê', 'kê', 'ết', 'lờ', 'mờ', 'nờ',
}

# Phrases that indicate agent is *instructing* the customer rather than
# reading their own card number. These should suppress the LLM call.
INSTRUCT_PHRASES = [
    'anh nhập', 'chị nhập', 'em nhập',
    'anh kiểm tra', 'chị kiểm tra', 'mình kiểm tra',
    'xem trên thẻ', 'mặt trước thẻ', 'trên mặt thẻ',
    'anh đọc', 'chị đọc',
    'chuyển vào', 'chuyển trực tiếp vào',
]


def _digit_count(text: str) -> int:
    """Number of raw Vietnamese digit words in the text."""
    return sum(1 for w in re.findall(r'\b\w+\b', text.lower()) if w in DIGIT_MAP)


def _letter_count(text: str) -> int:
    """Number of Vietnamese letter spellouts in the text."""
    return sum(1 for w in re.findall(r'\b\w+\b', text.lower()) if w in LETTER_SPELLOUTS)


def _unit_count(text: str) -> int:
    """Number of money/time-unit words (rules out amount-style readings)."""
    return sum(1 for w in re.findall(r'\b\w+\b', text.lower()) if w in NON_CARD_UNIT_WORDS)


def _has_card_keyword(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in CARD_KEYWORDS)


def _has_instruct_phrase(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in INSTRUCT_PHRASES)


@op
def is_suspicious(conversation: Conversation) -> bool:
    """Decide whether the conversation is a candidate for 16-digit card read.

    Rules:
      * Focus on agent turns that contain a card keyword AND no instruction
        phrase ("nhập", "kiểm tra trên thẻ", ...) in the SAME turn.
      * Require the digit run to be concentrated:
          - one turn alone with ≥ 12 raw digits, OR
          - a pair of consecutive turns each ≥ 6 raw digits.
      * Discard if the same window is heavy with money/time-unit words —
        those readings are amounts/dates, not card numbers.
      * Discard if letters (bê/tê/pê/...) appear in the same turn — that
        is a masked contract ID, not a 16-digit raw card number.
    """
    agent_turns = [v.get('content', '') for v in conversation.vads if v.get('role') == 'agent']

    for i, turn in enumerate(agent_turns):
        digits = _digit_count(turn)
        if digits < 6:
            continue

        # Agent is instructing, not reading
        if _has_instruct_phrase(turn):
            continue
        # Masked contract ID — letters mixed with digits
        if _letter_count(turn) >= 1 and digits < CARD_DIGITS:
            continue
        # Looks like an amount or date string
        if _unit_count(turn) >= 2:
            continue

        # Single-turn dense read
        if digits >= DENSE_READ_DIGITS and _has_card_keyword(turn):
            return True

        # Two-turn consecutive dense read with card context
        if i + 1 < len(agent_turns):
            nxt = agent_turns[i + 1]
            if _digit_count(nxt) >= SPLIT_READ_DIGITS and _letter_count(nxt) == 0 and _unit_count(nxt) < 2:
                if _has_card_keyword(turn) or _has_card_keyword(nxt):
                    return True

    return False


@op
def gate_digit_count(llm_result: dict = None, conversation: Conversation = None) -> dict:
    """Hard gate: a violation is only kept if the cited evidence really
    contains ≥ 16 raw Vietnamese digit words inside agent turns. Otherwise
    we override to non-violation.

    This catches LLM hallucinations where the model says "đủ 16 số" but the
    cited turns only contain 10–12 digits or letter-masked card IDs.
    """
    result = dict(llm_result or {})
    if not result.get("violation"):
        return {"result": result}

    idxs = turn_idxs(result.get("evidence"))
    if not idxs:
        result["violation"] = False
        result["reason"] = "Gate override: violation flagged but no evidence idxs provided"
        return {"result": result}

    agent_map = _build_turn_map(conversation, "agent")
    evidence_text = " ".join(
        (agent_map[i].get("content") or "") for i in idxs if i in agent_map
    )

    digits = _digit_count(evidence_text)
    declared = result.get("digits_counted")
    try:
        declared_int = int(declared) if declared is not None else None
    except (TypeError, ValueError):
        declared_int = None

    if digits < CARD_DIGITS:
        result["violation"] = False
        result["reason"] = (
            f"Gate override: evidence chỉ có {digits} chữ số raw "
            f"(LLM khai {declared_int!r}); chưa đủ 16 số thẻ."
        )
        result["evidence"] = ""

    return {"result": result}
