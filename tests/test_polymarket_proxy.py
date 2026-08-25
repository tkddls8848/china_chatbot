"""폴리마켓 프록시 세션 팩토리(docs/server-ops.md 8-4)."""

import requests

from features.market_sentiment.polymarket_proxy import build_polymarket_session


def test_empty_url_means_no_proxy():
    assert build_polymarket_session("") is None


def test_proxy_url_is_applied_to_both_schemes():
    session = build_polymarket_session("http://user:pass@proxy-host:8080")

    assert session is not None
    assert session.proxies == {
        "http": "http://user:pass@proxy-host:8080",
        "https": "http://user:pass@proxy-host:8080",
    }


def test_proxy_connection_failure_falls_back_to_direct(monkeypatch):
    calls = []
    direct_response = object()

    def request(_session, method, url, **kwargs):
        calls.append((method, url, kwargs))
        if len(calls) == 1:
            raise requests.exceptions.ProxyError("proxy is down")
        return direct_response

    monkeypatch.setattr(requests.Session, "request", request)
    session = build_polymarket_session("http://proxy-host:8080")

    assert session.get("https://gamma-api.example/markets", timeout=7) is direct_response
    assert len(calls) == 2


def test_direct_fallback_is_sticky_for_the_process(monkeypatch):
    sessions = []

    def request(current, method, url, **kwargs):
        sessions.append(current)
        if len(sessions) == 1:
            raise requests.Timeout("proxy timed out")
        return object()

    monkeypatch.setattr(requests.Session, "request", request)
    session = build_polymarket_session("http://proxy-host:8080")

    session.get("https://gamma-api.example/markets")
    session.get("https://gamma-api.example/markets?offset=100")

    assert len(sessions) == 3
    assert sessions[0] is session
    assert sessions[1] is sessions[2]
    assert sessions[1] is not session
    assert sessions[1].trust_env is False


def test_http_error_response_does_not_bypass_the_proxy(monkeypatch):
    response = object()
    calls = []

    def request(current, method, url, **kwargs):
        calls.append(current)
        return response

    monkeypatch.setattr(requests.Session, "request", request)
    session = build_polymarket_session("http://proxy-host:8080")

    assert session.get("https://gamma-api.example/markets") is response
    assert calls == [session]
