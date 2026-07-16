# China Chatbot

중국·홍콩 증시 속보와 관심종목 뉴스를 수집하고, Ollama로 한국어 번역해 텔레그램으로 전송하는 봇입니다.

## 주요 기능

- 전역 속보 다중 소스 수집: Futu(富途牛牛)·동방재부(东方财富)·신랑재경(新浪财经)·동화순(同花顺)·CLS(財联社)·임의 RSS(예: RSSHub)
- 소스 자동 페일오버: 연속 실패한 소스는 쿨다운 후 자동 재시도(수동 토글 불필요)
- 관심종목별 최근 7일 뉴스 수집
- Ollama 기반 한국어 번역 + 뉴스 감성 점수(-1~1)·영향도 평가, 관련 종목 코드 추출
- 관심종목 부정 뉴스(⚠️) 즉시 경고
- 뉴스 감성 신호 축적(`data/prediction_log.jsonl`)과 `/view` 종목별 상승/하락 참고 뷰, 오프라인 적중률 채점 스크립트
- A주·홍콩 종목 DB 생성(코드·이름·시장)
- 텔레그램 명령으로 Ollama GPU 오프로딩 설정 변경
- `ALLOWED_CHAT_IDS` 접근 제어(비우면 모두 허용)
- 전송 완료 기사 ID를 저장해 중복 전송 방지

## 동작 개요

봇은 시작 직후 뉴스 작업을 한 번 실행하고, 이후 `SCHEDULER_INTERVAL_MINUTES` 간격으로 반복합니다. 전역 뉴스 소스와 관심종목은 설정한 배치 크기만큼 회전 처리하므로, 관심종목이 많아도 매 주기에 모든 종목을 한꺼번에 조회하지 않습니다.

| 구분 | 현재 동작 |
|---|---|
| 전역 속보 | `NEWS_GLOBAL_SOURCES` 우선순위 목록(기본 futu,em,sina) 회전 처리, 소스별 최근 `NEWS_GLOBAL_LIMIT`건 확인 |
| 소스 페일오버 | 연속 `NEWS_SOURCE_FAILURE_THRESHOLD`회 실패 시 `NEWS_SOURCE_COOLDOWN_MINUTES`분 쿨다운 후 자동 복귀 |
| 관심종목 뉴스 | 종목별 최근 7일 뉴스 중 최대 `NEWS_STOCK_LIMIT_PER_SYMBOL`건 확인 |
| 감성 표기 | 번역과 같은 LLM 호출에서 감성·영향도 추출, 메시지에 🟢/⚪/🔴 표기 |
| 감성 뷰 | 전송 뉴스의 감성 신호를 축적하고 `/view`에서 최근 `VIEW_LOOKBACK_DAYS`일 종목별 집계 표시 |
| 번역 실패 | 해당 기사를 전송하지 않고 다음 주기에 다시 시도 |
| 중복 방지 | 전송 성공 기사만 `data/sent_ids.json`에 기록 |
| 종목 DB | 시작 시 캐시를 읽고, 없으면 생성. 매일 호스트 현지 시각 08:30에 갱신 |

> AkShare의 CLS 엔드포인트가 HTTP 404를 반환하는 동안 cls 소스는 기본 목록에서 빠져 있습니다. 복구되면 `NEWS_GLOBAL_SOURCES=futu,em,sina,cls`처럼 직접 추가하거나, RSSHub의 `/cls/telegraph` 라우트를 `NEWS_RSS_FEEDS`로 등록하세요.

## 요구 사항

- Python 3.10 이상(현재 개발 환경: Python 3.13)
- 텔레그램 봇 토큰과 전송 대상 채팅 ID
- Ollama와 설정한 모델(번역을 사용할 경우)

## 설치

PowerShell 기준:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

macOS/Linux에서는 가상환경 활성화 명령만 다음과 같이 바꿉니다.

```bash
source venv/bin/activate
```

## 환경 설정

프로젝트 루트의 `.env`를 수정합니다. 전체 옵션과 권장 시작값은 [`.env.example`](.env.example)에 있습니다.

설정 저장 방침: 모든 설정은 `.env`가 유일한 원본이며 봇 시작 시 1회 `app/core/config.py`에서만 읽습니다. `data/*.json`은 봇이 수집·축적하는 데이터(관심종목, 전송 이력 등)만 담고 설정값은 저장하지 않습니다. 텔레그램 `/system gpu` 명령으로 바꾼 GPU 설정은 세션 한정이며 재시작하면 `.env` 값으로 되돌아갑니다.

최소 설정:

```env
TELEGRAM_BOT_TOKEN=<텔레그램 봇 토큰>
TELEGRAM_CHAT_ID=<전송할 채널 또는 채팅방 ID>

OLLAMA_BASE_URL=http://localhost:11434
TRANSLATION_ENABLED=true
TRANSLATION_MODEL=gemma4:e4b
```

봇 토큰은 [@BotFather](https://t.me/BotFather)에서 발급합니다. `TELEGRAM_CHAT_ID`에는 예약 뉴스가 전송될 채널 또는 채팅방 ID를 지정하고, 봇에 메시지 전송 권한을 부여해야 합니다.

### 주요 옵션

| 옵션 | `.env.example` 값 | 설명 |
|---|---:|---|
| `OLLAMA_NUM_GPU` | `0` | Ollama GPU 설정. `-1`은 자동, `0`은 CPU 전용, 양수는 오프로딩 레이어 수. `/system gpu` 변경은 세션 한정 |
| `OLLAMA_GPU_ON_VALUE` | `-1` | `/system gpu on`으로 켤 때 적용할 값 |
| `TRANSLATION_ENABLED` | `true` | `false`이면 번역하지 않고 원문을 전송 |
| `TRANSLATION_TIMEOUT` | `60` | 번역 요청 제한 시간(초) |
| `TRANSLATION_NUM_PREDICT` | `4096` | 번역 응답 최대 생성 토큰 |
| `TRANSLATION_CONCURRENCY` | `1` | 동시에 실행할 번역 요청 수 |
| `NEWS_GLOBAL_SOURCES` | (빈 값) | 전역 소스 우선순위 목록(futu,em,sina,ths,cls). 비우면 futu,em,sina |
| `NEWS_RSS_FEEDS` | (빈 값) | `라벨\|URL,라벨\|URL` 형식 RSS 피드 추가 |
| `NEWS_SOURCE_FAILURE_THRESHOLD` | `3` | 소스 쿨다운 전 연속 실패 허용 횟수 |
| `NEWS_SOURCE_COOLDOWN_MINUTES` | `60` | 실패 소스 쿨다운 시간(분) |
| `NEWS_SENTIMENT_ENABLED` | `true` | 뉴스 메시지에 감성 점수 표기 |
| `NEWS_NEGATIVE_ALERT_THRESHOLD` | `-0.6` | 관심종목 부정 뉴스 경고 기준 감성 |
| `VIEW_LOOKBACK_DAYS` | `3` | `/view` 감성 뷰 집계에 사용할 최근 신호 일수 |
| `NEWS_ENABLE_CLS` | `false` | CLS 수집 활성화 여부(`NEWS_GLOBAL_SOURCES` 지정 시 무시) |
| `NEWS_SOURCE_FETCH_TIMEOUT_SECONDS` | `45` | 외부 뉴스 API 호출 제한 시간(초) |
| `NEWS_GLOBAL_LIMIT` | `3` | 소스별 한 주기 확인 범위 |
| `NEWS_STOCK_LIMIT_PER_SYMBOL` | `3` | 관심종목별 한 주기 확인 범위 |
| `GLOBAL_NEWS_BATCH_SIZE` | `1` | 한 주기에 처리할 전역 뉴스 소스 수. `0` 이하면 전체 처리 |
| `STOCK_NEWS_BATCH_SIZE` | `3` | 한 주기에 처리할 관심종목 수. `0` 이하면 전체 처리 |
| `STOCK_NEWS_FETCH_DELAY_SECONDS` | `0` | 배치 내 종목 조회 사이 대기 시간(초) |
| `SCHEDULER_INTERVAL_MINUTES` | `4` | 뉴스 작업 반복 간격(분) |
| `SENT_NEWS_RETENTION_DAYS` | `7` | 전송 기사 ID 보존 기간 |
| `STOCK_DB_ENABLED` | `true` | 종목 DB와 관련 종목 표시 기능 활성화 여부 |
| `ALLOWED_CHAT_IDS` | (빈 값) | 명령 허용 chat_id 목록. 비우면 모두 허용 |

`NEWS_GLOBAL_LIMIT`와 `NEWS_STOCK_LIMIT_PER_SYMBOL`은 반드시 전송할 기사 수가 아니라 확인할 최대 범위입니다. 신규 기사가 적거나 이미 전송한 기사뿐이면 실제 전송 수는 더 적습니다.

`SENT_NEWS_MAX_IDS`는 이전 설정과의 호환을 위해 남아 있지만 현재 구현에서는 개수 제한을 적용하지 않습니다. 기사 ID는 `SENT_NEWS_RETENTION_DAYS` 기준으로 만료됩니다.

### Ollama 준비

`.env.example`의 모델을 그대로 사용할 경우:

```powershell
ollama pull gemma4:e4b
ollama serve
```

`TRANSLATION_ENABLED=false`이면 뉴스는 중국어 원문으로 전송됩니다. 프롬프트는 시작할 때 읽으므로 `prompts/` 파일을 수정한 후에는 봇을 재시작해야 합니다.

## 실행

```powershell
python app\bot.py
```

동일한 작업 디렉터리에서 두 번째 인스턴스를 실행하면 `data/bot.lock`의 프로세스 잠금 때문에 종료됩니다. 종료는 `Ctrl+C`를 사용합니다.

## 텔레그램 명령어

| 명령어 | 설명 |
|---|---|
| `/start`, `/help` | 사용 가능한 명령어 표시 |
| `/add 600519` | 종목 코드를 조회해 관심종목에 추가 |
| `/list` | 현재 관심종목 목록 표시 |
| `/menu` | 버튼으로 관심종목 삭제 |
| `/view` | 관심종목별 뉴스 감성 뷰(상승/중립/하락) 요약 |
| `/view 600519` | 단일 종목 상세 뷰(근거 뉴스 포함) |
| `/score` | 운영 신호(`prediction_log.jsonl`) 적중률 채점 |
| `/score backtest` | 백필 신호(`backtest_log.jsonl`) 적중률 채점 |
| `/stockdb build` | 종목 코드·이름 DB 갱신 |
| `/system` | 현재 GPU 오프로딩 상태와 뉴스 소스 상태 표시 |
| `/system gpu on` | GPU 자동 오프로딩 활성화 |
| `/system gpu off` | CPU 전용으로 전환 |
| `/system gpu <레이어수>` | GPU 오프로딩 레이어 수 직접 지정 |

> 접근 제어: `ALLOWED_CHAT_IDS`에 chat_id를 지정하면 그 외 채팅의 명령·버튼은 조용히 무시됩니다. 비워 두면 기존처럼 모두 허용되므로, 외부 사용자가 봇을 찾을 수 있는 배포 환경에서는 반드시 설정하세요.

## 감성 뷰와 적중률 채점

전송된 뉴스의 감성·관련종목은 `data/prediction_log.jsonl`에 신호로 축적됩니다. `/view`는 이 신호를 최근 `VIEW_LOOKBACK_DAYS`일 기준으로 집계해 종목별 상승/중립/하락 **참고 뷰**를 보여줍니다(규칙 기반, LLM 추가 호출 없음). 예측이나 투자 조언이 아닙니다.

축적된 신호가 실제 주가 방향을 얼마나 맞췄는지는 텔레그램 `/score`(운영 로그) · `/score backtest`(백필 로그) 명령이나, 봇과 분리된 오프라인 스크립트로 채점합니다. 채점 로직(`app/state/scoring.py`)은 둘이 공유합니다.

```powershell
python scripts\score_predictions.py            # 1·3·5거래일 수평 채점
python scripts\score_predictions.py --horizons 1,3 --threshold 0.3
```

봇을 운영해 신호를 쌓지 않고도, 과거 뉴스를 일괄 수집해 백테스트할 수 있습니다(Ollama 실행 필요). 종목별 과거 뉴스를 봇과 동일한 프롬프트로 감성 추출하되 `ts`를 뉴스 발행 시각으로 기록해 별도 로그(`data/backtest_log.jsonl`)에 저장합니다. 중단 후 재실행하면 처리한 기사는 건너뜁니다.

```powershell
python scripts\backfill_predictions.py                       # 관심종목 전체, 최근 30일
python scripts\backfill_predictions.py --codes 600519 --days 14 --limit 10
python scripts\score_predictions.py --log data\backtest_log.jsonl
```

> 뉴스 API가 종목당 최근 약 100건만 반환하므로 임의 과거 구간 백필은 불가능하며, 실제 커버 범위는 종목의 뉴스 빈도에 따라 대략 최근 수 주입니다.

적중률은 항상-상승 기준선(base rate)과 함께 표기되며, 이를 지속적으로 상회해야 신호에 정보가 있다고 판단합니다. 자세한 프로토콜과 확장 계획은 [`docs/plan.md`](docs/plan.md)를 참고하세요.

## 관심종목과 종목 DB

관심종목에는 종목 코드만 입력합니다. 이름은 `data/stock_db.json`에서 조회합니다.

- 홍콩 종목: 5자리 코드(예: `09988`)
- 상하이·선전 A주: 6자리 코드(예: `600519`, `000001`)
- HKEX Northbound Stock Connect 개인투자자 가능 목록에 포함된 종목만 DB에 등록
- ChiNext(`300`, `301`)와 STAR Market(`688`, `689`) 종목은 현재 제외

종목 DB는 AkShare의 A주·홍콩 종목명과 HKEX 가능 종목 목록을 결합합니다. 종목명은 중국어 원본 `cn_name`, 한국식 한자음 `ko_name`, 표시명 `display_name`으로 저장됩니다.

## 상태 파일

실행 중 생성되는 상태·캐시·잠금 파일은 Git에서 제외됩니다.

| 파일 | 용도 |
|---|---|
| `data/watchlist.json` | 관심종목 목록 |
| `data/sent_ids.json` | 중복 전송 방지용 기사 ID와 전송 시각 |
| `data/prediction_log.jsonl` | 뉴스 감성 신호 로그(`/view` 집계·채점 입력) |
| `data/stock_db.json` | 종목 코드·이름·시장 캐시 |
| `data/bot.lock` | 단일 인스턴스 실행 잠금 |

GPU 설정(`OLLAMA_NUM_GPU`)은 `.env`가 원본입니다. `/system gpu` 명령의 변경은 세션 한정이며 재시작하면 `.env` 값으로 되돌아갑니다.

## 프로젝트 구조

```text
china_chatbot/
├── app/
│   ├── bot.py                 # 서비스 구성, 핸들러 등록, 스케줄러
│   ├── core/                  # 환경 설정, 접근 제어, 런타임 시스템 제어
│   ├── handlers/              # 공통 텔레그램 명령어
│   ├── llm/                   # Ollama 뉴스 번역
│   ├── news/                  # 뉴스 소스 레지스트리, 가공, 전송 파이프라인
│   ├── state/                 # 전송 기사 상태, 감성 신호 로그
│   ├── stocks/                # 종목 DB
│   └── watchlist/             # 관심종목 저장, 텔레그램 UI
├── data/                      # 런타임 상태와 캐시(Git 제외)
├── prompts/                   # 뉴스 번역 프롬프트
├── scripts/                   # 오프라인 도구(감성 신호 적중률 채점)
├── tests/                     # 단위 테스트
├── .env.example               # 환경 변수 예시
├── requirements.txt
└── README.md
```

## 운영 시 참고 사항

- 외부 뉴스 API, HKEX, Ollama, Telegram 중 하나가 느리거나 중단되면 해당 작업만 로그에 실패로 기록되고 그 작업의 다음 실행에서 다시 진행됩니다.
- 스케줄 작업은 동시에 중복 실행되지 않으며, 이전 작업이 길어지면 누락된 실행은 합쳐집니다.
- `data/`를 삭제하면 관심종목, 중복 전송 이력 등 축적 데이터가 초기화됩니다.
- `TELEGRAM_BOT_TOKEN`과 실제 `.env` 파일은 커밋하지 마세요.
