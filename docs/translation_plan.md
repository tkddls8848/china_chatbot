# 번역 기능 구현 계획

## 개요

AkShare로 수집한 중국어 뉴스를 Ollama `gemma4` 모델로 한국어 번역한 뒤 텔레그램에 전송한다.

번역 프롬프트는 파이썬 코드가 아니라 별도 텍스트 파일로 관리한다. 프롬프트 튜닝 시 `bot.py`나 `translator.py`를 수정하지 않도록 하기 위함이다.

---

## 파일 구조

```text
china_chatbot/
├── app/
│   ├── bot.py             # 메인 봇 로직
│   └── translator.py      # TranslationService + Ollama HTTP 호출
├── data/
│   ├── sent_ids.json
│   └── watchlist.json
├── docs/
│   └── translation_plan.md
├── prompts/
│   ├── cls_ko.txt         # 신규: 財联社 뉴스 번역 프롬프트
│   ├── futu_ko.txt        # 신규: 富途牛牛 뉴스 번역 프롬프트
│   └── stock_ko.txt       # 신규: 관심종목 뉴스 번역 프롬프트
├── .env
├── requirements.txt
└── README.md
```

---

## 단계별 구현

### Step 1. 프롬프트 파일 작성

`prompts/` 디렉터리에 뉴스 소스별 프롬프트 파일을 둔다.

| 파일 | 용도 |
|------|------|
| `prompts/cls_ko.txt` | 財联社 속보 번역 |
| `prompts/futu_ko.txt` | 富途牛牛 속보 번역 |
| `prompts/stock_ko.txt` | 관심종목 뉴스 번역 |

각 프롬프트는 아래 규칙을 포함한다.

- 중국어 금융 뉴스를 한국어로 정확하게 번역한다.
- 원문에 없는 내용을 추가하지 않는다.
- 투자 조언, 전망, 매수/매도 의견을 추가하지 않는다.
- 회사명, 종목명, 숫자, 날짜, 금액, 퍼센트는 최대한 보존한다.
- 제목은 자연스러운 한국어 뉴스 제목으로 번역한다.
- 본문은 자연스러운 한국어로 번역하되, 너무 길면 핵심을 유지해 3~6문장으로 정리한다.
- 설명이나 주석 없이 JSON만 출력한다.

출력 형식:

```json
{"title": "한국어 제목", "content": "한국어 본문"}
```

JSON을 강제하는 이유는 파싱 실패 여부를 명확히 감지하고, 텔레그램 메시지에서 제목과 본문을 안정적으로 분리하기 위함이다.

---

### Step 2. `app/translator.py` 작성

`app/translator.py`는 번역 관련 책임만 가진다.

```python
class TranslationService:
    def __init__(self, base_url: str, model: str, enabled: bool, timeout: int, prompt_dir: Path)
    def translate_article(self, source: str, title: str, content: str) -> tuple[str, str]
```

프롬프트 파일은 `__init__` 시점에 전부 읽어 메모리에 캐싱한다. 매 번역마다 파일 I/O가 발생하지 않도록 하기 위함이다. 프롬프트를 수정하려면 봇을 재시작해야 한다.

내부 동작:

```text
translate_article("cls", title, content)
    |
    |- enabled=false 이면 (title, content) 원문 반환
    |- 캐싱된 프롬프트 딕셔너리에서 source 키로 조회
    |- Ollama POST /api/chat 호출
    |    model: gemma4
    |    stream: false
    |    format: "json"   ← JSON 출력 강제
    |- 응답 JSON 파싱
    |- 성공 시 (ko_title, ko_content) 반환
    |- 실패 시 WARNING 로그 + (title, content) 원문 반환
```

Ollama 호출은 `requests` 동기 호출을 사용하고, `bot.py`에서는 `asyncio.to_thread()`로 감싼다. 현재 구조에서 추가 async HTTP 의존성을 늘리지 않기 위함이다.

Ollama API는 `/api/generate`보다 `/api/chat`을 우선 사용한다. 시스템 지침과 기사 입력을 분리하기 쉽기 때문이다.

`format: "json"` 파라미터를 요청에 포함한다. gemma4가 프롬프트 지시만으로는 JSON 형식을 지키지 않을 수 있어, Ollama 수준에서 JSON 출력을 강제한다.

예상 요청 형태:

```python
requests.post(
    f"{base_url}/api/chat",
    json={
        "model": model,
        "messages": [
            {"role": "system", "content": prompt_text},
            {
                "role": "user",
                "content": f"제목:\n{title}\n\n본문:\n{content}",
            },
        ],
        "stream": False,
        "format": "json",
    },
    timeout=timeout,
)
```

---

### Step 3. `app/bot.py` 수정

변경 범위는 최소화한다.

- `TranslationService` 초기화 추가
- `fetch_cls`, `fetch_futu`, `fetch_stock_news`에 번역 호출 추가
- `fetch_all`에서 translator를 각 fetch 함수에 전달
- `SentNewsTracker`의 저장 시점을 텔레그램 전송 성공 이후로 조정

초기화 예시:

```python
app.bot_data["translator"] = TranslationService(
    base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
    model=os.environ.get("TRANSLATE_MODEL", "gemma4"),
    enabled=os.environ.get("TRANSLATE_ENABLED", "true").lower() == "true",
    timeout=int(os.environ.get("TRANSLATE_TIMEOUT", "60")),
    prompt_dir=Path(os.environ.get("TRANSLATE_PROMPT_DIR", "prompts")),
    fallback_to_original=(
        os.environ.get("TRANSLATE_FALLBACK_TO_ORIGINAL", "false").lower() == "true"
    ),
)
```

fetch 함수 변경 패턴:

```python
raw_title = str(row["标题"])
raw_content = str(row["内容"])

title, content = await asyncio.to_thread(
    translator.translate_article,
    "cls",
    raw_title,
    raw_content,
)

title = html.escape(title)
content = html.escape(content)
```

---

### Step 4. `sent_ids.json` 저장 정책 개선

기존 `check_and_add()`는 전송 전에 기사 ID를 저장한다. 번역 기능을 넣을 때 `reserve/confirm/release` 구조로 바꾼다.

`max_instances`는 현재 1이지만 나중에 바뀔 수 있으므로 현재 스케줄러 설정에 의존하지 않는다. `reserve()`가 sent/pending 집합을 한 번의 락 안에서 확인하고 pending에 등록해 동일 기사의 중복 처리를 막는다.

```python
if not await tracker.reserve(article_id):
    continue

# 번역
# 텔레그램 전송

await tracker.confirm(article_id)
```

번역 또는 텔레그램 전송이 실패하면 `release(article_id)`로 pending 예약을 해제한다. `sent_ids.json`에는 `confirm()`된 ID만 저장한다.

권장 정책:

- 번역 성공 + 텔레그램 전송 성공: `sent_ids.json`에 저장
- 번역 실패 + 원문 fallback 전송 성공: `sent_ids.json`에 저장
- 텔레그램 전송 실패: 저장하지 않음

이렇게 하면 Ollama 장애 때 같은 기사가 반복 전송되는 일을 막으면서, Telegram 전송 실패는 다음 주기에 재시도할 수 있다.

---

### Step 5. `.env` 업데이트

```env
TRANSLATE_ENABLED=true
OLLAMA_BASE_URL=http://localhost:11434
TRANSLATE_MODEL=gemma4:e4b
TRANSLATE_TIMEOUT=60
TRANSLATE_PROMPT_DIR=prompts
TRANSLATE_FALLBACK_TO_ORIGINAL=false
TRANSLATE_CONCURRENCY=1
CLS_FUTU_NEWS_LIMIT=10
STOCK_NEWS_LIMIT=5
SCHEDULE_INTERVAL_MINUTES=3
```

`TRANSLATE_BATCH_SIZE`는 첫 구현에서는 사용하지 않는다. 현재 봇은 기사별로 텔레그램 메시지를 전송하므로, 배치 번역은 메시지-기사 매핑과 실패 처리를 복잡하게 만든다. 필요하면 번역 품질과 속도를 확인한 뒤 별도 단계로 도입한다.

---

### Step 6. 검증

| 검증 항목 | 방법 |
|-----------|------|
| 문법 검사 | `python -m py_compile app/bot.py app/translator.py` |
| Ollama 모델 확인 | `ollama list`로 `gemma4` 존재 확인 |
| 번역 off 동작 | `TRANSLATE_ENABLED=false` 설정 후 중국어 원문 전송 확인 |
| 번역 on 동작 | `TRANSLATE_ENABLED=true` 설정 후 한국어 전송 확인 |
| Ollama 장애 재시도 | Ollama 중단 후 원문 미전송 + 다음 주기 재시도 확인 |
| JSON 파싱 실패 재시도 | 잘못된 응답 발생 시 원문 미전송 + 다음 주기 재시도 확인 |
| Telegram 전송 실패 재시도 | 전송 실패 시 `sent_ids.json`에 저장되지 않는지 확인 |

---

### Step 7. README 업데이트

검증 완료 후 README에 아래 내용을 추가한다.

- Ollama 설치 및 실행 방법
- `gemma4` 모델 pull 방법
- 번역 관련 `.env` 설정값
- `TRANSLATE_ENABLED=false`일 때 중국어 원문을 전송한다는 설명
- Ollama 장애 시 원문 fallback 정책
- 프롬프트 수정 시 봇 재시작이 필요하다는 안내

```bash
ollama pull gemma4
ollama serve
```

---

## 미결 사항

- [ ] `ollama list`로 `gemma4` pull 여부 확인
- [ ] gemma4 금융 뉴스 번역 품질 확인 후 프롬프트 튜닝
- [ ] 번역 속도가 느릴 경우 모델 크기 변경 또는 후속 배치 번역 도입 검토
