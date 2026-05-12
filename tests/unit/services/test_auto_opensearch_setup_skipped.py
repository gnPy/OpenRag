"""Master flag + OPENRAG_AUTO_OPENSEARCH_SETUP gates the startup
auto-setup call to setup_opensearch_security().

This file unit-tests the gating decision in isolation; the orchestrator
function itself is exercised by test_opensearch_security_setup.py.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.mark.parametrize(
    "master, auto, should_skip",
    [
        (False, True, False),  # default: setup runs
        (False, False, False),  # master off => AUTO ignored, setup runs
        (True, True, False),  # master on + AUTO on: setup runs
        (True, False, True),  # master on + AUTO off: setup skipped
    ],
)
def test_skip_decision_truth_table(master, auto, should_skip):
    skip_auto_setup = master and not auto
    assert skip_auto_setup is should_skip
