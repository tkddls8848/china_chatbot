# 6파일 단순화 계획

## 목표

현재 20개 파일(패키지 구조)을 **app/ 하위 6개 단일 파일**로 병합.  
서브패키지 없음. `from xxx import yyy` 형태의 단순한 flat 구조.

---

## 목표 구조

```
app/
  settings.py    # Settings dataclass — 변경 없음
  store.py       # 데이터·상태: 모델, 저장소, StockDatabase
  llm.py         # LLM 추론: OllamaJsonClient, TranslationService, MarketViewAnalyzer
  news.py        # 뉴스: 소스 클라이언트, 수집, Telegram 전송
  bot.py         # 봇: 시장뷰 로직 + Telegram 핸들러 + 앱 팩토리
  main.py        # 진입점: AppServices 조립 + 스케줄러 + main()
```

---

## 파일별 담당 내용

### `settings.py` (변경 없음)
현재 파일 그대로 유지.

---

### `store.py` (≈ 350줄)

| 출처 | 클래스/함수 |
|---|---|
| `data/models.py` | `normalize_stock_code`, `is_matchable_stock_name`, `NewsItem`, `StockRef`, `ViewAction`, `ViewAnalysisResult` |
| `data/store.py` | `SentNewsTracker`, `WatchlistManager`, `MarketViewManager` |
| `data/stock_db.py` | `StockDatabase` |
| `view/market_view.py` 상단 | `ViewPendingStore` |

import: stdlib + settings (ViewPendingStore만)

---

### `llm.py` (≈ 400줄)

| 출처 | 클래스 |
|---|---|
| `llm/client.py` | `OllamaJsonClient` |
| `llm/translator.py` | `TranslationError`, `TranslationService` |
| `llm/analyzer.py` | `MarketViewError`, `MarketViewAnalyzer` |

import: stdlib + requests

---

### `news.py` (≈ 550줄)

| 출처 | 클래스/함수 |
|---|---|
| `news/sources.py` | `AkshareClient`, `XinhuaClient` |
| `news/collector.py` 상단 | 모든 normalizer 함수 (`_row_value`, `_within_news_cutoff`, `_make_news_item`, `normalize_cls_rows`, …) |
| `news/collector.py` | `NewsCollector` |
| `news/sender.py` | `_build_news_message`, `_translate_article`, `fetch_cls`, `fetch_futu`, `fetch_stock_news`, `fetch_xinhua`, `_refresh_stock_db`, `fetch_all` |

import: stdlib + akshare + feedparser + pandas + tenacity + telegram + `store.py` + `llm.py` + `settings.py`

---

### `bot.py` (≈ 550줄)

| 출처 | 클래스/함수 |
|---|---|
| `view/market_view.py` | `CandidateService`, `ViewActionPolicy`, `MarketViewFormatter`, `ViewActionService`, `MarketViewRunResult`, `MarketViewAnalysisService` |
| `handlers/core.py` | 키보드 상수·빌더, `HELP_TEXT`, `get_services`, `cmd_start`, `cmd_help`, `handle_reply_button`, `callback_handler`, `build_telegram_app` |
| `handlers/watchlist.py` | `cmd_menu`, `cmd_add`, `cmd_list`, `handle_remove_callback` |
| `handlers/view.py` | `cmd_view`, `handle_view_show`, `handle_view_set`, `handle_view_clear`, `run_saved_view`, `handle_view_run`, `handle_view_apply`, `handle_view_cancel` |

import: stdlib + telegram + `store.py` + `llm.py` + `news.py` + `settings.py`

---

### `main.py` (≈ 120줄)

| 출처 | 내용 |
|---|---|
| 현재 `main.py` | `AppServices` dataclass, `build_services()` |
| 현재 `main.py` | `configure_logging()`, `main()`, 스케줄러 등록 |

import: stdlib + apscheduler + 위 5개 파일 전부

---

## 의존 그래프

```
main
  └─ settings, store, llm, news, bot

bot
  └─ settings, store, llm, news

news
  └─ settings, store, llm

llm
  └─ stdlib + requests

store
  └─ stdlib + settings (ViewPendingStore만)

settings
  └─ stdlib
```

순환 없음.

---

## 단계별 작업

### 1단계: `store.py` 생성

다음 내용을 순서대로 하나의 파일로 합침:

1. `data/models.py` 전체
2. `data/store.py` 전체 (SentNewsTracker, WatchlistManager, MarketViewManager)
3. `data/stock_db.py` 전체 (StockDatabase)
4. `view/market_view.py`의 `ViewPendingStore` 클래스

import 정리: `from settings import Settings` (ViewPendingStore에서만 필요)

---

### 2단계: `llm.py` 생성

다음 내용을 순서대로 하나의 파일로 합침:

1. `llm/client.py` 전체 (OllamaJsonClient)
2. `llm/translator.py` 전체
3. `llm/analyzer.py` 전체

`OllamaJsonClient`는 같은 파일 내에 있으므로 내부 import 제거.

---

### 3단계: `news.py` 생성

다음 내용을 순서대로 하나의 파일로 합침:

1. `news/sources.py` 전체 (AkshareClient, XinhuaClient)
2. `news/collector.py`의 normalizer 함수들
3. `news/collector.py`의 `NewsCollector` 클래스
4. `news/sender.py` 전체

import 수정:
```python
# 변경 후
from store import SentNewsTracker, WatchlistManager, StockDatabase, NewsItem
from llm import TranslationService
from settings import Settings
```

`AkshareClient`, `XinhuaClient`, `NewsCollector`는 같은 파일 내이므로 import 불필요.

---

### 4단계: `bot.py` 생성

다음 내용을 순서대로 하나의 파일로 합침:

1. `view/market_view.py`에서 `ViewPendingStore` **제외한** 나머지 전체
2. `handlers/core.py` 전체 (키보드, HELP_TEXT, core handlers, build_telegram_app)
3. `handlers/watchlist.py` 전체
4. `handlers/view.py` 전체

import 수정:
```python
# 변경 후
from store import (NewsItem, StockRef, normalize_stock_code, is_matchable_stock_name,
                   WatchlistManager, MarketViewManager, StockDatabase, ViewPendingStore)
from llm import MarketViewAnalyzer, TranslationService
from news import NewsCollector
from settings import Settings
```

지연 import (`from handlers.view import ...`) → 같은 파일 내이므로 제거.

---

### 5단계: `main.py` 갱신

import를 새 flat 구조에 맞게 수정:

```python
from store import (SentNewsTracker, WatchlistManager, MarketViewManager,
                   StockDatabase, ViewPendingStore)
from llm import TranslationService, MarketViewAnalyzer
from news import AkshareClient, XinhuaClient, NewsCollector, fetch_all, _refresh_stock_db
from bot import (build_telegram_app, CandidateService, ViewActionPolicy,
                 MarketViewFormatter, ViewActionService, MarketViewAnalysisService)
from settings import Settings
```

---

### 6단계: 구 패키지 디렉토리 삭제

```
app/data/       (디렉토리 전체)
app/llm/        (디렉토리 전체)
app/news/       (디렉토리 전체)
app/view/       (디렉토리 전체)
app/handlers/   (디렉토리 전체)
```

---

## 최종 파일 목록

```
app/
  settings.py   (~109줄)
  store.py      (~350줄)
  llm.py        (~400줄)
  news.py       (~550줄)
  bot.py        (~550줄)
  main.py       (~120줄)
```

기능 파일: **6개** — `__init__.py` 없음, 서브패키지 없음

---

## 작업 체크리스트

- [ ] **1단계**: `store.py` 생성 (models + store + stock_db + ViewPendingStore)
- [ ] **2단계**: `llm.py` 생성 (client + translator + analyzer)
- [ ] **3단계**: `news.py` 생성 (sources + collector + sender)
- [ ] **4단계**: `bot.py` 생성 (view 로직 + 핸들러 전체)
- [ ] **5단계**: `main.py` import 수정
- [ ] **6단계**: 구 패키지 디렉토리 삭제
- [ ] **최종 확인**: `python -m py_compile main.py` 통과
