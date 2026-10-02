"""Import-time side effects for the `src` package.

Three things must happen before any `src.*` module runs:

  1. Load the env file (`local.env` or `.env`, see below) so `os.environ`
     is populated for `config.py` and the resources.yaml expansion.
  2. Import `operonx.providers` so it registers its categories (llm,
     embedding, reranking, vector_store, doc_store, keycloak, oauth2) —
     otherwise a lookup like `resource="db-gemini-3-flash"` has no class
     to parse the config into.
  3. Install the ResourceHub from this repo's `resources.yaml`.

It also patches the OpenAI-SDK LLM's `generate` with a deadline, retry and
usage/cost accounting.

Kept in its own module (not inlined into `__init__.py`) so anyone asking
"what runs at import" can find it by name. `src/__init__.py` imports it.
"""
import os as _osenv
import pathlib as _pathlib

from dotenv import load_dotenv

# ----- which env file -------------------------------------------------------
#
# Two files, both gitignored, and exactly one is loaded:
#
#     .env        the deployment's.  `deployment/score_sentiment/settings.py`
#                 WRITES this file on the pod (`set_key(".env", ...)`), so it
#                 is an interface, not a scratchpad — it holds the cluster
#                 endpoints and must keep the shape that script produces.
#     local.env   this machine's.  The docker-compose Postgres and the
#                 other endpoints a developer run talks to.
#
# Selected by platform: the pods are Linux containers, this is developed on
# Windows. That is the one signal that does not move. IP addresses change
# between the company LAN and a 3G dongle, hostnames are regenerated per
# pod, and the env file is the thing being decided about, so it cannot
# decide for itself.
#
# Precedence, highest first:
#
#     an explicit shell variable  >  the selected file
#         >  the default baked into resources.yaml
#
# `override=False` is what gives the first of those: a variable already in
# the environment is left alone. The two files are never merged: a
# half-local, half-remote configuration fails only as a DNS error from a
# remote endpoint being asked for a locally-named model.
#
# Set QC_LOCAL_STACK=false to make a Windows machine read `.env` instead,
# e.g. to point a local run at the cluster for one session.
from .env import env_bool as _env_bool, env_number as _env_number  # noqa: E402

_LOCAL_STACK_ENV = "QC_LOCAL_STACK"
_ROOT_DIR = _pathlib.Path(__file__).resolve().parents[2]
LOCAL_ENV_FILE = _ROOT_DIR / "local.env"
DEPLOY_ENV_FILE = _ROOT_DIR / ".env"


LOCAL_STACK = _env_bool(_LOCAL_STACK_ENV, default=_osenv.name == "nt")
ENV_FILE = LOCAL_ENV_FILE if LOCAL_STACK else DEPLOY_ENV_FILE
if not ENV_FILE.exists():
    # Say which one was missing. A silent fallback to the other file is how
    # a developer machine ends up talking to the cluster without knowing.
    _other = DEPLOY_ENV_FILE if LOCAL_STACK else LOCAL_ENV_FILE
    print(f"[env] {ENV_FILE.name} not found — falling back to {_other.name}",
          file=__import__("sys").stderr)
    ENV_FILE = _other



def drop_preloaded(environ, selected: dict, other: dict) -> None:
    """Undo what another loader put in *environ* from the file not selected.

    `operonx-run` loads `./.env` (operonx 1.10, `cli/run.py`) before it
    imports the application — before this module picks `local.env`. With
    `override=False`, every key `.env` set would then beat `local.env`: a
    developer run on the local stack talking to the cluster, the half-local,
    half-remote mix this file exists to prevent. A key whose value is still
    exactly the other file's is taken to be that loader's, not the shell's,
    and is dropped (or given the selected file's value).
    """
    for key, value in other.items():
        if value is None or environ.get(key) != value:
            continue
        if selected.get(key) is not None:
            environ[key] = selected[key]
        else:
            del environ[key]


if ENV_FILE == LOCAL_ENV_FILE and DEPLOY_ENV_FILE.exists():
    from dotenv import dotenv_values as _dotenv_values

    drop_preloaded(_osenv.environ, _dotenv_values(LOCAL_ENV_FILE), _dotenv_values(DEPLOY_ENV_FILE))
load_dotenv(ENV_FILE, override=False)

# Silence pydantic serializer noise emitted when Anthropic responses carry
# `reasoning` content blocks (list-shaped) into an OpenAI ChatCompletion pydantic
# model that expects `content: str`. Cosmetic — model output is unaffected.
import warnings as _warnings  # noqa: E402
_warnings.filterwarnings("ignore", message=r".*PydanticSerializationUnexpectedValue.*")
_warnings.filterwarnings("ignore", category=UserWarning, module=r"pydantic\.main")

import operonx.providers  # noqa: E402,F401 — registers the resource categories

# ----- the ResourceHub -------------------------------------------------------
#
# Installed explicitly from a path anchored to the repo (`_ROOT_DIR` comes
# from this file's location), never the current working directory: a
# CWD-relative lookup finds a different config depending on where the
# process was launched, and a pod that cd's elsewhere silently gets no
# resources at all.
#
# `OPERONX_CONFIG` overrides the path.
from operonx.core.registry import ResourceHub  # noqa: E402


def _resources_path() -> _pathlib.Path:
    raw = _osenv.environ.get("OPERONX_CONFIG", "").strip()
    if not raw:
        return _ROOT_DIR / "resources.yaml"
    path = _pathlib.Path(raw)
    # A bare name or relative path means "in this repo", never "wherever
    # this process happens to be standing".
    return path if path.is_absolute() else _ROOT_DIR / path


RESOURCES_FILE = _resources_path()
if ResourceHub._instance is None:
    ResourceHub.set_instance(ResourceHub.from_yaml(RESOURCES_FILE))


# ----- LLM usage logger (cache hit visibility) ------------------------------
#
# Anthropic returns cache_read_input_tokens / cache_creation_input_tokens but
# operonx doesn't surface them. We patch the OpenAI provider's generate
# coroutine to record the last usage object on the resource instance and,
# when HUSH_USAGE_LOG is set, emit a one-liner to stderr per call.
import sys as _sys  # noqa: E402

from operonx.providers.llms import openai as _openai_llm  # noqa: E402

_USAGE_LOG = _env_bool("HUSH_USAGE_LOG")  # per-call stderr log, off by default
_ORIG_GENERATE = _openai_llm.OpenAISDKModel.generate

# Cumulative counters — runners read for progress-bar postfix. Anthropic
# returns cache_read_input_tokens / cache_creation_input_tokens flat; Gemini
# returns implicit cache nested at prompt_tokens_details.cached_tokens and
# reasoning at completion_tokens_details.reasoning_tokens. Both shapes handled.
USAGE_TOTAL: dict[str, float] = {
    "calls": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "reasoning_tokens": 0,
    "cache_read_tokens": 0,
    "cache_creation_tokens": 0,
    "cost_usd": 0.0,
}

# Anthropic cached-input priced at 10% of input, cache-write at 125% (~25%
# premium). Gemini implicit cache priced at 25% of input (~75% discount). We
# key by provider heuristic on the model string — resource.config carries the
# per-token rates; multipliers below are applied to cost_per_input_token.
_CACHE_READ_MULT_DEFAULT = 0.25   # Gemini implicit cache
_CACHE_READ_MULT_ANTHROPIC = 0.1  # Anthropic ephemeral cache read
_CACHE_WRITE_MULT_ANTHROPIC = 1.25



def _get_nested(u, path: str):
    """Read `foo.bar` from usage object — model_dump dict OR pydantic model."""
    obj = u
    for part in path.split("."):
        if obj is None:
            return 0
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            obj = getattr(obj, part, None)
    return obj or 0


# Defaults tuned for observed stall behaviour:
#   - Healthy LLM call: < 30s. Long-context Claude Sonnet: 60-90s.
#   - A stall is an HTTP request that never returns → retry once, then fail.
# Worst case per stalling LLM call = 90s × 2 attempts = 180s.
# Increase via env if a workload legitimately needs longer.
_LLM_TIMEOUT_SECS = _env_number("LLM_CALL_TIMEOUT_SECS", 90.0)
_LLM_RETRIES = _env_number("LLM_CALL_RETRIES", 1)


def _op_in_flight() -> str:
    """Name of the LLMOp whose call we are inside, found by walking the stack.

    This patch sits on the *LLM*, which has no idea which op is using it,
    so a timeout could only ever name the model — and two resource keys
    (`db-gemini-3-flash` and `-high`) share one model string. A batch that
    died with five identical lines therefore could not say whether the
    scanner or the decider stalled, which is the only thing worth knowing.

    Walks `f_back` rather than `inspect.stack()`: the latter reads source
    context for every frame. Only ever called on the timeout path, so even
    that would be affordable — but there is no reason to pay it.
    """
    frame = _sys._getframe()
    while frame is not None:
        candidate = frame.f_locals.get("self")
        name = getattr(candidate, "name", None)
        if name and type(candidate).__name__.endswith("LLMOp"):
            return str(name)
        frame = frame.f_back
    return "?"


def _prompt_shape(args, kwargs) -> str:
    """`messages=N, chars=N` for the payload that did not come back.

    Messages arrive positionally from the Databricks subclasses — their
    `generate` calls `super().generate(self._normalize_messages(messages),
    …)` — and by keyword from anything calling the base directly. Read
    both, because guessing wrong is how a diagnostic reports nothing.

    A stalled call and an accidentally-enormous prompt look identical in a
    timeout line that omits the size.
    """
    messages = args[0] if args else kwargs.get("messages")
    if not isinstance(messages, (list, tuple)):
        return "messages=?"
    total = 0
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, (list, tuple)):
            total += sum(
                len(p.get("text", "")) for p in content if isinstance(p, dict)
            )
    return f"messages={len(messages)}, chars={total}"


async def _generate_with_deadline(self, *args, **kwargs):
    """Call _ORIG_GENERATE under a client-side deadline, with retry.

    Databricks / AIHub endpoints occasionally stall on long-context calls
    (single Claude Sonnet calls have hung > 10 min); without a deadline the
    pipeline blocks forever. Retry up to LLM_CALL_RETRIES times, then raise
    a normal exception, which fails the call (recorded as `{"error"}`).
    """
    import asyncio as _asyncio
    last_exc: Exception | None = None
    for attempt in range(_LLM_RETRIES + 1):
        try:
            return await _asyncio.wait_for(
                _ORIG_GENERATE(self, *args, **kwargs),
                timeout=_LLM_TIMEOUT_SECS,
            )
        except _asyncio.TimeoutError as _exc:
            last_exc = _exc
            model = (getattr(getattr(self, "config", None), "model", "") or "?")
            print(
                f"[llm timeout] op={_op_in_flight()} model={model} "
                f"exceeded {_LLM_TIMEOUT_SECS:.0f}s "
                f"(attempt {attempt + 1}/{_LLM_RETRIES + 1}) "
                f"[{_prompt_shape(args, kwargs)}]",
                file=_sys.stderr, flush=True,
            )
            if attempt >= _LLM_RETRIES:
                raise TimeoutError(
                    f"LLM {model!r} exceeded {_LLM_TIMEOUT_SECS:.0f}s "
                    f"after {_LLM_RETRIES + 1} attempts"
                ) from _exc
    # Unreachable — loop either returns or raises.
    raise last_exc  # type: ignore[misc]


async def _generate_with_usage_log(self, *args, **kwargs):
    resp = await _generate_with_deadline(self, *args, **kwargs)
    try:
        u = resp.usage
        try:
            self.last_usage = u.model_dump()
        except Exception:
            self.last_usage = {"raw": repr(u)}

        pt = getattr(u, "prompt_tokens", 0) or 0
        ct = getattr(u, "completion_tokens", 0) or 0
        # Anthropic flat fields (Win AIHub + Databricks proxy return these)
        cr = getattr(u, "cache_read_input_tokens", 0) or 0
        cw = getattr(u, "cache_creation_input_tokens", 0) or 0
        # Gemini nested: prompt_tokens_details.cached_tokens
        cr = cr or _get_nested(u, "prompt_tokens_details.cached_tokens")
        # Reasoning tokens: Databricks AI Gateway puts them FLAT at
        # `usage.reasoning_tokens` (not nested under completion_tokens_details
        # like OpenAI convention). Gemini native puts them at
        # `usageMetadata.thoughtsTokenCount`. Anthropic rolls them into
        # completion_tokens with no split field. Read flat first, then nested.
        rt = getattr(u, "reasoning_tokens", 0) or 0
        if not rt:
            rt = _get_nested(u, "completion_tokens_details.reasoning_tokens")

        # USD cost — per-resource rates from config; cached tokens discounted
        cfg = getattr(self, "config", None)
        pi = getattr(cfg, "cost_per_input_token", None) if cfg else None
        po = getattr(cfg, "cost_per_output_token", None) if cfg else None
        model_str = (getattr(cfg, "model", "") or "").lower() if cfg else ""
        is_anthropic = "claude" in model_str
        cache_read_mult = _CACHE_READ_MULT_ANTHROPIC if is_anthropic else _CACHE_READ_MULT_DEFAULT
        cost = 0.0
        if pi and po:
            uncached_in = max(0, pt - cr)
            cost += uncached_in * pi
            cost += cr * pi * cache_read_mult
            if is_anthropic:
                cost += cw * pi * _CACHE_WRITE_MULT_ANTHROPIC
                cost += ct * po  # Anthropic rolls thinking into completion_tokens
            else:
                # Gemini: reasoning_tokens is SEPARATE from completion_tokens
                # and billed at the same rate as output. Add both.
                cost += (ct + rt) * po

        USAGE_TOTAL["calls"] += 1
        USAGE_TOTAL["prompt_tokens"] += pt
        USAGE_TOTAL["completion_tokens"] += ct
        USAGE_TOTAL["reasoning_tokens"] += rt
        USAGE_TOTAL["cache_read_tokens"] += cr
        USAGE_TOTAL["cache_creation_tokens"] += cw
        USAGE_TOTAL["cost_usd"] += cost

        if _USAGE_LOG:
            tag = "HIT" if cr > 0 else ("WRITE" if cw > 0 else "MISS")
            print(
                f"  ⚡ [{tag}] in={pt} out={ct} read={cr} write={cw} "
                f"think={rt} ${cost:.4f}",
                file=_sys.stderr, flush=True,
            )
    except AttributeError:
        pass
    return resp


_openai_llm.OpenAISDKModel.generate = _generate_with_usage_log


# ----- gRPC teardown noise ---------------------------------------------------
#
# The Triton client's gRPC channel prints `'NoneType' object has no attribute
# 'POLLER'` at interpreter exit. Below a run's verdict it reads as a failed
# run, while the exit code is unaffected. Matched on the exception, so
# anything else unraisable still prints. (One of the two copies fires after
# Python resets the hook and cannot be caught.)
_PREVIOUS_UNRAISABLE = _sys.unraisablehook


def _quiet_grpc_teardown(unraisable) -> None:
    exc = unraisable.exc_value
    if isinstance(exc, AttributeError) and "POLLER" in str(exc):
        return
    _PREVIOUS_UNRAISABLE(unraisable)


_sys.unraisablehook = _quiet_grpc_teardown
