# 독립 모듈 기준 재분리 계획

## 목표

현재 `bot.py`는 여러 파일로 분리되었지만 파일 간 연관성이 아직 높다. 다음 리팩터링의 목표는 "파일 수를 늘리는 것"이 아니라 각 모듈이 독립적으로 이해, 테스트, 교체될 수 있도록 경계를 다시 잡는 것이다.

핵심 원칙:

- Telegram 핸들러는 Telegram API와 화면 출력만 담당한다.
- 뉴스 수집기는 외부 API 호출과 원천 데이터 정규화만 담당한다.
- 분석/추천 로직은 Telegram, AkShare, 파일 경로, 환경변수를 몰라야 한다.
- 저장소는 JSON 파일 입출력만 담당하고 업무 판단을 하지 않는다.
- 설정은 실행 조립 단계에서만 읽고, 하위 모듈에는 명시적 값으로 주입한다.

## 현재 구조 진단

현재 의존 순서는 대략 다음과 같다.

```text
config
  -> state, keyboards
  -> fetcher
  -> view_handlers
  -> bot
```

순환 import는 없지만 결합도는 여전히 높다.

### `fetcher.py`

현재 역할이 너무 많다.

- AkShare 원천 API 호출
- Xinhua RSS 수집
- 뉴스 중복 tracker 처리
- 번역 호출
- Telegram 메시지 HTML 생성
- Telegram 전송
- `/view run`용 전체 시장 뉴스 수집
- `stock_db` 기반 후보 universe 생성
- 스케줄러에서 호출되는 `fetch_all`

문제:

- 데이터 수집기인데 Telegram `Bot`을 알고 있다.
- 수집과 전송이 묶여 있어 테스트가 어렵다.
- view 후보 발굴 로직이 일반 뉴스 전송 로직과 같은 파일에 있다.
- `_fetch_*_raw` 같은 private 함수가 `bot.py`에서 직접 import된다.

### `view_handlers.py`

현재 역할이 넓다.

- Telegram 명령 핸들러
- pending TTL 관리
- LLM 결과 검증 정책
- 결과 메시지 HTML 포맷
- 워치리스트 적용/삭제 실행
- 뉴스 수집 호출
- `MarketViewAnalyzer`, `StockDatabase`, `WatchlistManager` 직접 조합

문제:

- 화면 계층과 유스케이스 계층이 섞여 있다.
- 검증 정책을 Telegram 없이 테스트하기 어렵다.
- 나중에 CLI나 웹 UI를 붙이면 재사용하기 어렵다.

### `bot.py`

현재 역할:

- 앱 부트스트랩
- 의존 객체 생성
- Telegram 명령 등록
- 기본 워치리스트 명령 처리
- reply button 처리
- callback 분기
- scheduler 등록

문제:

- `cmd_add`, `cmd_list`, `callback_handler`가 아직 남아 있어 부트스트랩과 UI 핸들러가 섞여 있다.
- `context.bot_data` 문자열 키에 의존하는 서비스 로케이터 패턴이 커지고 있다.

### `config.py`

현재 역할:

- `.env` 로드
- 경로 상수
- 기능별 설정
- HELP_TEXT
- 기본 워치리스트

문제:

- 단순 상수 모듈이라 모든 모듈이 직접 import하기 쉽다.
- 설정을 직접 import하면 테스트에서 값을 바꾸기 어렵다.
- HELP_TEXT는 Telegram UI 문구인데 config에 있다.

## 목표 아키텍처

권장 구조:

```text
app/
  main.py                    # 진입점. Telegram app 생성, 의존성 조립, scheduler 시작
  settings.py                # env -> Settings dataclass
  container.py               # 서비스 객체 생성

  domain/
    models.py                # NewsItem, StockRef, ViewAction, ViewAnalysisResult
    policies.py              # add/remove 검증, confidence/evidence 정책

  repositories/
    sent_news_store.py       # sent_ids.json
    watchlist_store.py       # watchlist.json
    market_view_store.py     # market_view.json
    stock_repository.py      # stock_db.json 조회 래퍼

  clients/
    akshare_client.py        # AkShare raw 호출
    xinhua_client.py         # RSS 호출
    ollama_client.py         # JSON chat 공통 클라이언트

  news/
    normalizer.py            # AkShare/RSS row -> NewsItem
    collector.py             # CLS/Futu/Xinhua/Stock 뉴스 수집
    delivery_service.py      # 중복 확인, 번역, Telegram 전송용 메시지 생성 전 단계

  view/
    candidate_service.py     # stock_db 전체와 뉴스 매칭으로 candidate_universe 생성
    analysis_service.py      # market_view + news + candidates -> LLM 분석
    action_service.py        # pending 생성, apply/cancel, watchlist 변경
    formatter.py             # view 결과 텍스트 생성

  tg/
    app_factory.py           # Application 생성 및 handler 등록
    keyboards.py
    text.py                  # HELP_TEXT 등 Telegram 문구
    handlers/
      common.py              # /start /help reply buttons
      watchlist.py           # /add /list /menu remove callback
      view.py                # /view show/set/run/clear, view callbacks
```

이 구조에서 의존 방향은 아래처럼 고정한다.

```text
settings
domain
repositories -> domain
clients -> domain
news -> clients, repositories, domain
view -> news, repositories, clients, domain
tg -> view, news, repositories, domain
main/container -> everything
```

금지할 의존:

- `domain`에서 Telegram, AkShare, requests, config import 금지
- `repositories`에서 Telegram import 금지
- `clients`에서 Telegram import 금지
- `news.collector`에서 Telegram 전송 금지
- `view.analysis_service`에서 Telegram 객체 접근 금지
- 하위 모듈에서 `os.environ` 직접 접근 금지

## 핵심 데이터 모델

먼저 `domain/models.py`를 만든다.

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NewsItem:
    id: str
    source: str
    title: str
    content: str
    published_at: str
    url: str = ""
    ticker: str = ""
    name: str = ""
    matched_candidates: list["StockRef"] = field(default_factory=list)


@dataclass(frozen=True)
class StockRef:
    code: str
    name: str
    market: str = ""
    in_watchlist: bool = False


@dataclass(frozen=True)
class ViewAction:
    code: str
    name: str
    action: str
    confidence: float
    reason: str
    evidence: list[dict]


@dataclass(frozen=True)
class ViewAnalysisResult:
    generated_at: str
    summary: str
    actions: list[ViewAction]
    risks: list[str]
```

효과:

- dict key 오타 감소
- handler와 서비스 사이 계약 명확화
- 테스트 fixture 작성이 쉬워짐

## 재분리 기준

### 1. External Client

외부 호출만 담당한다.

예:

- `AkshareClient.fetch_cls_raw()`
- `AkshareClient.fetch_futu_raw()`
- `AkshareClient.fetch_stock_news_raw(code)`
- `AkshareClient.resolve_stock_name(code)`
- `XinhuaClient.fetch_entries()`
- `OllamaJsonClient.chat_json(prompt, payload, options)`

이 계층은 pandas dataframe, feedparser entry, HTTP 응답처럼 원천 형식을 반환해도 된다. 단, Telegram은 몰라야 한다.

### 2. Normalizer

원천 데이터를 내부 모델로 변환한다.

예:

- `normalize_cls_rows(df) -> list[NewsItem]`
- `normalize_futu_rows(df) -> list[NewsItem]`
- `normalize_stock_news_rows(code, name, df) -> list[NewsItem]`
- `normalize_xinhua_entries(entries) -> list[NewsItem]`

이 계층은 AkShare 컬럼명 깨짐 문제를 캡슐화한다. 현재 여러 곳에 있는 `_row_value`와 fallback index 로직은 여기로 모은다.

### 3. Use Case Service

업무 흐름을 담당한다.

예:

- `NewsDeliveryService.collect_translate_and_mark_sent()`
- `MarketViewUseCase.run(market_view) -> ViewRunResult`
- `WatchlistUseCase.add_by_code(code)`
- `ViewActionService.apply(uid)`

이 계층은 Telegram 메시지를 보내지 않는다. 결과 객체를 반환한다.

### 4. Telegram Adapter

Telegram 입출력만 담당한다.

예:

- command args 파싱
- reply/edit_text 호출
- InlineKeyboard 생성
- use case 결과를 사용자 메시지로 렌더링

Telegram handler는 `context.bot_data["..."]`에서 여러 서비스를 직접 꺼내 조합하지 말고, 하나의 `AppServices` 객체를 꺼내 쓰게 한다.

```python
services = context.bot_data["services"]
result = await services.market_view.run_saved_view()
```

## AppServices 도입

`container.py`에 조립 전용 객체를 둔다.

```python
from dataclasses import dataclass


@dataclass
class AppServices:
    sent_news: SentNewsRepository
    watchlist: WatchlistRepository
    market_view_store: MarketViewRepository
    stock_repo: StockRepository
    translator: TranslationService
    market_view: MarketViewUseCase
    news_delivery: NewsDeliveryService
```

장점:

- `context.bot_data` 문자열 키 난립 감소
- 테스트에서 fake service 주입 쉬움
- handler 함수의 의존성이 명확해짐

## 단계별 계획

### 1단계: 모델과 설정 정리

작업:

- `app/settings.py` 생성
- `Settings` dataclass로 env 값을 묶음
- `app/domain/models.py` 생성
- `NewsItem`, `StockRef`, `ViewAction`, `ViewAnalysisResult` 정의
- 기존 dict 기반 반환은 유지하되, 신규 함수부터 모델 사용

완료 기준:

- `config.py` 직접 import가 새 코드에서 늘어나지 않는다.
- 최소한 view/news 후보 생성 경로는 `NewsItem`, `StockRef`를 사용한다.

### 2단계: 외부 클라이언트 분리

작업:

- `app/clients/akshare_client.py`
- `app/clients/xinhua_client.py`
- `app/clients/ollama_client.py`
- `fetcher.py`, `stock_db.py`, `translator.py`, `market_view.py`의 HTTP/Ollama/AkShare 호출을 점진적으로 이동

완료 기준:

- AkShare 호출 함수가 `fetcher.py`에 남지 않는다.
- Ollama POST 로직이 `translator.py`와 `market_view.py`에 중복되지 않는다.

### 3단계: 뉴스 수집과 전송 분리

작업:

- `app/news/normalizer.py`
- `app/news/collector.py`
- `app/news/message_formatter.py`
- `app/news/delivery_service.py`

현재 `fetcher.py`의 역할 분해:

| 현재 함수 | 이동 위치 |
|---|---|
| `_fetch_cls_raw`, `_fetch_futu_raw`, `_fetch_stock_news_raw` | `clients/akshare_client.py` |
| `_fetch_xinhua_entries` | `clients/xinhua_client.py` |
| `_row_value` | `news/normalizer.py` |
| `collect_global_market_news_items` | `news/collector.py` |
| `collect_watchlist_news_items` | `news/collector.py` |
| `_build_news_message` | `news/message_formatter.py` |
| `fetch_cls`, `fetch_futu`, `fetch_stock_news`, `fetch_xinhua` | `news/delivery_service.py` |
| `fetch_all` | `news/scheduler_jobs.py` 또는 `delivery_service.py` |

완료 기준:

- 뉴스 수집 함수는 `Bot`을 받지 않는다.
- Telegram 전송 함수는 수집기 raw dataframe을 직접 다루지 않는다.

### 4단계: Market View 유스케이스 분리

작업:

- `app/view/candidate_service.py`
- `app/view/analysis_service.py`
- `app/view/action_policy.py`
- `app/view/pending_store.py`
- `app/view/action_service.py`
- `app/view/formatter.py`

현재 `view_handlers.py`의 역할 분해:

| 현재 함수 | 이동 위치 |
|---|---|
| `_normalize_code` | `domain/policies.py` 또는 `stock_repository.py` |
| `_pending_expired`, `_prune_expired_view_pending` | `view/pending_store.py` |
| `_validate_view_actions` | `view/action_policy.py` |
| `_format_view_result_message` | `view/formatter.py` |
| `_handle_view_run`의 분석 흐름 | `view/analysis_service.py` |
| `handle_view_apply`, `handle_view_cancel`의 업무 처리 | `view/action_service.py` |
| `cmd_view`, `_handle_view_show`, `_handle_view_set`, `_handle_view_clear` | `telegram/handlers/view.py` |

완료 기준:

- `view_handlers.py`는 Telegram handler만 남거나 `telegram/handlers/view.py`로 대체된다.
- action 검증 정책은 Telegram 없이 단위 테스트 가능하다.

### 5단계: Watchlist 명령 분리

작업:

- `app/watchlist/service.py`
- `app/tg/handlers/watchlist.py`

현재 `bot.py`의 다음 함수 이동:

- `cmd_menu`
- `cmd_add`
- `cmd_list`
- remove callback 처리

완료 기준:

- `bot.py` 또는 `main.py`에는 handler 구현이 남지 않는다.
- handler 등록만 담당한다.

### 6단계: 부트스트랩 정리

작업:

- `app/main.py`
- `app/container.py`
- `app/tg/app_factory.py`
- scheduler job 등록 함수 분리

최종 `main.py` 예:

```python
def main() -> None:
    settings = Settings.from_env()
    services = build_services(settings)
    app = build_telegram_app(settings, services)
    start_scheduler(app, services, settings)
    app.run_polling()
```

완료 기준:

- `main.py`는 50~80줄 이하
- 직접 업무 로직 없음
- 모든 서비스 생성은 `container.py`에서 수행

## 권장 최종 의존 방향

```text
main
  -> settings
  -> container
  -> tg.app_factory

tg.handlers
  -> view services
  -> watchlist services
  -> telegram formatters/keyboards

view services
  -> news collector
  -> repositories
  -> ollama client
  -> domain policies

news services
  -> clients
  -> normalizers
  -> translator
  -> repositories

repositories
  -> filesystem/json
  -> domain models

clients
  -> external APIs only

domain
  -> stdlib only
```

## 테스트 계획

리팩터링과 동시에 다음 단위 테스트를 추가한다.

### Domain/Policy

- 코드 정규화
- add/remove 후보 검증
- confidence/evidence 기준
- 현재 watchlist에 없는 remove 제거
- candidate universe 밖 add 제거

### News Normalizer

- CLS row -> `NewsItem`
- Futu row -> `NewsItem`
- Stock news row -> `NewsItem`
- 깨진 컬럼명 fallback
- 날짜 cutoff

### View Service

- market view 저장 없음
- 뉴스 없음
- 후보 없음
- add 후보 있음
- remove 후보 있음
- pending 만료
- apply 중 일부 실패

### Telegram Handler

Telegram API 직접 호출 대신 fake service를 사용해 응답 텍스트만 검증한다.

## 마이그레이션 순서

권장 순서:

1. `domain/models.py` 추가
2. `settings.py`와 `container.py` 추가
3. `clients/akshare_client.py` 추가
4. `news/normalizer.py` 추가
5. `news/collector.py` 추가
6. `/view run`이 새 `news.collector`를 사용하게 변경
7. `view/action_policy.py` 분리
8. `view/analysis_service.py` 분리
9. `telegram/handlers/view.py`로 handler 이동
10. watchlist handler 이동
11. 기존 `fetcher.py`, `view_handlers.py` 축소 또는 제거
12. `bot.py`를 `main.py`/`app_factory.py`로 축소

각 단계마다 다음 명령으로 확인한다.

```powershell
python -m py_compile app\bot.py app\*.py
```

테스트가 추가된 뒤에는:

```powershell
pytest
```

## 리스크와 주의점

- AkShare 컬럼명이 환경/버전에 따라 깨져 보이는 문제가 있으므로 normalizer에 fallback을 집중시킨다.
- Telegram 메시지 텍스트가 mojibake 상태인 부분은 리팩터링과 별도 작업으로 두되, 새 파일에는 UTF-8 한국어 문구만 사용한다.
- 한 번에 `fetcher.py`를 다 쪼개면 회귀 위험이 크므로 `collect_global_market_news_items`부터 옮긴다.
- `context.bot_data` 키 기반 접근을 즉시 제거하지 말고 `services` 키를 먼저 추가한 뒤 점진적으로 전환한다.
- Xinhua, CLS, Futu, stock news는 수집 실패가 전체 루프를 멈추지 않도록 소스별 실패 격리를 유지한다.

## 완료 기준

최종 완료 기준:

- `bot.py` 또는 `main.py`는 앱 조립과 실행만 담당한다.
- Telegram handler는 business rule을 직접 구현하지 않는다.
- `fetcher.py`가 제거되거나 `news/delivery_service.py` 수준의 얇은 호환 레이어로만 남는다.
- `view_handlers.py`가 제거되거나 Telegram adapter로만 남는다.
- `MarketViewAnalyzer`는 Telegram, stock_db 파일 경로, AkShare를 모른다.
- 뉴스 수집은 Telegram 없이 단위 실행 가능하다.
- view action 검증은 LLM 없이 단위 테스트 가능하다.
- 새로운 기능 추가 시 `bot.py`를 거의 수정하지 않는다.
