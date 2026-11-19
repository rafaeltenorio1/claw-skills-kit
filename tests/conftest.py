"""Shared test setup.

The library's pins fix OpenClaw 2026.11.3 and Node 24.22.1 (the Docker image), and `reconcile` refuses a host that
runs other versions. Tests must not depend on whatever this machine has installed, so by default `openclaw` and `node`
are fakes reporting the pinned versions. Tests that need their own fake set CSK_OPENCLAW again.
"""
import shlex
import sys
from pathlib import Path

import pytest

FAKE = Path(__file__).parent / "fake_openclaw.py"


@pytest.fixture(autouse=True)
def pinned_runtime(tmp_path_factory, monkeypatch):
    state = tmp_path_factory.mktemp("fake-openclaw-state")
    monkeypatch.setenv("CSK_OPENCLAW", shlex.join([sys.executable, str(FAKE), str(state)]))
    monkeypatch.setenv("CSK_NODE", shlex.join([sys.executable, "-c", "print('v24.22.1')"]))
