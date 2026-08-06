"""Shared test fixtures."""

from __future__ import annotations

import pytest

from engine import database
from engine import main as engine_main


@pytest.fixture(autouse=True)
def plaintext_by_default(monkeypatch):
    """Run protocol tests without TLS unless a test asks for it.

    TLS is presence-based: once certificates exist on the machine, clients
    enable it automatically. That is right for a deployment and wrong for tests
    that stand up their own plaintext server — a developer who had generated
    certificates would see the whole suite fail for reasons unrelated to what
    it is testing.

    Transport encryption has its own coverage in test_tls.py, and
    test_integration.py opts back in for one end-to-end run over TLS.

    Patched on the *connection* modules, not on config: both import the flag by
    value at import time, so patching config alone would have no effect.
    """
    monkeypatch.setattr("client.connection.TLS_ENABLED", False)
    monkeypatch.setattr("admin_gui.connection.TLS_ENABLED", False)


@pytest.fixture(autouse=True)
def fresh_shutdown_event():
    """Give each test its own Engine shutdown event.

    engine.main creates it lazily per loop, but the module global still has to
    be cleared between tests: a leaked set() would make every subsequent
    connection handler exit immediately, and a leaked event from a closed loop
    raises RuntimeError. Teardown runs even when a test fails, which is the
    whole point of doing this here rather than inside each test.
    """
    engine_main.reset_shutdown()
    yield
    engine_main.reset_shutdown()


@pytest.fixture(autouse=True)
def isolated_database(tmp_path):
    """Point engine.database at a fresh per-test file.

    Autouse and repo-wide on purpose. engine.database holds its path and its
    connection in module globals, so without this any test that touches the
    Engine writes to the real monitoring.db in the repository root — and
    whichever test happened to run first would silently decide where every
    later test wrote.
    """
    database.set_database_path(tmp_path / "test.db")
    database.init_database()
    yield
    database.close_database()
