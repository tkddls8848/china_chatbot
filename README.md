# China Chatbot

중국·홍콩 증시 속보와 관심종목 뉴스를 수집하고, Ollama로 한국어 번역·분석해 텔레그램으로 전송하는 봇입니다.

## 주요 기능

- 푸투니우니우(富途牛牛, Futu) 전역 속보 수집
- 재련사(財联社, CLS) 전역 속보 수집(옵션, 현재 기본 비활성화)
- 관심종목별 최근 7일 뉴스 수집
- Ollama 기반 한국어 번역, 관련 종목 코드와 테마 후보 추출
- 리서치 주제와 최근 전역 뉴스를 바탕으로 관심종목 추가·삭제 후보 분석
- 텔레그램 버튼으로 리서치 결과를 확인한 뒤 관심종목에 적용
- A주·홍콩 종목 DB 생성 및 EODHD 시가총액·업종 보강
- 텔레그램 명령으로 Ollama GPU 오프로딩 설정 변경
- 전송 완료 기사 ID를 저장해 중복 전송 방지

## 동작 개요

봇은 시작 직후 뉴스 작업을 한 번 실행하고, 이후 `SCHEDULER_INTERVAL_MINUTES` 간격으로 반복합니다. 전역 뉴스 소스와 관심종목은 설정한 배치 크기만큼 회전 처리하므로, 관심종목이 많아도 매 주기에 모든 종목을 한꺼번에 조회하지 않습니다.

| 구분 | 현재 동작 |
|---|---|
| Futu 속보 | 기본 활성화, 주기당 최근 `NEWS_GLOBAL_LIMIT`건 확인 |
| CLS 속보 | `NEWS_ENABLE_CLS=true`일 때만 활성화 |
| 관심종목 뉴스 | 종목별 최근 7일 뉴스 중 최대 `NEWS_STOCK_LIMIT_PER_SYMBOL`건 확인 |
| 번역 실패 | 해당 기사를 전송하지 않고 다음 주기에 다시 시도 |
| 중복 방지 | 전송 성공 기사만 `data/sent_ids.json`에 기록 |
| 종목 DB | 시작 시 캐시를 읽고, 없으면 생성. 매일 호스트 현지 시각 08:30에 갱신 |

> 현재 AkShare의 CLS 엔드포인트가 HTTP 404를 반환하는 상황을 고려해 `NEWS_ENABLE_CLS=false`가 기본값입니다. 엔드포인트가 정상화되면 직접 활성화하세요.

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
| `NEWS_ENABLE_CLS` | `false` | CLS 수집 활성화 여부 |
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
| `/stockdb build` | 종목 코드·이름 DB 갱신 |
| `/stockdb enrich` | EODHD로 시가총액·업종 보강 |
| `/system` | 현재 GPU 오프로딩 상태 표시 |
| `/system gpu on` | GPU 자동 오프로딩 활성화 |
| `/system gpu off` | CPU 전용으로 전환 |
| `/system gpu <레이어수>` | GPU 오프로딩 레이어 수 직접 지정 |

`/research run`은 현재 활성화된 CLS/Futu 전역 뉴스, 리서치 주제, 현재 관심종목, 종목 DB 후보군을 Ollama에 전달합니다. 결과는 즉시 관심종목을 바꾸지 않으며, 텔레그램의 **적용** 버튼을 눌러야 추가·삭제가 반영됩니다.

> 현재 명령어 발신자나 채팅방을 제한하는 접근제어는 구현되어 있지 않습니다. 봇 토큰을 공개하지 말고, 외부 사용자가 봇을 찾거나 대화를 시작할 수 있는 배포 환경에서는 핸들러에 허용 사용자/채팅 검증을 추가하세요.

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
| `data/sent_ids.json` | 중복 전송 방지용 기사 ID와 전송 시각 |
| `data/stock_db.json` | 종목 코드·이름·시장·보강 데이터 캐시 |
| `data/market_research.json` | 리서치 주제와 최근 분석 결과 |
| `data/runtime_config.json` | 텔레그램에서 변경한 GPU 설정 |
| `data/bot.lock` | 단일 인스턴스 실행 잠금 |

`data/runtime_config.json`의 값은 `.env`의 `OLLAMA_NUM_GPU`보다 우선하며 재시작 후에도 유지됩니다. 초기값으로 되돌리려면 봇을 종료한 상태에서 해당 파일을 삭제한 뒤 다시 실행하세요.

## 프로젝트 구조

```text
china_chatbot/
├── app/
│   ├── bot.py                 # 서비스 구성, 핸들러 등록, 스케줄러
│   ├── core/                  # 환경 설정과 런타임 시스템 제어
│   ├── handlers/              # 공통 텔레그램 명령어
│   ├── llm/                   # Ollama 번역과 리서치 분석
│   ├── news/                  # 뉴스 소스, 가공, 전송 파이프라인
│   ├── research/              # 리서치 뉴스·후보군·명령 처리
│   ├── state/                 # 전송 기사 상태 관리
│   ├── stocks/                # 종목 DB 생성·조회·보강
│   └── watchlist/             # 관심종목 저장과 텔레그램 UI
├── data/                      # 런타임 상태와 캐시(Git 제외)
├── prompts/                   # 번역·리서치 프롬프트
├── .env.example               # 환경 변수 예시
├── requirements.txt
└── README.md
```

## 운영 시 참고 사항

- 외부 뉴스 API, HKEX, EODHD, Ollama, Telegram 중 하나가 느리거나 중단되면 해당 작업만 로그에 실패로 기록되고 그 작업의 다음 실행에서 다시 진행됩니다.
- 스케줄 작업은 동시에 중복 실행되지 않으며, 이전 작업이 길어지면 누락된 실행은 합쳐집니다.
- `data/`를 삭제하면 관심종목, 중복 전송 이력, 리서치 상태, 런타임 GPU 설정이 초기화됩니다.
- `TELEGRAM_BOT_TOKEN`, `EODHD_API_TOKEN`, 실제 `.env` 파일은 커밋하지 마세요.
