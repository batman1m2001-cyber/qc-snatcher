"""The image must carry every file the code reads at import.

models.yaml became the only routing source and config.py reads it at
import, but the Dockerfile never copied it: the next image would have
raised FileNotFoundError on the first `import src.core.config`.
"""
import re

import pytest

from tests._paths import ROOT
COPIED = {m.group(1).lstrip("./").rstrip("/")
          for m in re.finditer(r"^COPY\s+(\S+)\s+\S+", (ROOT / "Dockerfile").read_text(encoding="utf-8"), re.M)}


@pytest.mark.parametrize("needed", ["models.yaml", "resources.yaml", "src", "app", "operonx.toml", "knowledge", "main.py"])
def test_image_copies(needed):
    assert needed in COPIED, f"Dockerfile does not COPY {needed}"
