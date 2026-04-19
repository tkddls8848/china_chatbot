# 🇨🇳 중국·홍콩 증시 텔레그램 미니앱 봇 — 개발 계획서

**프로젝트명:** TBD  
**버전:** 0.5.1  
**작성일:** 2026-04-19  
**목표 시장:** 상해 메인보드, 선전 메인보드, 과창판(STAR), 창업판(ChiNext), 홍콩(HKEX)  
**운영 형태:** 1인 전용

---

## 1. 프로젝트 개요

### 1.1 서비스 개요

중국 A주(상해·선전·과창판·창업판) 및 홍콩 H주·항셍 시장 정보를 제공하는 텔레그램 미니앱(WebApp) 기반 증시 정보 봇.

시장 지수, 종목 검색, 뉴스, 경제 캘린더, 관심종목 알림을 제공하는 **순수 정보 채널**. LLM 없음.

### 1.2 확정 사항

| 항목 | 결정 |
|------|------|
| 구현 형태 | 텔레그램 미니앱 (WebApp) |
| 봇 수신 방식 | Polling (Webhook 미사용) |
| 백엔드 언어 | Python 3.12.x |
| 웹 프레임워크 | FastAPI |
| 목표 시장 | 상해 / 선전 / 과창판 / 창업판 / 홍콩 (5개) |
| 시장 데이터 | akshare (중국 A주 — 지수·종목·시총·경제지표), yfinance (홍콩) |
| 뉴스 데이터 | **RSS 피드 (feedparser)** |
| LLM | 없음 |
| 사용자 범위 | 1인 전용 |
| 데이터베이스 | SQLite (파일 기반) |
| 배포 플랫폼 | 로컬 / 자체 서버 |

### 1.3 핵심 기능

| 기능 | 설명 |
|------|------|
| 시장 지수 조회 | 5개 시장 실시간(15분 지연) 지수 현황 |
| 종목 검색 및 상세 | 티커/종목명 검색, 가격·차트 |
| 시가총액 상위 | 시장별 시총 상위 종목 리스트 |
| 경제 캘린더 | PBOC 정책, PMI, CPI 등 주요 경제지표 일정 |
| 뉴스 피드 | RSS 피드 취합 기반 중국·홍콩 시장 뉴스 |
| 관심종목 알림 | 관심종목 등록 및 임계값 가격 알림 |

### 1.4 v0.4.0 → v0.5.0 변경 내역

| 항목 | 이전 (v0.4.0) | 변경 (v0.5.0) |
|------|--------------|--------------|
| 봇 수신 방식 | Webhook | Polling |
| 데이터베이스 | PostgreSQL (Railway) | SQLite (로컬 파일) |
| 배포 플랫폼 | Railway | 로컬 / 자체 서버 |
| users 테이블 | 있음 | 제거 (1인 전용) |
| webhook.py 라우트 | 있음 | 제거 |
| railway.json | 있음 | 제거 |
| TELEGRAM_WEBHOOK_SECRET | 있음 | 제거 |

> **Polling 채택 이유**  
> 1인 전용 운영 환경에서는 사용자 메시지 수신량이 적으므로 Polling으로 충분하다.  
> Webhook은 공개 HTTPS 엔드포인트가 필수인 반면, Polling은 서버가 텔레그램 API에
> 주기적으로 요청을 보내는 방식이라 로컬 환경에서도 즉시 동작한다.  
> 미니앱(WebApp) URL은 HTTPS가 여전히 필요하므로 개발 시 ngrok, 운영 시 자체 도메인을 사용한다.

### 1.5 v0.5.0 → v0.5.1 변경 내역

| 항목 | 이전 (v0.5.0) | 변경 (v0.5.1) |
|------|--------------|--------------|
| 뉴스 데이터 소스 | akshare 뉴스 함수 | RSS 피드 (feedparser) |
| akshare 사용 범위 | A주 전반 + 뉴스 | 지수·종목·시총·경제지표만 |
| 데이터 클라이언트 | akshare_client.py, yfinance_client.py | + rss_client.py 추가 |
| 의존 패키지 | — | feedparser≥6.0 추가 |
| RSS 피드 섹션 | 없음 | 섹션 9 신규 추가 |
| /api/news 파라미터 | market, limit | source 파라미터 추가 |
| 스케줄러 잡 | index_refresh, alert_check, close_report, morning_brief | rss_refresh 추가 |
| 로드맵 | Phase 6 | Phase 7로 재편 (뉴스 단계 분리) |

---

## 2. 시스템 아키텍처
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
│  │  RssClient (뉴스 RSS 취합)                         │ │
│  └───────────────────────────────────────┬───────────┘ │
│                                          │             │
│  ┌───────────────────────────────────────▼───────────┐ │
│  │                SQLite (로컬 파일)                  │ │
│  │  watchlist │ alerts │ index_cache                  │ │
│  └────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────┘

---

## 3. 기술 스택

### 3.1 백엔드

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `python` | 3.12.x | 런타임 |
| `python-telegram-bot` | 21.x | 텔레그램 봇 API (Polling) |
| `fastapi` | 0.111.x | REST API 서버 (미니앱 전용) |
| `uvicorn[standard]` | 0.29.x | ASGI 서버 |
| `akshare` | 최신 | 중국 A주 — 지수·종목·시총·경제지표 |
| `yfinance` | 0.2.x | 홍콩·글로벌 지수 |
| `feedparser` | ≥6.0 | RSS 피드 파싱 (뉴스 취합) |
| `httpx` | 0.27.x | 비동기 HTTP 클라이언트 (RSS fetch 포함) |
| `apscheduler` | 3.10.x | 스케줄 작업 |
| `sqlalchemy` | 2.0.x | ORM |
| `alembic` | 1.13.x | DB 마이그레이션 |
| `pydantic-settings` | 2.x | 환경변수 관리 |

### 3.2 프론트엔드 (미니앱)

| 기술 | 용도 |
|------|------|
| HTML5 / CSS3 | 마크업·스타일 |
| Vanilla JS (ES6+) | 인터랙션 |
| Chart.js 4.x | 주가 차트 |
| Telegram WebApp JS SDK | 텔레그램 브릿지·테마 |

### 3.3 인프라

| 항목 | 개발 | 운영 |
|------|------|------|
| 실행 환경 | 로컬 PC | 자체 서버 |
| DB | SQLite 파일 | SQLite 파일 |
| HTTPS | ngrok | 자체 도메인 + Let's Encrypt |

---

## 4. 프로젝트 구조
{project-name}/
├── .env
├── .env.example
├── .gitignore
├── .python-version
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
│   ├── init.py
│   ├── config.py
│   ├── exceptions.py
│   │
│   ├── bot/
│   │   ├── init.py
│   │   ├── main.py          # Polling 실행 진입점
│   │   ├── handlers/
│   │   │   ├── init.py
│   │   │   ├── start.py
│   │   │   ├── market.py
│   │   │   ├── news.py
│   │   │   └── alert.py
│   │   └── keyboards.py
│   │
│   ├── api/
│   │   ├── init.py
│   │   ├── main.py
│   │   ├── deps.py
│   │   └── routes/
│   │       ├── init.py
│   │       ├── market.py      # GET /api/market
│   │       ├── stock.py       # GET /api/stock
│   │       ├── news.py        # GET /api/news
│   │       ├── calendar.py    # GET /api/calendar
│   │       ├── watchlist.py   # CRUD /api/watchlist
│   │       └── alert.py       # CRUD /api/alert
│   │       # webhook.py 없음 — Polling 방식이므로 불필요
│   │
│   ├── services/
│   │   ├── init.py
│   │   ├── market_service.py
│   │   ├── stock_service.py
│   │   ├── news_service.py    # rss_client 의존으로 변경
│   │   ├── calendar_service.py
│   │   └── alert_service.py
│   │
│   ├── data/
│   │   ├── init.py
│   │   ├── akshare_client.py  # 지수·종목·시총·경제지표 전용
│   │   ├── yfinance_client.py
│   │   └── rss_client.py      # RSS 피드 취합 (신규)
│   │
│   ├── db/
│   │   ├── init.py
│   │   ├── session.py
│   │   └── models/
│   │       ├── init.py
│   │       ├── watchlist.py   # user_id 외래키 없음 (1인 전용)
│   │       └── alert.py
│   │
│   └── scheduler/
│       ├── init.py
│       └── jobs.py
│
└── frontend/
├── index.html             # 홈 — 5개 시장 지수 카드
├── market.html            # 시장 상세·시총 상위
├── stock.html             # 종목 상세·차트
├── news.html              # 뉴스 피드 (RSS 출처 필터 포함)
├── calendar.html          # 경제 캘린더
├── watchlist.html         # 관심종목
├── settings.html          # 설정 (RSS 피드 소스 ON/OFF 포함)
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

---

## 5. 환경변수

```dotenv
# .env.example

# ── 텔레그램 ──────────────────────────────────────────
TELEGRAM_BOT_TOKEN=
WEBAPP_URL=                  # ngrok URL (개발) 또는 자체 도메인 (운영)
# TELEGRAM_WEBHOOK_SECRET 없음 — Polling 방식이므로 불필요

# ── 데이터베이스 ───────────────────────────────────────
DATABASE_URL=sqlite:///./data/app.db

# ── 앱 설정 ───────────────────────────────────────────
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=INFO

# ── 캐시 ──────────────────────────────────────────────
CACHE_TTL_SECONDS=900

# ── RSS 피드 ──────────────────────────────────────────
RSS_MAX_ITEMS_PER_FEED=20    # 피드당 최대 수집 건수
RSS_FETCH_TIMEOUT=10         # 피드 요청 타임아웃 (초)
```

---

## 6. 데이터베이스 스키마

1인 전용이므로 `users` 테이블을 제거하고 `watchlist`·`alerts`에서 `user_id` 외래키를 삭제한다.
SQLite 문법 기준으로 작성한다 (`SERIAL` → `INTEGER PRIMARY KEY AUTOINCREMENT`, `JSONB` → `TEXT`).

```sql
-- watchlist
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
```

---

## 7. API 설계
시장
GET /api/market                      # 5개 시장 지수 목록
GET /api/market/{market_id}          # 단일 시장 상세
GET /api/market/{market_id}/top      # 시총 상위 ?limit=20
종목
GET /api/stock/search?q={keyword}
GET /api/stock/{ticker}
GET /api/stock/{ticker}/chart?period=1mo&interval=1d
GET /api/stock/{ticker}/news
뉴스 (RSS 기반)
GET /api/news?market=all&limit=20&source=all
source: all | sina | scmp | reuters | hkej | ...
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
시스템
GET /health
POST /webhook 없음 — Polling 방식이므로 불필요

---

## 8. 스케줄러

```python
JOBS = [
    # 장중 지수 캐시 갱신 (15분)
    {"id": "index_refresh", "trigger": "interval", "minutes": 15},
    # 알림 가격 체크 (15분)
    {"id": "alert_check",   "trigger": "interval", "minutes": 15},
    # RSS 피드 갱신 (30분)
    {"id": "rss_refresh",   "trigger": "interval", "minutes": 30},
    # 장 마감 요약 발송 — A주 기준 15:30 KST
    {"id": "close_report",  "trigger": "cron", "hour": 15, "minute": 30},
    # 모닝 브리핑 — 09:00 KST
    {"id": "morning_brief", "trigger": "cron", "hour": 9,  "minute": 0},
]
```

---

## 9. RSS 피드 목록

| 출처 | 피드 URL (예시) | 언어 | 커버리지 |
|------|----------------|------|---------|
| 新浪财经 | `https://finance.sina.com.cn/rss/stock.xml` | 중국어 | A주·홍콩 전반 |
| 东方财富 | RSS 또는 스크래핑 확인 필요 | 중국어 | A주 중심 |
| 南华早报 (SCMP Markets) | `https://www.scmp.com/rss/5/feed` | 영어 | 홍콩·중국 영문 |
| Reuters China Business | `https://feeds.reuters.com/reuters/CNbusinessNews` | 영어 | 중국 거시·기업 |
| 香港经济日报 | 별도 확인 필요 | 중국어 | 홍콩 로컬 |

> 실제 RSS URL은 서비스 정책·도메인 변경에 따라 달라질 수 있으므로 착수 전 유효성 확인 필요.  
> URL 목록은 `config.py` 또는 `.env`의 `RSS_FEED_URLS` 리스트로 관리한다.

### rss_client.py 역할

복수 RSS URL을 설정에서 읽어 `httpx`로 비동기 fetch → `feedparser`로 파싱 →
표준 뉴스 스키마(`title`, `link`, `published`, `source`, `market_tag`)로 정규화 →
URL 기준 중복 제거 → `news_service.py`에 결과 반환.

---

## 10. 미니앱 화면

| 파일 | 설명 |
|------|------|
| `index.html` | 홈 — 5개 시장 지수 카드 |
| `market.html` | 시장 상세·시총 상위 |
| `stock.html` | 종목 상세·차트 |
| `news.html` | 뉴스 피드 (RSS 출처 필터 포함) |
| `calendar.html` | 경제 캘린더 |
| `watchlist.html` | 관심종목 |
| `settings.html` | 설정 (RSS 피드 소스 ON/OFF 포함) |

---

## 11. 개발 로드맵

| Phase | 목표 |
|-------|------|
| Phase 1 | 기반 구축 — /health, /start, Polling 동작 확인, 미니앱 진입 |
| Phase 2 | 시장 데이터 — 5개 지수 조회·차트 렌더링 (akshare + yfinance) |
| Phase 3 | 종목 — 검색·상세·차트 (akshare + yfinance) |
| Phase 4 | 뉴스 피드 — RSS 취합·정규화·출처 필터 (rss_client) |
| Phase 5 | 관심종목·알림 — 등록·임계값 알림 발송 |
| Phase 6 | 경제 캘린더·스케줄러 — 자동 브리핑 (akshare 경제지표) |
| Phase 7 | 운영 환경 구성 — ngrok(개발) → 자체 서버 + 도메인(운영) |