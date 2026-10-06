"""The score job's ends: `Calls`, the input files that carry a call_code
(the job's items), and `Outputs`, one JSON out per call."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

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
    `skipped` — the graph needs the call_code to route a call at all. With
    *outputs*, a call whose output is already there (`Outputs.exists`) is
    skipped too, never read: re-running over a folder does only what is
    missing.
    """

    def __init__(
        self,
        input_dir: "str | Path | None" = None,
        files: Optional[List[str]] = None,
        files_list: "str | Path | None" = None,
        outputs: "Optional[Outputs]" = None,
    ):
        self.outputs = outputs
        self.input_dir = Path(input_dir) if input_dir else None
        self.files = [Path(f) for f in files] if files else None
        self.files_list = Path(files_list) if files_list else None
        self.skipped = 0

    def paths(self) -> List[Path]:
        if self.files is not None or self.files_list is not None:
            listed = read_files_list(self.files_list) if self.files_list else []
            return sorted([*(self.files or []), *map(Path, listed)])
        return sorted(self.input_dir.glob("*.json")) if self.input_dir else []

    async def __aiter__(self) -> AsyncIterator[Dict[str, Any]]:
        for path in self.paths():
            if self.outputs is not None and self.outputs.exists(path.stem):
                continue
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


class Outputs:
    """One JSON per call, `<path>/<name>.json`, written whole (to a temporary
    name, then renamed) so a killed run never leaves half a file.

    `write` is the job's `output=`; `fail` writes a failed call's file as
    `{"error": ...}` under *write_errors*, so every input has an output a
    reader can check. With *skip_existing*, a call whose file is there is
    not scored again — but a file holding `{"error": ...}` (or one that is
    not JSON) is not "already there": a rerun scores that call again.
    """

    def __init__(self, path: "str | Path", *, skip_existing: bool = False,
                 write_errors: bool = False):
        self.path = Path(path)
        self.skip_existing = skip_existing
        self.write_errors = write_errors

    def file_for(self, key: str) -> Path:
        return self.path / f"{key}.json"

    def exists(self, key: str) -> bool:
        if not (self.skip_existing and self.file_for(key).exists()):
            return False
        try:
            return "error" not in json.loads(self.file_for(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False

    def write(self, key: str, result: Any) -> None:
        self._put(key, result)

    def fail(self, key: str, error: str) -> None:
        if self.write_errors:
            self._put(key, {"error": error})

    def _put(self, key: str, item: Any) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        target = self.file_for(key)
        tmp = target.with_name(target.name + ".part")
        tmp.write_text(json.dumps(item, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(target)

    def __repr__(self) -> str:
        return f"dir({self.path}/*.json)"
