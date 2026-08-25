"""Polymarket 요청 전용 프록시 세션 팩토리.

gamma-api.polymarket.com이 이 서버 출구 IP의 지역을 `HTTP 451`로 막을 때만
쓴다(docs/server-ops.md 8-4). `PolymarketClient`·`PolymarketHistoryClient`는
생성 시 `session=`을 받는 것만 알고 그 세션이 프록시를 쓰는지는 모른다 —
그래서 이 모듈 하나만 있고 없고로 프록시 경유 여부가 갈린다. 붙일 때도
뗄 때도 두 클라이언트 코드는 건드리지 않는다.
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


class _ProxyFallbackSession(requests.Session):
    """프록시가 연결 불능이면 이후 요청을 직접 보내는 읽기 전용 세션.

    Gamma가 돌려준 HTTP 451 같은 응답에는 개입하지 않는다. 프록시 서버 자체에
    연결하지 못한 경우와 프록시 경유 timeout만 failover 대상으로 삼는다.
    한 번 failover한 뒤에는 같은 스냅숏의 나머지 페이지에서 죽은 프록시를 매번
    다시 기다리지 않는다.
    """

    def __init__(self, proxy_url: str):
        super().__init__()
        self.proxies = {"http": proxy_url, "https": proxy_url}
        self._direct_session = requests.Session()
        self._direct_session.trust_env = False
        self._proxy_available = True

    def request(self, method, url, **kwargs):
        if self._proxy_available:
            try:
                return super().request(method, url, **kwargs)
            except (requests.exceptions.ProxyError, requests.Timeout):
                self._proxy_available = False
                logger.warning(
                    "[POLYMARKET] 프록시 연결 실패; 이번 프로세스에서는 직접 연결로 전환합니다."
                )
        return self._direct_session.request(method, url, **kwargs)


def build_polymarket_session(proxy_url: str) -> requests.Session | None:
    """`proxy_url`이 비어 있으면 None(직접 호출 그대로), 있으면 그 프록시를 문 세션.

    http/https 프록시는 `requests`가 바로 지원한다. socks5는 서버에
    `pysocks`가 먼저 있어야 한다 — 이 프로젝트 requirements에는 없다.
    """
    if not proxy_url:
        return None
    return _ProxyFallbackSession(proxy_url)
