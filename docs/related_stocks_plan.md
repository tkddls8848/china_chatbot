# 관련종목 자동 추출 계획

## 개요

번역된 뉴스 하단에 아래 형식의 관련종목 라인을 자동으로 추가한다.

```
관련종목 : 09988(阿里巴巴), 600519(贵州茅台)
```

기업명은 AkShare DB의 중국어명을 그대로 사용한다. 한국어 번역은 하지 않는다.

대상 시장은 홍콩 메인보드, 상해·심천 메인보드(A주), 과창판(科创板), 창업판(创业板)이다.

---

## 핵심 설계 원칙

| 원칙 | 이유 |
|------|------|
| LLM이 종목코드만 추출, AkShare DB가 코드 검증 후 중국어명 제공 | 기업명은 AkShare DB에서 가져오므로 LLM이 이름을 알 필요 없음 |
| 번역과 추출을 같은 LLM 호출에서 처리 | 기사당 추가 Ollama 호출 없이 응답 JSON에 `related` 필드 추가 |
| 코드가 AkShare DB에 없으면 제거 | 코드 정확성 보장, 환각 필터 역할 |
| 주식 DB는 시작 시 1회 빌드, 매일 새벽 갱신 | AkShare 반복 호출 최소화 |

---

## 데이터 흐름

```
중국어 뉴스
  │
  ▼
Ollama (번역 + 종목 추출)
  │
  ▼
{"title": "KO", "content": "KO", "related": ["09988", "600519"]}
  │
  ▼
StockDatabase (코드 유효성 확인 + 중국어명 조회)
  │
  ▼
유효 코드만 남김 → "관련종목 : 09988(阿里巴巴), 600519(贵州茅台)"
  │
  ▼
텔레그램 메시지 footer에 추가
```

---

## 파일 구조 변경

```text
china_chatbot/
├── app/
│   ├── bot.py             ← fetch 함수 + _build_news_message 수정
│   ├── translator.py      ← translate_article 반환값 확장
│   └── stock_db.py        ← 신규: AkShare 주식 DB 빌드 및 조회
├── data/
│   ├── sent_ids.json
│   ├── watchlist.json
│   └── stock_db.json      ← 신규: 종목코드→중국명 캐시 (자동 생성)
├── prompts/
│   ├── cls_ko.txt         ← related 필드 추가
│   ├── futu_ko.txt
│   └── stock_ko.txt
```

---

## Step 1. AkShare 주식 DB 구성 (`app/stock_db.py`)

### 사용 AkShare API

| 대상 시장 | AkShare 함수 | 종목코드 패턴 |
|-----------|-------------|-------------|
| 상해 메인보드 | `ak.stock_info_a_code_name()` | 60xxxx |
| 과창판 (科创板) | 동일 함수 포함 | 688xxx, 689xxx |
| 심천 메인보드 | 동일 함수 포함 | 000xxx, 001xxx, 002xxx, 003xxx |
| 창업판 (创业板) | 동일 함수 포함 | 300xxx, 301xxx |
| 홍콩 메인보드 | `ak.stock_hk_spot_em()` | 0xxxx (5자리) |

`ak.stock_info_a_code_name()` 한 번으로 A주 전체(상해+심천 전 시장)를 커버한다.

### 클래스 설계

```python
class StockDatabase:
    def __init__(self, cache_file: Path)
    def build(self) -> None          # AkShare 호출, cache_file에 저장
    def load(self) -> None           # cache_file에서 로드
    def is_valid_code(self, code: str) -> bool
    def get_cn_name(self, code: str) -> str | None
```

### 내부 저장 구조

```json
{
  "09988": {"name": "阿里巴巴集团控股有限公司", "market": "HK"},
  "600519": {"name": "贵州茅台", "market": "SH"},
  "300750": {"name": "宁德时代", "market": "SZ"},
  "688041": {"name": "海光信息", "market": "STAR"}
}
```

### 시장 구분 로직

```python
def _classify_market(code: str) -> str:
    if len(code) <= 5:
        return "HK"
    if code.startswith(("688", "689")):
        return "STAR"
    if code.startswith(("300", "301")):
        return "CHI"     # ChiNext 창업판
    if code.startswith("6"):
        return "SH"
    return "SZ"
```

### 빌드 함수 핵심 로직

```python
def build(self) -> None:
    # A주 전체
    df_a = ak.stock_info_a_code_name()
    # 컬럼: 'code' (股票代码), 'name' (股票名称)

    # 홍콩
    df_hk = ak.stock_hk_spot_em()
    # 컬럼: '代码' (5자리), '名称'

    db = {}
    for _, row in df_a.iterrows():
        code = str(row["code"]).zfill(6)
        db[code] = {"name": str(row["name"]), "market": _classify_market(code)}

    for _, row in df_hk.iterrows():
        code = str(row["代码"]).zfill(5)
        db[code] = {"name": str(row["名称"]), "market": "HK"}

    self._cache_file.write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
    self._db = db
```

---

## Step 2. 프롬프트 수정

세 프롬프트 파일(`cls_ko.txt`, `futu_ko.txt`, `stock_ko.txt`)에 아래 규칙과 출력 필드를 추가한다.

### 추가할 규칙

```
- 본문에 명시적으로 언급된 홍콩·상해·심천 상장 기업이 있으면 종목코드를 related에 포함한다.
- related는 본문에서 직접 언급된 종목만 포함한다. 추론이나 연관 종목은 포함하지 않는다.
- 종목코드가 불확실하면 related를 빈 배열로 출력한다.
```

### 변경된 출력 형식

```
출력:
{"title": "한국어 제목", "content": "한국어 본문", "related": ["09988", "600519"]}
```

`related`는 종목코드 문자열의 배열이다. 없는 경우에는 `[]`로 출력한다.  
기업명은 코드만 있으면 `StockDatabase`에서 자동으로 조회하므로 LLM이 이름을 출력할 필요가 없다.

---

## Step 3. `TranslationService` 수정 (`app/translator.py`)

### 반환 타입 변경

```python
# 변경 전
def translate_article(self, source, title, content) -> tuple[str, str]

# 변경 후
def translate_article(self, source, title, content) -> tuple[str, str, list[str]]
# 반환: (ko_title, ko_content, related_codes)
# related_codes 예: ["09988", "600519"]
```

### `_parse_translation` 수정

```python
def _parse_translation(self, translated: str) -> tuple[str, str, list[str]]:
    data = json.loads(translated)
    title = data.get("title")
    content = data.get("content")
    related = data.get("related", [])

    if not isinstance(title, str) or not title.strip():
        raise ValueError("translation JSON missing title")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("translation JSON missing content")
    if not isinstance(related, list):
        related = []

    # 문자열 코드만 필터링
    related_codes = [c for c in related if isinstance(c, str) and c.strip()]

    return title.strip(), content.strip(), related_codes
```

`related` 필드가 없거나 파싱 실패 시 빈 리스트를 반환해 기존 번역 흐름을 깨뜨리지 않는다.

---

## Step 4. `bot.py` 수정

### `_translate_article` 반환 타입

```python
async def _translate_article(...) -> tuple[str, str, list[str]]:
```

### `_build_news_message` 수정

```python
def _build_news_message(
    header: str,
    title: str,
    content: str,
    footer: str = "",
    related_stocks: list[tuple[str, str]] | None = None,  # [(code, cn_name), ...]
) -> str:
```

`related_stocks`가 있으면 footer 앞에 관련종목 라인을 삽입한다.

```python
if related_stocks:
    items = ", ".join(f"{code}({name})" for code, name in related_stocks)
    related_line = f"\n\n🔖 관련종목 : {items}"
else:
    related_line = ""
```

최종 조합:

```python
text = f"{header}{title_part}{safe_content}{related_line}{footer}"
```

### `StockDatabase`를 이용한 코드 검증 및 이름 조회

각 `prepare_row` 함수에서 번역 후 코드 검증과 중국어명 조회를 함께 수행한다.

```python
title, content, related_codes = await _translate_article(...)

stock_db: StockDatabase = app.bot_data["stock_db"]
related_stocks = []
for code in related_codes:
    cn_name = stock_db.get_cn_name(code)   # None이면 DB에 없는 코드 → 제거
    if cn_name:
        related_stocks.append((code, cn_name))

text = _build_news_message(
    header=...,
    title=title,
    content=content,
    related_stocks=related_stocks,
)
```

`get_cn_name()`이 유효성 검증과 이름 조회를 동시에 담당하므로 `is_valid_code()`를 별도로 호출할 필요가 없다.

### `bot_data` 초기화 추가

```python
stock_db = StockDatabase(cache_file=BASE_DIR / "data" / "stock_db.json")
stock_db.load_or_build()   # 캐시 있으면 로드, 없으면 AkShare 빌드
app.bot_data["stock_db"] = stock_db
```

### 일별 DB 갱신 스케줄러

```python
scheduler.add_job(
    lambda: stock_db.build(),
    trigger="cron",
    hour=8,
    minute=30,
    id="refresh_stock_db",
)
```

평일 장 개시 전 갱신하므로 당일 신규 상장 종목도 반영된다.

---

## Step 5. `.env` 추가 설정

```env
STOCK_DB_ENABLED=true        # false이면 관련종목 추출 비활성화
```

`STOCK_DB_ENABLED=false`이면 `StockDatabase.is_valid_code()`가 항상 `False`를 반환해 related 라인이 표시되지 않는다.

---

## Step 6. 검증 항목

| 항목 | 방법 |
|------|------|
| AkShare DB 빌드 | `python -c "from app.stock_db import StockDatabase; ..."` 직접 실행 |
| 코드 검증 동작 | `is_valid_code("09988")` → True, `is_valid_code("99999")` → False |
| 프롬프트 파싱 | `related` 필드 있는 경우 / 없는 경우 / 빈 배열 각각 확인 |
| 텔레그램 메시지 | 관련종목 라인 있는 기사와 없는 기사 모두 정상 전송 확인 |
| 글자 수 초과 처리 | `TELEGRAM_MESSAGE_LIMIT` 초과 시 content 우선 절단, 관련종목 라인은 유지 |
| DB 빌드 실패 시 | `load_or_build` 예외 → WARNING 로그 후 빈 DB로 동작 (관련종목 미표시) |

---

## Step 7. 구현 순서

1. `app/stock_db.py` 작성 및 독립 실행으로 DB 빌드 확인
2. 프롬프트 파일 3개 수정 (related 필드 추가)
3. `translator.py` 수정 (반환 타입 변경, `_parse_translation` 업데이트)
4. `bot.py` 수정 (StockDatabase 초기화, `_translate_article`, `_build_news_message`)
5. `.env` 및 `.env.example`에 `STOCK_DB_ENABLED` 추가
6. 문법 검사: `python -m py_compile app/bot.py app/translator.py app/stock_db.py`
7. 봇 실행 후 관련종목 라인 표시 확인

---

## 미결 사항

- [ ] `ak.stock_info_a_code_name()` 반환 컬럼명 실환경 확인 (`code` / `股票代码` 등 버전별 차이)
- [ ] `ak.stock_hk_spot_em()` 홍콩 코드가 5자리 `05` 형태인지 `5` 형태인지 확인
- [ ] LLM이 코드 환각 없이 `related` 필드(코드 문자열 배열)를 안정적으로 채우는지 실기사로 품질 검증
- [ ] `related`가 빈번히 비어 있다면 별도 NER 단계(jieba + AkShare 명칭 사전 매칭) 도입 검토
- [ ] 북경거래소(北交所, 43xxx / 8xxxx) 포함 여부 결정
