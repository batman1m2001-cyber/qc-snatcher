"""Deterministic gates used by the hangup case.

Two concerns bundled:

  1. `BOT_SIGNATURES` + `_has_bot_signature` — regex-free keyword scan for
     network voicemail / AI call-screening assistant / caller-side language
     that betrays the receiver is a bot, not a real customer.
  2. `gate_flags` @op — folds every silence / bot / empty-customer flag
     used by `verify_hangup`'s conditional routing into one dict, so the
     main graph reads as a flat switch rather than a chain of `is_silent`
     + `_has_bot_signature` calls.

`graph.py` only imports `gate_flags`; `BOT_SIGNATURES` is re-exported from
the package, `_has_bot_signature` stays private.
"""

from operonx.core import op

from ...core.conversation import Conversation

# Bot/voicemail signatures that appear on the CUSTOMER side when the call is
# auto-answered by:
#   - network voicemail (carrier recorded messages)
#   - third-party AI call-screening assistants ("trợ lý nghe máy",
#     "trợ lý cuộc gọi đang ghi âm", ...)
#   - assistants flipping the question back to the caller ("anh chị gọi có
#     việc gì", "mình gọi đúng số rồi", ...). A real KH receiving a call would
#     NOT use caller-side language like "mình gọi đúng số" — these are
#     unmistakable bot signatures.
# Any single occurrence of these in a customer turn is sufficient evidence
# that the receiver is a bot (AI assistants commonly intersperse short
# fillers like "ừ", "dạ em là" between scripted lines, so "all turns must
# match" misses them).
BOT_SIGNATURES = [
    # Network voicemail / carrier
    'nhà mạng',
    'việt nam mô bai', 'việt nam môbile', 'vietnam mobile',
    'viettel', 'vinaphone', 'mobifone',
    'ngoài vùng phủ sóng',
    'chủ thuê bao', 'chủ thu tế bào',
    'tạm thời không liên lạc', 'không liên lạc được',
    'thuê bao quý khách',
    # AI assistant / call-screening bot self-identification
    'trợ lý ảo',
    'trợ lý nghe máy',
    'trợ lý cuộc gọi',
    'ghi âm cuộc gọi này',
    'đang ghi âm cuộc gọi',
    # Bot flipping the question back to caller (caller-side language)
    'anh chị gọi có việc gì',
    'anh chị gọi đến có việc gì',
    'anh chị gọi đúng số',
    'mình gọi có việc gì',
    'mình gọi đến có việc gì',
    'mình gọi đúng số rồi',
    'ai gọi vậy ạ',
    'ai gọi về ạ',
]


def _has_bot_signature(text: str) -> bool:
    t = (text or '').lower()
    return any(p in t for p in BOT_SIGNATURES)


@op
def gate_flags(conversation: Conversation) -> dict:
    """Compute all gate flags for hangup case in one place.

    Returns:
    - agent_silent: agent never produced a content turn.
    - customer_silent: `Conversation.is_silent(role="customer")`.
    - customer_empty: no customer content turns (real or bot).
    - customer_bot_only: customer has content but every turn is a bot/voicemail signature.
    - mutual_silence: both agent_silent and customer_empty (true no-pickup).
    - agent_no_response: agent_silent but customer DID speak (incl bot voicemail) — per QC this IS a violation.
    """
    agent_silent = conversation.is_silent(role="agent")
    customer_silent = conversation.is_silent(role="customer")
    customer_turns = [
        (v.get('content') or '').strip()
        for v in conversation.vads
        if v.get('role') == 'customer'
    ]
    customer_turns = [t for t in customer_turns if t]
    customer_empty = len(customer_turns) == 0
    customer_bot_only = (not customer_empty) and all(_has_bot_signature(t) for t in customer_turns)
    return {
        "agent_silent": agent_silent,
        "customer_silent": customer_silent,
        "customer_empty": customer_empty,
        "customer_bot_only": customer_bot_only,
        "mutual_silence": agent_silent and customer_empty,
        "agent_no_response": agent_silent and not customer_empty,
    }
