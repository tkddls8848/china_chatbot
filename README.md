# China Chatbot

중국·홍콩 증시 뉴스를 한국어로 번역해 텔레그램으로 자동 전송하는 봇입니다.

## 기능

| 소스 | 내용 | 주기 |
|------|------|------|
| 재련사(財联社, CLS) | 신규 금융 속보 확인 (최대 3건 훑기) | 5분 |
| 푸투니우니우(富途牛牛, Futu) | 신규 홍콩중국 증시 속보 확인 (최대 3건 훑기) | 5분 |
| 관심종목 뉴스 | 지정 종목 신규 뉴스 확인 (종목별 최대 3건 훑기) | 5분 |

## 설치

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 환경 설정

`.env` 파일을 프로젝트 루트에 생성하고 아래 값을 채웁니다.

```env
TELEGRAM_BOT_TOKEN=<텔레그램 봇 토큰>
TELEGRAM_CHAT_ID=<전송할 채널 또는 채팅방 ID>

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_NUM_GPU=0

TRANSLATION_ENABLED=true
TRANSLATION_MODEL=gemma4:e4b
TRANSLATION_TIMEOUT=60
TRANSLATION_NUM_PREDICT=4096
TRANSLATION_PROMPT_DIR=prompts
TRANSLATION_CONCURRENCY=1

NEWS_GLOBAL_LIMIT=3
NEWS_STOCK_LIMIT_PER_SYMBOL=3
SCHEDULER_INTERVAL_MINUTES=5
SENT_NEWS_MAX_IDS=0

STOCK_DB_ENABLED=true

RESEARCH_ANALYSIS_ENABLED=true
RESEARCH_ANALYSIS_MODEL=gemma4:e4b
RESEARCH_ANALYSIS_TIMEOUT=180
RESEARCH_ANALYSIS_NUM_PREDICT=1024
RESEARCH_NEWS_STOCK_LIMIT_PER_SYMBOL=3
RESEARCH_NEWS_MAX_ITEMS=3
RESEARCH_NEWS_GLOBAL_LIMIT=3
```

`NEWS_GLOBAL_LIMIT`와 `NEWS_STOCK_LIMIT_PER_SYMBOL`은 주기마다 반드시 보내는 기사 수가 아니라 신규 기사 확인 범위의 최대값입니다. 이미 보낸 기사는 `data/sent_ids.json` 기준으로 건너뛰며, 신규 기사가 부족하면 적게 보내거나 보내지 않습니다. `SENT_NEWS_MAX_IDS=0`은 중복 방지용 기사 ID를 계속 보관한다는 뜻입니다.

봇 토큰은 [@BotFather](https://t.me/BotFather), 채팅방 ID는 [@userinfobot](https://t.me/userinfobot)에서 확인할 수 있습니다.

## Ollama 번역

봇은 Ollama의 `gemma4` 모델을 호출해 중국어 뉴스를 한국어로 번역합니다.

```bash
ollama pull gemma4
ollama serve
```

`TRANSLATION_ENABLED=false`로 설정하면 번역하지 않고 중국어 원문을 전송합니다. `TRANSLATION_ENABLED=true`이면 Ollama 호출, JSON 파싱, 타임아웃 실패 시 원문을 전송하지 않고 다음 주기에 재시도합니다.

프롬프트는 `prompts/` 아래 텍스트 파일로 관리합니다. 프롬프트를 수정한 뒤에는 봇을 재시작해야 합니다.

## 실행

```bash
python app\bot.py
```

시작 즉시 1회 실행 후 5분마다 반복합니다.

## 관심종목 설정

관심종목은 `data/watchlist.json`에 저장되며 텔레그램 명령어로 관리합니다.

```text
/add 600519
/list
/menu
```

- 홍콩 종목: 5자리 코드 (예: `09988`)
- 상하이 A주: 6자리 `6`으로 시작 (예: `600519`)
- 심천 A주: 외국인 개인 거래 가능 목록에 포함된 6자리 `0`으로 시작하는 코드

`stock_db.json`은 AkShare 종목명 데이터에 HKEX Northbound Stock Connect 매수/매도 가능 목록을 결합해 생성합니다. ChiNext(`300`, `301`)와 STAR Market(`688`, `689`)처럼 기관 전문투자자 대상인 A주는 관련종목 후보와 `/add`에서 제외합니다. 종목 데이터는 원본명 `cn_name`, 한국 한자음 변환명 `ko_name`, 시스템 표시명 `display_name`으로 저장하며, `display_name`은 `ko_name`을 사용합니다.

`/add`는 종목코드만 입력받고, 종목명은 필터링된 `stock_db.json`에서 조회합니다. 삭제는 `/menu`에서 종목 버튼을 눌러 처리합니다.

## 파일 구조

```text
china_chatbot/
├── app/
│   ├── bot.py             # 메인 봇 로직
│   └── translator.py      # Ollama 번역 처리
├── data/
│   ├── sent_ids.json      # 중복 전송 방지용 기사 ID
│   └── watchlist.json     # 관심종목 목록
├── docs/
│   └── translation_plan.md
├── prompts/
│   ├── cls_ko.txt
│   ├── futu_ko.txt
│   └── stock_ko.txt
├── .env
├── .env.example
├── requirements.txt
└── README.md
```

## 의존성

| 패키지 | 용도 |
|--------|------|
| python-telegram-bot | 텔레그램 봇 API |
| akshare | 중국 금융 데이터 |
| pandas | HKEX 가능 종목 XLS 파싱 |
| hanja | 중국어 종목명의 한국식 한자음 변환 |
| opencc-python-reimplemented | 간체 종목명을 번체로 변환해 한자음 변환 품질 보강 |
| apscheduler | 주기적 스케줄링 |
| python-dotenv | `.env` 파일 로드 |
| requests | Ollama HTTP API 호출 |
| tenacity | AkShare 네트워크 재시도 |
