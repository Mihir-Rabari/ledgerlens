"""Shared fixtures: a live FalkorDB with freshly seeded tenants.

Tests are end-to-end by design: they exercise real FalkorDB semantics, the
exact algorithm signatures the product depends on, and the isolation that the
multigraph topology gives us. If FalkorDB is unreachable the suite fails
loudly rather than skipping silently.
"""

import pathlib
import subprocess
import sys

import pytest

from ledgerlens.graph import connection

ROOT = pathlib.Path(__file__).parent.parent
FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def seeded():
    conn = connection()
    conn.client.execute_command("PING")  # fails the session loudly if FalkorDB is down
    subprocess.run(
        [sys.executable, str(ROOT / "seed.py"), "--wipe"],
        check=True,
        capture_output=True,
        timeout=300,
    )
    yield conn


@pytest.fixture()
def truth_aurora() -> dict:
    import json

    return json.loads((FIXTURES / "planted_aurora.json").read_text())


@pytest.fixture()
def truth_nimbus() -> dict:
    import json

    return json.loads((FIXTURES / "planted_nimbus.json").read_text())


@pytest.fixture()
def truth_verdant() -> dict:
    import json

    return json.loads((FIXTURES / "planted_verdant.json").read_text())
