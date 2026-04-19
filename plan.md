🇨🇳 중국·홍콩 증시 텔레그램 미니앱 봇 — 개발 계획서
프로젝트명: TBD
버전: 0.1.0
작성일: 2026-04-19
목표 시장: 상해 메인보드, 선전 메인보드, 과창판(STAR), 창업판(ChiNext), 홍콩(HKEX)
운영 형태: 1인 전용

1. 프로젝트 개요
1.1 서비스 개요
중국 A주(상해·선전·과창판·창업판) 및 홍콩 H주·항셍 시장 정보를 제공하는 텔레그램 미니앱(WebApp) 기반 증시 정보 봇.
시장 지수, 종목 검색, 뉴스, 경제 캘린더, 관심종목 알림을 제공하는 순수 정보 채널. LLM 없음.
1.2 확정 사항
항목결정구현 형태텔레그램 미니앱 (WebApp)봇 수신 방식Polling (Webhook 미사용)백엔드 언어Python 3.12.x웹 프레임워크FastAPI목표 시장상해 / 선전 / 과창판 / 창업판 / 홍콩 (5개)시장 데이터akshare (중국 A주 — 지수·종목·시총·경제지표), yfinance (홍콩)뉴스 데이터RSS 피드 (feedparser) — RSSHub 자체 인스턴스 경유LLM없음사용자 범위1인 전용데이터베이스SQLite (파일 기반)배포 플랫폼로컬 / 자체 서버RSS 인프라RSSHub (Docker, localhost:1200)
1.3 핵심 기능
기능설명시장 지수 조회5개 시장 실시간(15분 지연) 지수 현황종목 검색 및 상세티커/종목명 검색, 가격·차트시가총액 상위시장별 시총 상위 종목 리스트경제 캘린더PBOC 정책, PMI, CPI 등 주요 경제지표 일정뉴스 피드RSSHub 경유 RSS 피드 취합 기반 중국·홍콩 시장 뉴스관심종목 알림관심종목 등록 및 임계값 가격 알림

Polling 채택 이유
1인 전용 운영 환경에서는 사용자 메시지 수신량이 적으므로 Polling으로 충분하다.
Webhook은 공개 HTTPS 엔드포인트가 필수인 반면, Polling은 서버가 텔레그램 API에
주기적으로 요청을 보내는 방식이라 로컬 환경에서도 즉시 동작한다.
미니앱(WebApp) URL은 HTTPS가 여전히 필요하므로 개발 시 ngrok, 운영 시 자체 도메인을 사용한다.

2. 시스템 아키텍처
┌──────────────────────────────────────────────────────┐
│                   텔레그램 클라이언트                 │
│  ┌───────────────┐       ┌──────────────────────────┐ │
│  │   챗봇 명령어  │       │     미니앱 (WebApp)       │ │
│  │   /start      │       │     HTML/CSS/Vanilla JS   │ │
│  │   /market     │       │     Chart.js              │ │
│  │   /news       │       │     Telegram WebApp SDK   │ │
│  └───────┬───────┘       └─────────────┬────────────┘ │
└──────────┼──────────────────────────────┼────────────┘
           │ Telegram Bot API (Polling)    │ HTTPS
           ▼                               ▼
┌──────────────────────────────────────────────────────┐
│              Python Backend (로컬 / 자체 서버)        │
│  ┌──────────────────────┐  ┌────────────────────────┐ │
│  │ python-telegram-bot  │  │  FastAPI + uvicorn      │ │
│  │ v21 (Polling 모드)   │  │  (미니앱 API 전용)      │ │
│  └──────────────────────┘  └────────────┬───────────┘ │
│                                          │             │
│  ┌───────────────────────────────────────▼───────────┐ │
│  │                    서비스 레이어                   │ │
│  │  MarketService │ StockService │ NewsService        │ │
│  │  CalendarService │ AlertService                    │ │
│  └───────────────────────────────────────┬───────────┘ │
│                                          │             │
│  ┌───────────────────────────────────────▼───────────┐ │
│  │                    데이터 레이어                   │ │
│  │  AkshareClient (지수·종목·시총·경제지표)           │ │
│  │  YfinanceClient (홍콩)                             │ │
│  │  RssClient → RSSHub (localhost:1200)               │ │
│  └───────────────────────────────────────┬───────────┘ │
│                                          │             │
│  ┌───────────────────────────────────────▼───────────┐ │
│  │                SQLite (로컬 파일)                  │ │
│  │  watchlist │ alerts │ index_cache                  │ │
│  └────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────┘
           ▲
           │ HTTP (localhost:1200)
┌──────────┴───────────────────────────────────────────┐
│              RSSHub (Docker, 포트 1200)               │
│  财联社 · 东方财富 · 新浪财经 · 上交所 · SCMP · Reuters │
└──────────────────────────────────────────────────────┘

3. 기술 스택
3.1 백엔드
패키지버전용도python3.12.x런타임python-telegram-bot21.x텔레그램 봇 API (Polling)fastapi0.111.xREST API 서버 (미니앱 전용)uvicorn[standard]0.29.xASGI 서버akshare최신중국 A주 — 지수·종목·시총·경제지표yfinance0.2.x홍콩·글로벌 지수feedparser≥6.0RSS 피드 파싱 (RSSHub 응답 파싱)httpx0.27.x비동기 HTTP 클라이언트 (RSSHub fetch 포함)apscheduler3.10.x스케줄 작업sqlalchemy2.0.xORMalembic1.13.xDB 마이그레이션pydantic-settings2.x환경변수 관리
3.2 프론트엔드 (미니앱)
기술용도HTML5 / CSS3마크업·스타일Vanilla JS (ES6+)인터랙션Chart.js 4.x주가 차트Telegram WebApp JS SDK텔레그램 브릿지·테마
3.3 인프라
항목개발운영실행 환경로컬 PC자체 서버DBSQLite 파일SQLite 파일HTTPSngrok자체 도메인 + Let's EncryptRSSHubDocker (localhost:1200)Docker (localhost:1200, 외부 미노출)

RSSHub는 외부에 노출할 필요 없이 백엔드와 같은 호스트에서 내부 통신만 하면 된다.
운영 환경에서도 포트 1200은 방화벽으로 외부 차단 권장.


4. 프로젝트 구조
{project-name}/
├── .env
├── .env.example
├── .gitignore
├── .python-version
├── docker-compose.yml       # RSSHub 컨테이너 포함
├── Makefile
├── requirements.txt
├── requirements-dev.txt
│
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
├── data/
│   └── app.db               # SQLite 파일 (gitignore 대상)
│
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── exceptions.py
│   │
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── main.py          # Polling 실행 진입점
│   │   ├── handlers/
│   │   │   ├── __init__.py
│   │   │   ├── start.py
│   │   │   ├── market.py
│   │   │   ├── news.py
│   │   │   └── alert.py
│   │   └── keyboards.py
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── deps.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── market.py      # GET /api/market
│   │       ├── stock.py       # GET /api/stock
│   │       ├── news.py        # GET /api/news
│   │       ├── calendar.py    # GET /api/calendar
│   │       ├── watchlist.py   # CRUD /api/watchlist
│   │       ├── alert.py       # CRUD /api/alert
│   │       └── admin.py       # /api/admin/*
│   │       # webhook.py 없음 — Polling 방식이므로 불필요
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── market_service.py
│   │   ├── stock_service.py
│   │   ├── news_service.py    # rss_client 의존
│   │   ├── calendar_service.py
│   │   └── alert_service.py
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   ├── akshare_client.py  # 지수·종목·시총·경제지표 전용
│   │   ├── yfinance_client.py
│   │   └── rss_client.py      # RSSHub 경유 RSS 취합 (신규)
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── session.py
│   │   └── models/
│   │       ├── __init__.py
│   │       ├── watchlist.py   # user_id 외래키 없음 (1인 전용)
│   │       └── alert.py
│   │
│   └── scheduler/
│       ├── __init__.py
│       └── jobs.py
│
└── frontend/
    ├── index.html
    ├── market.html
    ├── stock.html
    ├── news.html
    ├── calendar.html
    ├── watchlist.html
    ├── settings.html
    ├── admin.html
    └── static/
        ├── css/
        │   ├── base.css
        │   ├── components.css
        │   └── telegram-theme.css
        └── js/
            ├── api.js
            ├── chart.js
            ├── telegram.js
            └── utils.js

5. 환경변수
dotenv# .env.example

# ── 텔레그램 ──────────────────────────────────────────
TELEGRAM_BOT_TOKEN=
WEBAPP_URL=                  # ngrok URL (개발) 또는 자체 도메인 (운영)

# ── 데이터베이스 ───────────────────────────────────────
DATABASE_URL=sqlite:///./data/app.db

# ── 앱 설정 ───────────────────────────────────────────
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=INFO

# ── 캐시 ──────────────────────────────────────────────
CACHE_TTL_SECONDS=900

# ── RSSHub ────────────────────────────────────────────
RSSHUB_BASE_URL=http://localhost:1200   # Docker 내부망이면 http://rsshub:1200

# ── RSS 피드 ──────────────────────────────────────────
RSS_FEED_URLS=http://localhost:1200/cls/telegraph,http://localhost:1200/cls/hot,http://localhost:1200/eastmoney/report/strategyreport,http://localhost:1200/eastmoney/search/A股,http://localhost:1200/sina/news/stock,http://localhost:1200/sse/disclosure,http://localhost:1200/jisilu/explore/category-4__sort_type-hot__day-30,http://localhost:1200/scmp/section/2,http://localhost:1200/reuters/cn
RSS_SOURCE_LABELS=财联社전보,财联社인기,东方财富리서치,东方财富A株,新浪财经,上交所공시,集思录채권,SCMP,Reuters
RSS_MAX_ITEMS_PER_FEED=20
RSS_FETCH_TIMEOUT=10

# ── 어드민 ─────────────────────────────────────────────
ADMIN_TOKEN=change-me        # 반드시 변경

RSSHUB_BASE_URL은 docker-compose 네트워크 구성에 따라 http://rsshub:1200으로 변경한다.
RSS_FEED_URLS와 RSS_SOURCE_LABELS는 쉼표 구분, 순서가 1:1 대응해야 한다.


6. 데이터베이스 스키마
1인 전용이므로 users 테이블을 제거하고 watchlist·alerts에서 user_id 외래키를 삭제한다.
SQLite 문법 기준으로 작성한다.
sql-- watchlist
CREATE TABLE watchlist (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker     VARCHAR(16) NOT NULL,
    market     VARCHAR(16) NOT NULL,  -- sh | sz | hk
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (ticker)
);

-- alerts
CREATE TABLE alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker       VARCHAR(16) NOT NULL,
    condition    VARCHAR(8)  NOT NULL,  -- above | below
    price        REAL        NOT NULL,
    is_active    BOOLEAN DEFAULT 1,
    triggered_at DATETIME,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- index_cache
CREATE TABLE index_cache (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    market    VARCHAR(16) UNIQUE NOT NULL,
    data      TEXT        NOT NULL,  -- JSON 문자열
    cached_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

7. API 설계
시장
GET /api/market                      # 5개 시장 지수 목록
GET /api/market/{market_id}          # 단일 시장 상세
GET /api/market/{market_id}/top      # 시총 상위 ?limit=20

종목
GET /api/stock/search?q={keyword}
GET /api/stock/{ticker}
GET /api/stock/{ticker}/chart?period=1mo&interval=1d
GET /api/stock/{ticker}/news

뉴스 (RSSHub 경유 RSS 기반)
GET /api/news?market=all&limit=20&source=all
    source: all | 财联社전보 | 财联社인기 | 东方财富리서치 | 东方财富A株
            | 新浪财经 | 上交所공시 | 集思录채권 | SCMP | Reuters
    market: all | cn | hk | global

경제 캘린더
GET /api/calendar?start=YYYY-MM-DD&end=YYYY-MM-DD

관심종목
GET    /api/watchlist
POST   /api/watchlist         body: {"ticker":"600519","market":"sh"}
DELETE /api/watchlist/{ticker}

알림
GET    /api/alert
POST   /api/alert             body: {"ticker":"600519","condition":"above","price":1800}
DELETE /api/alert/{id}

어드민 (X-Admin-Token 헤더 필수)
GET    /api/admin/status
POST   /api/admin/refresh/index
POST   /api/admin/refresh/rss
GET    /api/admin/feeds
POST   /api/admin/feeds       body: {"url":"...","label":"...","market_tag":"cn"}
DELETE /api/admin/feeds       body: {"url":"..."}
GET    /api/admin/watchlist
GET    /api/admin/alerts

시스템
GET /health
# POST /webhook 없음 — Polling 방식이므로 불필요

8. 스케줄러
pythonJOBS = [
    # 장중 지수 캐시 갱신 (15분)
    {"id": "index_refresh", "trigger": "interval", "minutes": 15},
    # 알림 가격 체크 (15분)
    {"id": "alert_check",   "trigger": "interval", "minutes": 15},
    # RSS 피드 갱신 (30분) — RSSHub 캐시 만료(1800초)와 동기화
    {"id": "rss_refresh",   "trigger": "interval", "minutes": 30},
    # 장 마감 요약 발송 — A주 기준 15:30 KST
    {"id": "close_report",  "trigger": "cron", "hour": 15, "minute": 30},
    # 모닝 브리핑 — 09:00 KST
    {"id": "morning_brief", "trigger": "cron", "hour": 9,  "minute": 0},
]

9. RSS 피드 구성 (RSSHub 기반)
9.1 RSSHub Docker 설정
yaml# docker-compose.yml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      RSSHUB_BASE_URL: http://rsshub:1200
    depends_on:
      - rsshub

  rsshub:
    image: diygod/rsshub:latest
    restart: unless-stopped
    ports:
      - "127.0.0.1:1200:1200"   # 루프백만 노출 — 외부 차단
    environment:
      NODE_ENV: production
      CACHE_TYPE: memory
      CACHE_EXPIRE: 1800        # 30분 — rss_refresh 스케줄과 동기화

Docker 없이 로컬 개발 시: docker run -d --name rsshub -p 127.0.0.1:1200:1200 diygod/rsshub

9.2 피드 라우트 목록
레이블RSSHub 라우트언어커버리지财联社전보/cls/telegraph중국어A주·홍콩 실시간 전보财联社인기/cls/hot중국어인기 뉴스东方财富리서치/eastmoney/report/strategyreport중국어전략 리서치 보고서东方财富A株/eastmoney/search/A股중국어A주 관련 뉴스新浪财经/sina/news/stock중국어A주·홍콩 전반上交所공시/sse/disclosure중국어상장사 공시集思录채권/jisilu/explore/category-4__sort_type-hot__day-30중국어채권·전환사채SCMP/scmp/section/2영어홍콩·중국 영문Reuters/reuters/cn영어중국 거시·기업

피드 추가 예시 (어드민 또는 .env): /eastmoney/search/新能源 — 키워드 기반 커스텀 피드 자유롭게 확장 가능.

9.3 rss_client.py 구조
python# src/data/rss_client.py
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import feedparser
import httpx

from src.config import settings


@dataclass
class NewsItem:
    title: str
    link: str
    published: Optional[datetime]
    source: str        # 레이블 (e.g. "财联社전보")
    source_url: str    # RSSHub 라우트 URL
    market_tag: str    # "cn" | "hk" | "global"


def _infer_market(url: str) -> str:
    if any(k in url for k in ("scmp", "hkej")):
        return "hk"
    if "reuters" in url:
        return "global"
    return "cn"


_feed_registry: list[dict] = [
    {
        "url": url.strip(),
        "label": label.strip(),
        "market_tag": _infer_market(url.strip()),
    }
    for url, label in zip(
        settings.RSS_FEED_URLS.split(","),
        settings.RSS_SOURCE_LABELS.split(","),
    )
]


async def _fetch_feed(client: httpx.AsyncClient, feed: dict) -> list[NewsItem]:
    try:
        resp = await client.get(feed["url"], timeout=settings.RSS_FETCH_TIMEOUT)
        resp.raise_for_status()
    except Exception:
        return []  # 개별 피드 실패 → 전체 중단 없이 빈 리스트 반환

    items = []
    for entry in feedparser.parse(resp.text).entries[: settings.RSS_MAX_ITEMS_PER_FEED]:
        published = None
        if getattr(entry, "published_parsed", None):
            published = datetime(*entry.published_parsed[:6])
        items.append(NewsItem(
            title=entry.get("title", "").strip(),
            link=entry.get("link", ""),
            published=published,
            source=feed["label"],
            source_url=feed["url"],
            market_tag=feed["market_tag"],
        ))
    return items


async def fetch_all_news(
    source_filter: str = "all",
    market_filter: str = "all",
    limit: int = 50,
) -> list[NewsItem]:
    feeds = _feed_registry
    if source_filter != "all":
        feeds = [f for f in feeds if f["label"] == source_filter]
    if market_filter != "all":
        feeds = [f for f in feeds if f["market_tag"] == market_filter]

    async with httpx.AsyncClient() as client:
        batches = await asyncio.gather(*[_fetch_feed(client, f) for f in feeds])

    seen: set[str] = set()
    merged: list[NewsItem] = []
    for batch in batches:
        for item in batch:
            if item.link not in seen:
                seen.add(item.link)
                merged.append(item)

    merged.sort(key=lambda x: x.published or datetime.min, reverse=True)
    return merged[:limit]


# ── 런타임 피드 관리 (어드민 API 전용) ──────────────────

def add_feed(url: str, label: str, market_tag: str = "cn") -> None:
    if not any(f["url"] == url for f in _feed_registry):
        _feed_registry.append({"url": url, "label": label, "market_tag": market_tag})

def remove_feed(url: str) -> bool:
    global _feed_registry
    before = len(_feed_registry)
    _feed_registry = [f for f in _feed_registry if f["url"] != url]
    return len(_feed_registry) < before

def list_feeds() -> list[dict]:
    return list(_feed_registry)

10. 미니앱 화면
파일설명index.html홈 — 5개 시장 지수 카드market.html시장 상세·시총 상위stock.html종목 상세·차트news.html뉴스 피드 (RSS 출처 필터 포함 — 레이블 기반)calendar.html경제 캘린더watchlist.html관심종목settings.html설정 (RSS 피드 소스 ON/OFF 포함)admin.html어드민 관리 페이지 (토큰 인증, 피드 관리, 캐시 갱신)

11. 어드민 페이지
11.1 개요
브라우저에서 직접 접근하는 단독 관리 페이지. 텔레그램 WebApp과 독립적으로 동작하며,
ADMIN_TOKEN 헤더 인증으로 보호된다. 1인 전용이므로 정적 토큰 방식으로 충분하다.
접근 URL: http://<서버주소>:<PORT>/admin.html
11.2 API 엔드포인트
모든 요청에 X-Admin-Token: <ADMIN_TOKEN> 헤더가 필요하다.
메서드경로설명GET/api/admin/status버전·캐시 상태·활성 피드 수 조회POST/api/admin/refresh/index지수 캐시 즉시 갱신POST/api/admin/refresh/rssRSS 피드 즉시 갱신GET/api/admin/feeds현재 활성 RSS 피드 목록 (URL·레이블·market_tag)POST/api/admin/feedsRSS 피드 추가 (body: {"url":"...","label":"...","market_tag":"cn"})DELETE/api/admin/feedsRSS 피드 삭제 (body: {"url":"..."})GET/api/admin/watchlist관심종목 전체 조회GET/api/admin/alerts알림 전체 조회 (활성·발동 포함)
11.3 RSS 피드 런타임 관리
rss_client.py 내 모듈 수준 _feed_registry를 통해 런타임에 피드를 추가·삭제할 수 있다.
서버 재시작 시 settings.RSS_FEED_URLS / RSS_SOURCE_LABELS 값으로 초기화된다.
영구 반영이 필요하면 .env를 직접 수정한다.
11.4 환경변수
dotenvADMIN_TOKEN=change-me   # 반드시 변경
11.5 화면 구성
섹션기능시스템 상태버전, 활성 피드 수, RSSHub 연결 상태, 캐시 fresh/stale캐시 강제 갱신지수 캐시 / RSS 피드 즉시 갱신 버튼RSS 피드 관리RSSHub 라우트 목록, 레이블·market_tag 표시, 추가/삭제관심종목등록된 종목 목록 (read-only)가격 알림전체 알림 목록·상태 (read-only)

12. 개발 로드맵
Phase목표Phase 1기반 구축 — /health, /start, Polling 동작 확인, 미니앱 진입, RSSHub Docker 기동 확인Phase 2시장 데이터 — 5개 지수 조회·차트 렌더링 (akshare + yfinance)Phase 3종목 — 검색·상세·차트 (akshare + yfinance)Phase 4뉴스 피드 — RSSHub 라우트 연동·정규화·출처 필터 (rss_client)Phase 5관심종목·알림 — 등록·임계값 알림 발송Phase 6경제 캘린더·스케줄러 — 자동 브리핑 (akshare 경제지표)Phase 6.5어드민 페이지 — RSS 피드 관리, 캐시 제어, 모니터링Phase 7운영 환경 구성 — ngrok(개발) → 자체 서버 + 도메인(운영)