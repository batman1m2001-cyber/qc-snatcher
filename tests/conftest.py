"""Project-wide pytest options, and the pinned environment (`tests/_env.py`)
— set here, before any test module imports `src`."""
from tests._env import pin

pin()


def pytest_addoption(parser):
    parser.addoption(
        "--update-signatures",
        action="store_true",
        default=False,
        help="re-record tests/fixtures/graph_signatures.json from the current graphs "
             "(only when the change to the graph is the one you meant)",
    )
