"""Polymarket 요청 전용 프록시 세션 팩토리.

gamma-api.polymarket.com이 이 서버 출구 IP의 지역을 `HTTP 451`로 막을 때만
쓴다(docs/server-ops.md 8-4). `PolymarketClient`·`PolymarketHistoryClient`는
생성 시 `session=`을 받는 것만 알고 그 세션이 프록시를 쓰는지는 모른다 —
그래서 이 모듈 하나만 있고 없고로 프록시 경유 여부가 갈린다. 붙일 때도
뗄 때도 두 클라이언트 코드는 건드리지 않는다.
"""

from __future__ import annotations

import requests


def build_polymarket_session(proxy_url: str) -> requests.Session | None:
    """`proxy_url`이 비어 있으면 None(직접 호출 그대로), 있으면 그 프록시를 문 세션.

    http/https 프록시는 `requests`가 바로 지원한다. socks5는 서버에
    `pysocks`가 먼저 있어야 한다 — 이 프로젝트 requirements에는 없다.
    """
    if not proxy_url:
        return None
    session = requests.Session()
    session.proxies = {"http": proxy_url, "https": proxy_url}
    return session
