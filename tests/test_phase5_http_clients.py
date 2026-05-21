"""Phase 5: respx-based tests for Resend + LLM HTTP clients."""
from __future__ import annotations

import pytest

pytest.importorskip("respx")


# ---------------------------------------------------------------------------
# Resend client — uses urllib under the hood, so respx (httpx) cannot intercept.
# We test the client by monkeypatching urllib.request.urlopen.
# ---------------------------------------------------------------------------


def test_resend_client_marks_failed_response_unsuccessful(monkeypatch) -> None:
    from services.outreach.resend_client import ResendClient
    import urllib.error
    import urllib.request

    monkeypatch.setenv("RESEND_API_KEY", "rk_test")
    monkeypatch.setenv("RESEND_SANDBOX_TO", "sandbox@example.com")

    def _raise(req, timeout=15):
        raise urllib.error.HTTPError(req.full_url, 502, "bad gateway", {}, fp=None)

    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    client = ResendClient(api_key="rk_test", mode="sandbox", sandbox_to="sandbox@example.com")
    result = client.send(to="target@example.com", subject="hi", html_body="<p>hi</p>")
    assert result.success is False
    assert "502" in (result.error or "")


def test_resend_client_returns_success_on_200(monkeypatch) -> None:
    from services.outreach.resend_client import ResendClient
    import urllib.request

    monkeypatch.setenv("RESEND_API_KEY", "rk_test")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"id": "msg_42"}'

    def _ok(req, timeout=15):
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", _ok)
    client = ResendClient(api_key="rk_test", mode="sandbox", sandbox_to="sandbox@example.com")
    result = client.send(to="t@example.com", subject="s", html_body="<p>h</p>")
    assert result.success is True
    assert result.email_id == "msg_42"


def test_groq_client_maps_500_to_transient_error(monkeypatch) -> None:
    """5xx responses raise LLMTransientError so retries can take over."""
    from packages.llm.http_clients import GroqLLMClient, LLMTransientError
    import urllib.error
    import urllib.request

    monkeypatch.setenv("GROQ_API_KEY", "gk")

    def _raise(req, timeout=30):
        raise urllib.error.HTTPError(req.full_url, 503, "boom", {}, fp=None)

    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    client = GroqLLMClient(api_key="gk")
    with pytest.raises(LLMTransientError):
        client.complete("hi")
