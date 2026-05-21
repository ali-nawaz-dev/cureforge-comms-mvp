"""Phase 5: Streamlit smoke test using AppTest.

Just enough to assert the dashboard imports and constructs its initial
session_state without crashing. Detailed UI interactions are out of scope –
the goal is to catch import / wiring regressions in CI.
"""
from __future__ import annotations

import pytest

pytest.importorskip("streamlit.testing.v1")


def test_dashboard_renders_initial_state() -> None:
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file("apps/dashboard/app.py")
    app.run(timeout=10)
    # The dashboard should have populated session_state with the bus, queue,
    # ledger, and workers regardless of any uploaded data.
    state = app.session_state
    assert "bus" in state
    assert "queue" in state
    assert "ledger" in state
    assert "matcher_worker" in state
    assert "outreach_worker" in state
