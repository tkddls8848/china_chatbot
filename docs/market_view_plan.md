# `/view` 기반 시장 뷰 워치리스트 기능 구현 계획

## 목표

사용자가 작성한 "나만의 시장 뷰" 프롬프트를 기준으로 LLM이 최신 뉴스와 현재 워치리스트를 분석하고, 워치리스트 조정 제안과 관련 뉴스를 텔레그램으로 출력한다.

LLM은 워치리스트를 즉시 변경하지 않고, `/view run`을 통해 제안만 출력한다. 실제 추가/삭제는 사용자가 버튼으로 승인했을 때만 적용한다.

---

## 구현 상태 요약 (2026-05-02 기준)

| 단계 | 내용 | 상태 |
|---|---|---|
| 1단계 | 저장소와 명령 골격 | ✅ 완료 |
| 2단계 | LLM 분석 MVP | ✅ 완료 |
| 3단계 | 승인 기반 워치리스트 변경 | ✅ 완료 |
| 4단계 | 뉴스 수집 재사용성 개선 | ✅ 완료 (전체 시장 뉴스 수집 분리) |
| 5단계 | 자동 분석 스케줄러 | ⬜ 미구현 |
| — | 공통 LLM 클라이언트 리팩터링 | ⬜ 미구현 |

---

## 현재 구조

```
app/
├── bot.py               # /view 명령 처리, 후보 universe 빌드, pending 관리
├── market_view.py       # MarketViewManager, MarketViewAnalyzer
├── translator.py        # TranslationService (JSON 재시도·복구 로직 추가됨)
└── stock_db.py          # StockDatabase (get_candidate_universe 포함)

prompts/
└── market_view_ko.txt   # LLM 분석 시스템 프롬프트

data/
└── market_view.json     # 시장 뷰 텍스트 + 마지막 분석 결과 저장
```

---

## 사용자 명령 UX

### `/view` 또는 `/view show`

저장된 시장 뷰와 최근 분석 요약을 표시한다.

```
시장 뷰
AI 인프라, 중국 소비 회복, 전력설비를 선호. 부동산과 단기 과열 테마는 제외.

최근 분석
- 마지막 실행: 2026-05-02T11:35:00
- 요약: AI 인프라와 전력설비 관련 흐름은 긍정적...

명령
/view show
/view set 시장뷰내용
/view run
/view clear
```

### `/view set <내용>`

시장 뷰를 `data/market_view.json`에 저장한다.

### `/view run`

저장된 시장 뷰로 분석을 실행한다. 전체 시장 뉴스(CLS + Futu)를 수집하고 후보 universe를 빌드한 뒤 LLM에 전달한다.

### `/view <임시뷰 텍스트>`

저장하지 않고 즉석에서 분석만 실행한다. `data/market_view.json`에 저장되지 않는다.

### `/view clear`

저장된 시장 뷰와 마지막 분석 결과를 삭제한다. 워치리스트는 변경하지 않는다.

---

## 데이터 파일

### `data/market_view.json`

```json
{
  "view": "AI 인프라, 전력설비, 중국 소비 회복 수혜를 선호한다.",
  "updated_at": "2026-05-02T11:30:00",
  "last_result": {
    "generated_at": "2026-05-02T11:35:00",
    "summary": "오늘 뉴스는 전력설비와 AI 인프라 쪽에 우호적이다.",
    "actions": [],
    "risks": []
  }
}
```

---

## 구현된 파일 상세

### `app/market_view.py`

**`MarketViewManager`**
- `get_view()` / `set_view(text)` / `clear_view()`
- `get_last_result()` / `save_result(result)`
- `data/market_view.json` 읽기/쓰기

**`MarketViewAnalyzer`**
- `analyze(market_view, watchlist, news_items, candidate_universe)` → `dict`
- Ollama `/api/chat` POST, `format: "json"` 강제
- 생성자 파라미터: `base_url`, `model`, `enabled`, `timeout`, `num_predict`, `prompt_file`, `num_gpu`

### `app/bot.py` 추가 내용

**상수 (env 연동)**

| 상수 | env 변수 | 기본값 | 설명 |
|---|---|---|---|
| `VIEW_MAX_ADD` | `VIEW_MAX_ADD` | 5 | 최대 추가 제안 수 |
| `VIEW_MAX_REMOVE` | `VIEW_MAX_REMOVE` | 3 | 최대 삭제 제안 수 |
| `VIEW_PENDING_TTL_MINUTES` | `VIEW_PENDING_TTL_MINUTES` | 10 | pending 만료 시간(분) |
| `VIEW_NEWS_LIMIT_PER_STOCK` | `VIEW_NEWS_LIMIT_PER_STOCK` | 2 | 종목당 뉴스 수집 수 |
| `VIEW_MAX_NEWS_ITEMS` | `VIEW_MAX_NEWS_ITEMS` | 20 | LLM에 넘기는 최대 뉴스 수 |
| `VIEW_GLOBAL_NEWS_LIMIT` | `VIEW_GLOBAL_NEWS_LIMIT` | 20 | 전체 시장 뉴스 수집 수 |
| `VIEW_MAX_CANDIDATES` | `VIEW_MAX_CANDIDATES` | 60 | 후보 universe 최대 종목 수 |
| `MARKET_VIEW_NUM_PREDICT` | `MARKET_VIEW_NUM_PREDICT` | 1024 | LLM 최대 출력 토큰 |

**주요 함수**

| 함수 | 역할 |
|---|---|
| `collect_global_market_news_items()` | CLS + Futu 최신 뉴스를 구조화된 dict 리스트로 수집 |
| `build_view_candidate_universe()` | stock_db 전체를 뉴스 본문과 대조해 언급된 종목을 후보로 추출 |
| `_validate_view_actions()` | LLM 결과에서 add/remove 중 실제 적용 가능한 항목만 필터링 |
| `_format_view_result_message()` | 분석 결과를 텔레그램 HTML 메시지로 포맷팅 |
| `_prune_expired_view_pending()` | TTL 만료된 pending 항목 정리 |
| `build_view_result_keyboard()` | [적용] [취소] 인라인 버튼 생성 |
| `_handle_view_apply()` | 승인 시 wm.add/remove 실행, stock_db 검증 포함 |
| `_handle_view_cancel()` | pending 제거 |

**콜백 처리**
- `view_apply:{uid}` → `_handle_view_apply()`
- `view_cancel:{uid}` → `_handle_view_cancel()`

### `prompts/market_view_ko.txt`

LLM 입력 구조:
```json
{
  "market_view": "...",
  "current_watchlist": {"300750": "CATL"},
  "news_items": [...],
  "candidate_universe": [...]
}
```

LLM 출력 스키마:
```json
{
  "summary": "string",
  "actions": [
    {
      "ticker": "string",
      "name": "string",
      "action": "add | keep | remove | watch",
      "confidence": 0.0,
      "reason": "string",
      "evidence": [
        {
          "title": "string",
          "source": "string",
          "published_at": "string",
          "url": "string"
        }
      ]
    }
  ],
  "risks": ["string"]
}
```

### `app/translator.py` 변경 사항

- `num_gpu`, `num_predict` 파라미터 추가
- JSON 파싱 실패 시 1회 자동 재시도 (retry_prompt 포함)
- `_extract_json_object()`: `{...}` 블록 추출
- `_parse_known_translation_shape()`: regex 기반 폴백 파서
- `_clean_jsonish_string()`: 불완전 JSON 문자열 정규화

---

## 환경 변수 전체 목록 (`.env`)

```env
# Ollama 공통
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_NUM_GPU=0          # 0=CPU, -1=GPU전체, N=N레이어 GPU
TRANSLATE_MODEL=gemma4:e4b

# 번역
TRANSLATE_ENABLED=true
TRANSLATE_TIMEOUT=60
TRANSLATE_NUM_PREDICT=1024
TRANSLATE_PROMPT_DIR=prompts
TRANSLATE_FALLBACK_TO_ORIGINAL=false
TRANSLATE_CONCURRENCY=1

# 시장 뷰 분석
MARKET_VIEW_ENABLED=true
MARKET_VIEW_MODEL=gemma4:e4b      # 미설정 시 TRANSLATE_MODEL 사용
MARKET_VIEW_TIMEOUT=180
MARKET_VIEW_NUM_PREDICT=4096      # 출력이 길어 높게 설정 필요

# 시장 뷰 동작
VIEW_MAX_ADD=5
VIEW_MAX_REMOVE=3
VIEW_PENDING_TTL_MINUTES=10
VIEW_NEWS_LIMIT_PER_STOCK=2
VIEW_MAX_NEWS_ITEMS=20
VIEW_GLOBAL_NEWS_LIMIT=20
VIEW_MAX_CANDIDATES=60
```

---

## 안전장치 (구현됨)

- LLM 결과는 반드시 JSON으로 파싱한다. 실패 시 워치리스트 변경 없음.
- `add` 대상은 `stock_db`에 존재하는 코드만 허용한다.
- `add`는 이미 watchlist에 있는 종목을 포함하지 않는다.
- `remove`는 watchlist에 없는 종목을 포함하지 않는다.
- pending은 `VIEW_PENDING_TTL_MINUTES` 경과 후 만료된다.
- 사용자가 버튼을 누르지 않으면 워치리스트를 변경하지 않는다.
- `/view clear`는 시장 뷰만 삭제하고 워치리스트는 변경하지 않는다.

---

## 알려진 이슈 및 대응

| 이슈 | 원인 | 대응 |
|---|---|---|
| `Read timed out` | `MARKET_VIEW_TIMEOUT`이 너무 짧음 | `MARKET_VIEW_TIMEOUT=180` 이상 설정 |
| `Unterminated string` JSON 오류 | `MARKET_VIEW_NUM_PREDICT`가 너무 작아 출력 잘림 | `MARKET_VIEW_NUM_PREDICT=4096` 이상 설정 |
| FUTU 번역 JSON 오류 | `TRANSLATE_NUM_PREDICT=512`로 잘림 | `TRANSLATE_NUM_PREDICT=1024` 설정 |
| GPU 미사용 | Ollama가 이미 CPU로 모델 로드된 상태 | Ollama 서버 재시작 후 `ollama ps`로 확인 |

---

## 미구현 항목

### 5단계: 자동 분석 스케줄러

```env
VIEW_AUTO_ANALYZE=false
VIEW_ANALYZE_INTERVAL_MINUTES=60
```

`VIEW_AUTO_ANALYZE=true`일 때 스케줄러가 정기적으로 분석 결과만 전송한다. 자동 적용은 항상 비활성화.

### 공통 LLM 클라이언트 리팩터링

`TranslationService`와 `MarketViewAnalyzer`가 Ollama 호출 코드를 중복 보유 중. 추후 `app/llm_client.py`로 분리 가능.

---

## 비범위

- 자동 매매
- 사용자 승인 없는 워치리스트 자동 변경
- 포트폴리오 비중 산정
- 실시간 시세 기반 매수/매도 판단
- 외부 뉴스 API 추가 도입
- `VIEW_AUTO_APPLY` 옵션 (설계상 제외)
