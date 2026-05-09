# 시장 뷰 후보 확장 TODO

## 원본 메모

단순 기사 몇 개, 관심종목, 최신 뉴스에 종목명이 직접 언급된 후보를 다루고 있는데 신문기사에서 종목명을 지정하지 않는 한 아무 내용도 안 나올 거임. `futu_ko.txt`의 프롬프트 요소를 적극 활용할 필요 있음.

## 배경

현재 시장 뷰 후보 생성은 다음 범위에 지나치게 묶여 있다.

- 단순 기사 몇 개
- 현재 관심종목
- 최신 뉴스 본문에 종목명이 직접 언급된 후보

이 구조에서는 신문 기사나 시장 속보가 산업, 정책, 테마만 언급하고 종목명을 직접 쓰지 않는 경우 후보 종목이 거의 생성되지 않는다. 따라서 `prompts/futu_ko.txt`의 프롬프트에 직접 언급 종목용 `mentioned_stocks`와 테마 기반 후보용 `theme_candidates`를 도입해 두 목적을 분리해서 활용한다.

## 목표

Futu 전체 시장 뉴스에서 종목명이 직접 나오지 않아도, 기사 내용의 산업/정책/테마/공급망 단서를 기반으로 시장 뷰 분석용 후보군을 확장한다.

단, 기존 뉴스 전송의 정확도를 해치지 않기 위해 직접 언급 종목과 추론 후보는 명확히 분리한다.

## 설계 원칙

- `mentioned_stocks`는 직접 언급 종목을 뜻한다.
  - 본문에 명시적으로 직접 언급된 상장사 종목코드만 포함한다.
- `theme_candidates`는 테마 기반 후보를 뜻한다.
  - 기사 내용상 관련 가능한 산업, 테마, 공급망, 대표 기업 후보를 담는다.
- 텔레그램 뉴스 메시지의 `관련종목` 표시는 `mentioned_stocks`만 사용한다.
- `/view` 시장 뷰 후보군 확장에는 `theme_candidates`를 사용한다.
- LLM이 생성한 종목코드는 반드시 `StockDatabase`로 검증한다.
- 후보 추천은 `candidate_universe` 안에서만 허용한다.

## 적용 대상 파일

- `prompts/futu_ko.txt`
- `app/translator.py`
- `app/bot.py`
- 필요 시 테스트 파일

## 1단계: Futu 프롬프트 확장

`prompts/futu_ko.txt`의 출력 JSON에 `mentioned_stocks`와 `theme_candidates` 필드를 사용한다.

예상 출력 형식:

```json
{
  "title": "한국어 제목",
  "content": "한국어 본문",
  "mentioned_stocks": ["09988", "600519"],
  "theme_candidates": [
    {
      "keyword": "算力",
      "theme": "AI 인프라",
      "reason": "기사에서 AI 서버 및 연산 수요 증가가 언급됨",
      "codes": ["002371", "688041"]
    }
  ]
}
```

프롬프트 규칙:

- `mentioned_stocks`에는 직접 언급된 종목만 넣는다.
- `theme_candidates`에는 직접 언급되지 않았더라도 기사 내용과 연관된 산업/테마/공급망 키워드를 넣는다.
- `codes`는 확실하지 않으면 빈 배열로 둔다.
- `theme_candidates`는 투자 의견이 아니라 후보군 확장을 위한 단서임을 명시한다.

## 2단계: 번역 결과 파서 확장

`app/translator.py`에서 번역 결과를 기존 3튜플에서 확장 가능한 구조로 바꾼다.

권장 방식:

- `TranslationResult` dataclass 추가
- 필드:
  - `title: str`
  - `content: str`
  - `mentioned_stocks: list[str]`
  - `theme_candidates: list[dict[str, Any]]`

호환 전략:

- 기존 호출부가 많으므로 한 번에 대규모 변경하지 않는다.
- 먼저 `_parse_translation()`이 `mentioned_stocks`와 `theme_candidates`를 읽을 수 있게 만든다.
- 호출부 수정은 `fetch_futu()`와 `collect_global_market_news_items()` 중심으로 제한한다.
- `cls`, `stock` 소스는 `theme_candidates`가 없어도 빈 배열로 동작하게 한다.

## 3단계: Futu 시장 뉴스 수집에 theme_candidates 저장

`app/bot.py`의 `collect_global_market_news_items()`에서 Futu 뉴스 수집 시 번역 결과의 `theme_candidates`를 `news_items`에 포함한다.

예상 news item:

```json
{
  "id": "Futu:2026-05-09 10:15:...",
  "source": "Futu",
  "ticker": "",
  "name": "",
  "title": "번역 제목",
  "content": "번역 본문",
  "published_at": "2026-05-09 10:15",
  "url": "https://...",
  "theme_candidates": [
    {
      "keyword": "算力",
      "theme": "AI 인프라",
      "reason": "기사에서 AI 서버 및 연산 수요 증가가 언급됨",
      "codes": ["002371"]
    }
  ]
}
```

주의:

- 일반 뉴스 전송 흐름에서는 `theme_candidates`를 표시하지 않는다.
- `/view` 분석용 `news_items`에만 보존한다.

## 4단계: 후보군 생성 로직 확장

`build_view_candidate_universe()`에 `theme_candidates` 기반 후보 생성 경로를 추가한다.

현재 후보 경로:

1. 현재 워치리스트 항상 포함
2. 시장 뷰 키워드 기반 후보
3. 뉴스 본문 내 종목명 직접 매칭 후보

추가 후보 경로:

4. Futu `theme_candidates` 기반 후보

처리 방식:

- `theme_candidates.codes`가 있으면 `stock_db.is_valid_code()`로 검증 후 후보에 추가한다.
- `theme_candidates.keyword` 또는 `theme_candidates.theme`이 있으면 `_VIEW_KEYWORD_MAP`과 연결 가능한 중국어 패턴을 만든다.
- stock DB의 중국어 종목명에 해당 패턴이 포함되면 제한 개수 안에서 후보에 추가한다.
- 후보에는 `matched_news`, `relation_reason`, `relation_keyword`를 포함한다.

예상 candidate:

```json
{
  "code": "002371",
  "name": "北方华创",
  "market": "SZ",
  "in_watchlist": false,
  "matched_news": [
    {
      "title": "AI 서버 수요 증가 기사",
      "source": "Futu",
      "published_at": "2026-05-09 10:15",
      "url": "https://..."
    }
  ],
  "relation_keyword": "算力",
  "relation_reason": "AI 인프라 투자 확대와 관련"
}
```

## 5단계: 시장 뷰 프롬프트 보강

`prompts/market_view_ko.txt`에서 `candidate_universe` 설명을 수정한다.

변경 방향:

- 기존: 최신 뉴스에 종목명이 직접 언급된 후보와 현재 워치리스트
- 변경: 직접 언급 후보, 현재 워치리스트, Futu `theme_candidates` 기반 테마 후보

추가 규칙:

- 직접 언급 후보와 연관 후보를 구분해서 판단한다.
- `relation_reason`만 있고 근거 뉴스가 약하면 `add`보다 `watch`로 분류한다.
- 직접 언급이 아닌 후보는 confidence를 보수적으로 둔다.

## 6단계: 제한값 추가

환경 변수로 테마 후보 개수를 제한한다.

예:

```python
VIEW_THEME_CANDIDATES_LIMIT = int(os.environ.get("VIEW_THEME_CANDIDATES_LIMIT", "20"))
```

목적:

- LLM 추론 후보가 과도하게 늘어나는 것을 방지한다.
- `VIEW_MAX_CANDIDATES` 안에서 직접 언급 후보와 워치리스트가 밀려나지 않게 한다.

## 7단계: 검증 계획

단위 검증:

- `mentioned_stocks`만 있는 JSON이 정상 파싱되는지 확인한다.
- `theme_candidates`가 포함된 Futu JSON이 정상 파싱되는지 확인한다.
- `theme_candidates`가 없거나 잘못된 형식이면 빈 배열로 처리되는지 확인한다.
- `theme_candidates.codes`에 없는 종목코드는 후보에서 제외되는지 확인한다.

기능 검증:

- 종목명이 직접 없는 뉴스에 대해 `theme_candidates` 키워드가 생성되는지 확인한다.
- `build_view_candidate_universe()`가 `theme_candidates` 기반 후보를 생성하는지 확인한다.
- `/view` 결과에서 직접 근거가 약한 후보가 `add`가 아니라 `watch`로 분류되는지 확인한다.

회귀 검증:

- CLS 뉴스 전송이 기존처럼 동작하는지 확인한다.
- 관심종목 개별 뉴스 전송이 기존처럼 동작하는지 확인한다.
- 텔레그램 메시지의 `관련종목`에 추론 후보가 섞이지 않는지 확인한다.

## 권장 구현 순서

1. `futu_ko.txt`에 `mentioned_stocks`, `theme_candidates` 출력 규칙 추가
2. `translator.py` 파서에서 `mentioned_stocks`, `theme_candidates` 안전 파싱
3. Futu 시장 뉴스 수집에서 `theme_candidates` 보존
4. `build_view_candidate_universe()`에 `theme_candidates` 후보 경로 추가
5. `market_view_ko.txt` 후보 설명 보강
6. 단위 테스트 또는 최소 샘플 데이터 검증

## 리스크와 대응

- 리스크: LLM이 관련 없는 종목코드를 생성할 수 있다.
  - 대응: `stock_db.is_valid_code()` 검증 및 confidence 보수화
- 리스크: 후보가 너무 많아져 시장 뷰 분석 품질이 떨어질 수 있다.
  - 대응: `VIEW_THEME_CANDIDATES_LIMIT`와 `VIEW_MAX_CANDIDATES`로 제한
- 리스크: 직접 언급 종목과 추론 후보가 섞여 사용자에게 오해를 줄 수 있다.
  - 대응: 뉴스 메시지는 `mentioned_stocks`만 표시하고, `theme_candidates`는 `/view` 내부 후보 확장에만 사용
- 리스크: 기존 호출부가 3튜플 반환에 의존한다.
  - 대응: 변경 범위를 Futu 시장 뷰 흐름부터 단계적으로 적용
