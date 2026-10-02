"""QC trace consumer — `LocalConsumer`, minus the customer's words.

Remote tracers are deliberately absent. The pipeline hands a whole
`Conversation` — agent and customer transcripts, contact details inside
scoring payloads — to a dozen different ops, and any consumer that ships
op inputs off-host would ship that with it. Only on-disk tracing is
supported, and only through the redaction below.

What it removes, and why each one:

**The transcript.** Twelve ops take the whole `Conversation`, so an
unredacted trace serialises one call's transcript twelve times (1.38 MB per
call on average, worst case 12 MB, 92% of it those copies). A pointer
replaces them — the input JSON is the store of record, and `source_path` is
what makes the pointer resolvable back to it. `request_id` alone yields a
filename stem, which does not say which batch directory it came from.

**Query vectors.** Retrieval stores 1024 floats twice per call —
`inputs.embeddings` and `outputs.vector`, ~45 KB each. Nobody debugs
retrieval by reading a vector; the query text and the ranked pool are
what you look at, and both survive.

**The static half of each prompt.** Kept as `{"_prompt": key, "sha": …}`.
The sha matters as much as the key: prompts get edited, so a trace naming
only the key would reconstruct against whatever the file says today and
quietly show a prompt that never ran.

Every op, every timing, every output survives. Only duplicated payload
goes.

**Layout: flat.** One directory per call, `<root>/<trace_id>/`, beside the
stage files `finalize_row` writes. operonx 1.10's default (`origin`) files
a job's traces under `<root>/jobs/<job>/<run>/<trace_id>/`; the stage file
would stay flat and the two would part.

Why `Conversation` is intercepted by type in `sanitize()`
---------------------------------------------------------
operonx does not `asdict` records; `Consumer.sanitize` replaces any
non-primitive with `{"$unserializable": "<type>"}`. Left to the base class,
a `Conversation` would become `{"$unserializable": "Conversation"}` — not a
leak, but `source_path` would go with it, silently losing the one thing
that makes a trace resolvable.
"""

from __future__ import annotations

import hashlib
from typing import Any, ClassVar, Dict, Optional, Tuple

from operonx.core.registry import REGISTRY
from operonx.core.utils.yaml_model import YamlModel
from operonx.telemetry.consumers.local import LocalConsumer

from src.core.conversation import Conversation
from src.core.prompts import PROMPTS

__all__ = ["QCLocalConsumer", "QCLocalConsumerConfig"]

#: Shortest float list treated as an embedding. Real vectors are 1024-d;
#: nothing else in a trace is a long run of bare floats.
_VECTOR_MIN_DIM = 64


class QCLocalConsumer(LocalConsumer):
    """`LocalConsumer` with the QC pipeline's redaction rules."""

    DEFAULT_CONFIG: ClassVar[Dict[str, Any]] = {**LocalConsumer.DEFAULT_CONFIG, "layout": "flat"}

    #: {static prompt text -> (prompt key, sha8)}. Built once, lazily —
    #: PROMPTS loads at import and never changes during a run.
    _prompt_index: ClassVar[Optional[Dict[str, Tuple[str, str]]]] = None

    # ── prompt lookup ─────────────────────────────────────────────────

    @classmethod
    def _static_prompts(cls) -> Dict[str, Tuple[str, str]]:
        if cls._prompt_index is None:
            index: Dict[str, Tuple[str, str]] = {}
            for key in PROMPTS.splittable():
                try:
                    static = PROMPTS.split(key).static
                except Exception:  # a broken split is not this module's problem
                    continue
                sha = hashlib.sha256(static.encode("utf-8")).hexdigest()[:8]
                # The trace holds the RENDERED prompt, so `{{` has already
                # collapsed to `{`. Index both forms: matching only the raw
                # template silently misses every block containing braces.
                index[static] = (key, sha)
                index[static.replace("{{", "{").replace("}}", "}")] = (key, sha)
            cls._prompt_index = index
        return cls._prompt_index

    def _as_prompt_ref(self, text: str) -> Optional[Dict[str, Any]]:
        """`{"_prompt": key, "sha": …}` if *text* is a known static half.

        Text matching nothing is left alone: an edited or retired prompt
        keeps its full copy rather than being replaced by a lie.
        """
        hit = self._static_prompts().get(text)
        if hit is None:
            return None
        key, sha = hit
        return {"_prompt": key, "sha": sha, "chars": len(text)}

    # ── value reducers ────────────────────────────────────────────────

    @staticmethod
    def _as_conversation_ref(conv: Conversation) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "_redacted": "Conversation",
            "n_turns": len(getattr(conv, "vads", None) or []),
        }
        source = getattr(conv, "source_path", "")
        if source:
            out["source"] = source
        return out

    def _as_vector_ref(self, value: Any) -> Optional[Dict[str, Any]]:
        """`{"_redacted": "vector", "dim": n}` for an embedding, else None."""
        if not isinstance(value, list) or not value:
            return None
        # [[...]] — a batch of one, which is how the embedder returns it.
        if len(value) == 1 and isinstance(value[0], list):
            inner = self._as_vector_ref(value[0])
            return None if inner is None else {**inner, "batch": 1}
        if len(value) < _VECTOR_MIN_DIM:
            return None
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in value):
            return None
        return {"_redacted": "vector", "dim": len(value)}

    def _shrink_messages(self, messages: Any) -> Any:
        """Swap each system block that is a known static half for a ref.

        User messages carry the per-request variables and are left alone —
        that is the part worth reading.
        """
        if not isinstance(messages, list):
            return messages
        out = []
        for msg in messages:
            if not isinstance(msg, dict) or msg.get("role") != "system":
                out.append(msg)
                continue
            msg = dict(msg)
            content = msg.get("content")
            if isinstance(content, str):
                ref = self._as_prompt_ref(content)
                if ref is not None:
                    msg["content"] = ref
            elif isinstance(content, list):
                blocks = []
                for block in content:
                    if isinstance(block, dict) and isinstance(block.get("text"), str):
                        ref = self._as_prompt_ref(block["text"])
                        if ref is not None:
                            block = {**block, "text": ref}
                    blocks.append(block)
                msg["content"] = blocks
            out.append(msg)
        return out

    # ── the hook ──────────────────────────────────────────────────────

    def sanitize(self, payload: Any) -> Any:
        """Reduce before the base class decides a value is unserialisable.

        Order matters. `Conversation` is intercepted by type here because
        the base would otherwise turn it into `{"$unserializable": …}`,
        taking `source_path` with it.
        """
        if isinstance(payload, Conversation):
            return self._as_conversation_ref(payload)

        if isinstance(payload, dict):
            out = {}
            for key, value in payload.items():
                # `messages` is the rendered pair; `template` and `prompt`
                # are the same pair before formatting. All carry the
                # static half verbatim.
                if key in ("messages", "template", "prompt"):
                    out[key] = super(QCLocalConsumer, self).sanitize(
                        self._shrink_messages(value)
                    )
                    continue
                out[key] = self.sanitize(value)
            return out

        vec = self._as_vector_ref(payload)
        if vec is not None:
            return vec

        return super().sanitize(payload)


class QCLocalConsumerConfig(YamlModel):
    """YAML-configurable :class:`QCLocalConsumer`, declared as `trace_qc:`."""

    _category: ClassVar[str] = "trace_qc"

    root: str = "./traces"
    layout: str = "flat"
    media_threshold: int = 1024
    write_view_txt: bool = True
    show_io: bool = True


def _create_qc_local_consumer(cfg: QCLocalConsumerConfig) -> QCLocalConsumer:
    return QCLocalConsumer(config={
        "root": cfg.root,
        "layout": cfg.layout,
        "media_threshold": cfg.media_threshold,
        "write_view_txt": cfg.write_view_txt,
        "show_io": cfg.show_io,
    })


# Side-effect registration — importing this module makes `trace_qc:<name>`
# resolvable through the hub.
REGISTRY.register(QCLocalConsumerConfig, _create_qc_local_consumer)
