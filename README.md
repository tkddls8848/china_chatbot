# China Chatbot

중국·홍콩 증시 속보와 관심종목 뉴스를 수집하고, Ollama로 한국어 번역·분석해 텔레그램으로 전송하는 봇입니다.

## 주요 기능

- 전역 속보 다중 소스 수집: Futu(富途牛牛)·동방재부(东方财富)·신랑재경(新浪财经)·동화순(同花顺)·CLS(財联社)·임의 RSS(예: RSSHub)
- 소스 자동 페일오버: 연속 실패한 소스는 쿨다운 후 자동 재시도(수동 토글 불필요)
- 관심종목별 최근 7일 뉴스 수집
- Ollama 기반 한국어 번역 + 뉴스 감성 점수(-1~1)·영향도 평가, 관련 종목 코드와 테마 후보 추출
- 관심종목 부정 뉴스(⚠️) 즉시 경고
- 정량 컨텍스트: 관심종목 시세·주력 자금흐름, 섹터 상·하위 보드, 涨停 수, 인기순위·용호방(龙虎榜) 진입
- 모닝/마감 브리핑: A주 거래일에만 자동 발송, LLM 코멘트 포함(실패 시 데이터 전용)
- 리서치 주제와 최근 전역 뉴스+정량 컨텍스트 기반 관심종목 추가·삭제 후보 분석
- bull/bear 2차 검증 패스: 약한 후보를 기각하고 찬반 근거를 함께 표시
- 분석 이력 메모리: 직전 분석 요약을 다음 분석 프롬프트에 주입
- 후보군 확장: 강세 섹터 구성종목 + 问财 자연어 스크리닝(옵션)
- 관심리스트 편입·편출 이벤트 기록과 주간 시장뷰 성적표
- 텔레그램 버튼으로 리서치 결과를 확인한 뒤 관심종목에 적용
- A주·홍콩 종목 DB 생성 및 EODHD 시가총액·업종 보강
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
| 모닝 브리핑 | 거래일 `BRIEFING_MORNING_HOUR:MINUTE`(기본 08:50)에 시세·뉴스·LLM 코멘트 발송 |
| 마감 브리핑 | 거래일 `BRIEFING_EVENING_HOUR:MINUTE`(기본 17:40)에 시세·자금흐름·감성 집계 발송 |
| 주간 성적표 | `SCORECARD_DAY_OF_WEEK`(기본 토) `SCORECARD_HOUR`시에 편입·편출 성과 요약 |
| 번역 실패 | 해당 기사를 전송하지 않고 다음 주기에 다시 시도 |
| 중복 방지 | 전송 성공 기사만 `data/sent_ids.json`에 기록 |
| 종목 DB | 시작 시 캐시를 읽고, 없으면 생성. 매일 호스트 현지 시각 08:30에 갱신 |

> AkShare의 CLS 엔드포인트가 HTTP 404를 반환하는 동안 cls 소스는 기본 목록에서 빠져 있습니다. 복구되면 `NEWS_GLOBAL_SOURCES=futu,em,sina,cls`처럼 직접 추가하거나, RSSHub의 `/cls/telegraph` 라우트를 `NEWS_RSS_FEEDS`로 등록하세요.

## 요구 사항

- Python 3.10 이상(현재 개발 환경: Python 3.13)
- 텔레그램 봇 토큰과 전송 대상 채팅 ID
- Ollama와 설정한 모델(번역 또는 리서치 분석을 사용할 경우)
- EODHD API 토큰(`/stockdb enrich`를 사용할 경우에만 필요)

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

최소 설정:

```env
TELEGRAM_BOT_TOKEN=<텔레그램 봇 토큰>
TELEGRAM_CHAT_ID=<전송할 채널 또는 채팅방 ID>

OLLAMA_BASE_URL=http://localhost:11434
TRANSLATION_ENABLED=true
TRANSLATION_MODEL=gemma4:e4b
RESEARCH_ANALYSIS_ENABLED=true
RESEARCH_ANALYSIS_MODEL=gemma4:e4b
```

봇 토큰은 [@BotFather](https://t.me/BotFather)에서 발급합니다. `TELEGRAM_CHAT_ID`에는 예약 뉴스가 전송될 채널 또는 채팅방 ID를 지정하고, 봇에 메시지 전송 권한을 부여해야 합니다.

### 주요 옵션

| 옵션 | `.env.example` 값 | 설명 |
|---|---:|---|
| `OLLAMA_NUM_GPU` | `0` | 초기 Ollama GPU 설정. `-1`은 자동, `0`은 CPU 전용, 양수는 오프로딩 레이어 수 |
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
| `EODHD_ENRICH_LIMIT` | `200` | `/stockdb enrich` 한 번에 보강할 최대 종목 수 |
| `EODHD_ENRICH_DELAY` | `0.5` | EODHD 종목별 요청 사이 대기 시간(초) |
| `RESEARCH_ANALYSIS_NUM_PREDICT` | `2048` | 리서치 분석 응답 최대 생성 토큰 |
| `RESEARCH_NEWS_MAX_ITEMS` | `3` | 리서치 한 번에 사용할 최대 뉴스 수 |
| `RESEARCH_NEWS_GLOBAL_LIMIT` | `3` | 리서치 소스별 뉴스 확인 범위 |
| `RESEARCH_VERIFICATION_ENABLED` | `true` | 추가/삭제 후보 bull/bear 2차 검증 패스 |
| `RESEARCH_HISTORY_LIMIT` | `5` | 분석 이력 보존 개수(다음 분석에 맥락 주입) |
| `RESEARCH_SECTOR_CANDIDATES_ENABLED` | `true` | 강세 섹터 구성종목 후보 추가 |
| `WENCAI_ENABLED` | `false` | 问财 자연어 스크리닝(별도 `pip install pywencai` 필요) |
| `QUANT_CONTEXT_ENABLED` | `true` | 정량 컨텍스트(시세·자금흐름 등) 수집 |
| `QUANT_CACHE_TTL_MINUTES` | `10` | 시장 전체 시세 테이블 캐시 시간(분) |
| `BRIEFING_MORNING_ENABLED` | `true` | 모닝 브리핑 자동 발송 |
| `BRIEFING_EVENING_ENABLED` | `true` | 마감 브리핑 자동 발송 |
| `BRIEFING_LLM_ENABLED` | `true` | 브리핑에 Ollama 코멘트 포함 |
| `SCORECARD_ENABLED` | `true` | 주간 시장뷰 성적표 발송 |
| `ALLOWED_CHAT_IDS` | (빈 값) | 명령 허용 chat_id 목록. 비우면 모두 허용 |

`NEWS_GLOBAL_LIMIT`와 `NEWS_STOCK_LIMIT_PER_SYMBOL`은 반드시 전송할 기사 수가 아니라 확인할 최대 범위입니다. 신규 기사가 적거나 이미 전송한 기사뿐이면 실제 전송 수는 더 적습니다.

`SENT_NEWS_MAX_IDS`는 이전 설정과의 호환을 위해 남아 있지만 현재 구현에서는 개수 제한을 적용하지 않습니다. 기사 ID는 `SENT_NEWS_RETENTION_DAYS` 기준으로 만료됩니다.

### Ollama 준비

`.env.example`의 모델을 그대로 사용할 경우:

```powershell
ollama pull gemma4:e4b
ollama serve
```

`TRANSLATION_ENABLED=false`이면 뉴스는 중국어 원문으로 전송됩니다. 리서치 분석도 사용하지 않으려면 `RESEARCH_ANALYSIS_ENABLED=false`로 설정하세요. 프롬프트는 시작할 때 읽으므로 `prompts/` 파일을 수정한 후에는 봇을 재시작해야 합니다.

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
| `/research show` | 저장된 리서치 주제와 최근 결과 표시 |
| `/research set <주제>` | 리서치 주제 저장 |
| `/research run` | 저장한 주제로 리서치 실행 |
| `/research <주제>` | 주제를 저장하지 않고 일회성 리서치 실행 |
| `/research clear` | 저장한 주제와 최근 분석 결과 삭제 |
| `/briefing morning` | 모닝 브리핑 즉시 실행(휴장일 무시) |
| `/briefing evening` | 마감 브리핑 즉시 실행(휴장일 무시) |
| `/briefing scorecard` | 시장뷰 성적표 즉시 실행 |
| `/stockdb build` | 종목 코드·이름 DB 갱신 |
| `/stockdb enrich` | EODHD로 시가총액·업종 보강 |
| `/system` | 현재 GPU 오프로딩 상태 표시 |
| `/system gpu on` | GPU 자동 오프로딩 활성화 |
| `/system gpu off` | CPU 전용으로 전환 |
| `/system gpu <레이어수>` | GPU 오프로딩 레이어 수 직접 지정 |

`/research run`은 활성 전역 뉴스, 리서치 주제, 현재 관심종목, 종목 DB·강세 섹터·问財(옵션) 후보군, 정량 컨텍스트, 직전 분석 이력을 Ollama에 전달합니다. `RESEARCH_VERIFICATION_ENABLED=true`이면 추가/삭제 후보에 대해 bull(🐂)/bear(🐻) 근거를 만드는 2차 검증을 수행하고 약한 후보는 기각 목록으로 분리합니다. 결과는 즉시 관심종목을 바꾸지 않으며, 텔레그램의 **적용** 버튼을 눌러야 추가·삭제가 반영됩니다.

> 접근 제어: `ALLOWED_CHAT_IDS`에 chat_id를 지정하면 그 외 채팅의 명령·버튼은 조용히 무시됩니다. 비워 두면 기존처럼 모두 허용되므로, 외부 사용자가 봇을 찾을 수 있는 배포 환경에서는 반드시 설정하세요.

## 관심종목과 종목 DB

관심종목에는 종목 코드만 입력합니다. 이름은 `data/stock_db.json`에서 조회합니다.

- 홍콩 종목: 5자리 코드(예: `09988`)
- 상하이·선전 A주: 6자리 코드(예: `600519`, `000001`)
- HKEX Northbound Stock Connect 개인투자자 가능 목록에 포함된 종목만 DB에 등록
- ChiNext(`300`, `301`)와 STAR Market(`688`, `689`) 종목은 현재 제외

종목 DB는 AkShare의 A주·홍콩 종목명과 HKEX 가능 종목 목록을 결합합니다. 종목명은 중국어 원본 `cn_name`, 한국식 한자음 `ko_name`, 표시명 `display_name`으로 저장됩니다. `/stockdb enrich`는 `EODHD_API_TOKEN`을 사용해 아직 보강되지 않은 종목에 시가총액과 업종을 추가하며, 시작 시 자동 실행되지는 않습니다.

## 상태 파일

실행 중 생성되는 상태·캐시·잠금 파일은 Git에서 제외됩니다.

| 파일 | 용도 |
|---|---|
| `data/watchlist.json` | 관심종목 목록 |
| `data/watchlist_events.json` | 편입·편출 이벤트와 당시 가격(성적표 근거) |
| `data/sent_ids.json` | 중복 전송 방지용 기사 ID와 전송 시각 |
| `data/news_log.json` | 전송 뉴스의 감성·관련종목 로그(마감 브리핑 집계용) |
| `data/stock_db.json` | 종목 코드·이름·시장·보강 데이터 캐시 |
| `data/market_research.json` | 리서치 주제, 최근 분석 결과와 이력 |
| `data/runtime_config.json` | 텔레그램에서 변경한 GPU 설정 |
| `data/bot.lock` | 단일 인스턴스 실행 잠금 |

`data/runtime_config.json`의 값은 `.env`의 `OLLAMA_NUM_GPU`보다 우선하며 재시작 후에도 유지됩니다. 초기값으로 되돌리려면 봇을 종료한 상태에서 해당 파일을 삭제한 뒤 다시 실행하세요.

## 프로젝트 구조

```text
china_chatbot/
├── app/
│   ├── bot.py                 # 서비스 구성, 핸들러 등록, 스케줄러
│   ├── briefing/              # 거래일 캘린더, 모닝/마감 브리핑, 성적표
│   ├── core/                  # 환경 설정, 접근 제어, 런타임 시스템 제어
│   ├── handlers/              # 공통 텔레그램 명령어
│   ├── llm/                   # Ollama 번역·리서치 분석·브리핑 코멘트
│   ├── news/                  # 뉴스 소스 레지스트리, 가공, 전송 파이프라인
│   ├── research/              # 리서치 뉴스·후보군(섹터/问财)·명령 처리
│   ├── state/                 # 전송 기사 상태, 뉴스 감성 로그
│   ├── stocks/                # 종목 DB, 정량 시세 서비스
│   └── watchlist/             # 관심종목 저장, 이벤트 로그, 텔레그램 UI
├── data/                      # 런타임 상태와 캐시(Git 제외)
├── prompts/                   # 번역·리서치·검증·브리핑 프롬프트
├── tests/                     # 단위 테스트
├── Dockerfile                 # 봇 컨테이너 이미지
├── docker-compose.yml         # 봇 + Ollama (+옵션 RSSHub)
├── .env.example               # 환경 변수 예시
├── requirements.txt
└── README.md
```

## Docker로 실행

```bash
cp .env.example .env   # 토큰·채팅 ID 입력
docker compose up -d --build
docker compose exec ollama ollama pull gemma4:e4b
```

RSSHub까지 함께 띄우려면 `docker compose --profile rss up -d` 후
`NEWS_RSS_FEEDS=재련사RSS|http://rsshub:1200/cls/telegraph` 처럼 등록합니다.

## 운영 시 참고 사항

- 외부 뉴스 API, HKEX, EODHD, Ollama, Telegram 중 하나가 느리거나 중단되면 해당 작업만 로그에 실패로 기록되고 그 작업의 다음 실행에서 다시 진행됩니다.
- 스케줄 작업은 동시에 중복 실행되지 않으며, 이전 작업이 길어지면 누락된 실행은 합쳐집니다.
- `data/`를 삭제하면 관심종목, 중복 전송 이력, 리서치 상태, 런타임 GPU 설정이 초기화됩니다.
- `TELEGRAM_BOT_TOKEN`, `EODHD_API_TOKEN`, 실제 `.env` 파일은 커밋하지 마세요.
