import httpx
import pytest

from robo_cortex.core.abstractor import generate_abstract


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=None, response=httpx.Response(self.status_code)
            )

    def json(self):
        return self._payload


def test_generate_abstract_success(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeResponse({"response": "  A short summary.  "})

    monkeypatch.setattr(httpx, "post", fake_post)

    assert generate_abstract("some long statement") == "A short summary."


def test_generate_abstract_connection_error_returns_none(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", fake_post)

    assert generate_abstract("some long statement") is None


def test_generate_abstract_timeout_returns_none(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "post", fake_post)

    assert generate_abstract("some long statement") is None


def test_generate_abstract_non_200_returns_none(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeResponse({}, status_code=500)

    monkeypatch.setattr(httpx, "post", fake_post)

    assert generate_abstract("some long statement") is None


def test_generate_abstract_malformed_json_returns_none(monkeypatch):
    class _BadResponse(_FakeResponse):
        def json(self):
            raise ValueError("not json")

    def fake_post(url, json=None, timeout=None):
        return _BadResponse({})

    monkeypatch.setattr(httpx, "post", fake_post)

    assert generate_abstract("some long statement") is None


def test_generate_abstract_missing_response_key_returns_none(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeResponse({"unexpected": "shape"})

    monkeypatch.setattr(httpx, "post", fake_post)

    assert generate_abstract("some long statement") is None


def test_generate_abstract_empty_input_never_calls_httpx(monkeypatch):
    def fake_post(*args, **kwargs):
        raise AssertionError("httpx.post should not be called for empty input")

    monkeypatch.setattr(httpx, "post", fake_post)

    assert generate_abstract("") is None
    assert generate_abstract("   ") is None
