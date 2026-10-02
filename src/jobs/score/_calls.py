"""The score job's ends: `Calls`, the input files that carry a call_code,
and `Outputs`, one JSON out per call."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from operonx.app.jobs import DirSink

logger = logging.getLogger(__name__)


def read_files_list(path: "str | Path") -> List[str]:
    """Newline-separated paths; blank lines and `#` lines ignored. A list
    rather than arguments because Windows caps a command line at 32K."""
    out: List[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


class Calls:
    """The input files that carry a `metadata.call_code`, in name order.

    Which files: *files*, and those *files_list* names — or, when neither
    is given, every `*.json` in *input_dir*. The list file is read when the
    run starts, not when the job is declared.

    An item is `{"path", "name", "metadata"}`. A file with no call_code, or
    one that is not JSON, is skipped with a warning and counted in
    `skipped` — the graph needs the call_code to route a call at all.
    """

    def __init__(
        self,
        input_dir: "str | Path | None" = None,
        files: Optional[List[str]] = None,
        files_list: "str | Path | None" = None,
    ):
        self.input_dir = Path(input_dir) if input_dir else None
        self.files = [Path(f) for f in files] if files else None
        self.files_list = Path(files_list) if files_list else None
        self.skipped = 0

    def paths(self) -> List[Path]:
        if self.files is not None or self.files_list is not None:
            listed = read_files_list(self.files_list) if self.files_list else []
            return sorted([*(self.files or []), *map(Path, listed)])
        return sorted(self.input_dir.glob("*.json")) if self.input_dir else []

    async def items(self) -> AsyncIterator[Dict[str, Any]]:
        for path in self.paths():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Cannot read {path.name}: {e}")
                self.skipped += 1
                continue
            meta = data.get("metadata") or {}
            if not meta.get("call_code"):
                logger.warning(f"{path.name}: missing metadata.call_code, skipping")
                self.skipped += 1
                continue
            yield {"path": str(path), "name": path.stem, "metadata": meta}

    def __repr__(self) -> str:
        if self.files_list is not None:
            return f"calls({self.files_list})"
        return f"calls({self.input_dir or f'{len(self.files or [])} files'})"


class Outputs(DirSink):
    """One JSON per call. A call whose file holds `{"error": ...}` is not
    "already there": with `skip_existing`, a rerun scores it again rather
    than keeping the failure (operonx's `DirSink` counts any file)."""

    def exists(self, key: str) -> bool:
        if not super().exists(key):
            return False
        try:
            return "error" not in json.loads(self.file_for(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
