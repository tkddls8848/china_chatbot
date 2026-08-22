"""폴리마켓 프록시 세션 팩토리(docs/server-ops.md 8-4)."""

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
