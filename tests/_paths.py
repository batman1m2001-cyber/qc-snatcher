"""Where the repo is, for tests at any depth under `tests/`."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
