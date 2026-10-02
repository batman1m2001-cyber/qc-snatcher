"""One grammar for environment variables.

Booleans: `1 true yes on` and `0 false no off`, any case. Numbers: an int
or a float. Empty or unset is the default; anything else raises, naming the
variable — a typo such as `QC_ENABLE_RABA=flase` must not quietly keep a
case running, and `HUSH_USAGE_LOG=false` must not turn the log on.

Each reader takes the mapping to read (`os.environ` when omitted), so a
test passes a dict instead of setting the process environment. A leaf
module, so `_bootstrap` can use it before anything else is imported.
"""
import os
from typing import Mapping, Optional, TypeVar

TRUE = frozenset({"1", "true", "yes", "on"})
FALSE = frozenset({"0", "false", "no", "off"})

N = TypeVar("N", int, float)


def env_str(name: str, default: str = "", env: Optional[Mapping[str, str]] = None) -> str:
    return (os.environ if env is None else env).get(name, "").strip() or default


def env_bool(name: str, default: bool = False, env: Optional[Mapping[str, str]] = None) -> bool:
    raw = (os.environ if env is None else env).get(name, "")
    token = raw.strip().lower()
    if not token:
        return default
    if token in TRUE:
        return True
    if token in FALSE:
        return False
    raise ValueError(f"{name}={raw!r} is not a boolean. Use one of {sorted(TRUE | FALSE)}.")


def env_number(name: str, default: N, env: Optional[Mapping[str, str]] = None) -> N:
    """An int or a float, as *default* is."""
    raw = (os.environ if env is None else env).get(name, "")
    if not raw.strip():
        return default
    try:
        return type(default)(raw.strip())
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not {'an integer' if isinstance(default, int) else 'a number'}.") from None
