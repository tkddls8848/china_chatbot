# China Chatbot

중국·홍콩 증시 뉴스를 한국어로 번역해 텔레그램으로 자동 전송하는 봇입니다.

## 기능

| 소스 | 내용 | 주기 |
|------|------|------|
| 재련사(財联社, CLS) | 신규 금융 속보 확인 (최대 10건 훑기) | 5분 |
| 푸투니우니우(富途牛牛, Futu) | 신규 홍콩중국 증시 속보 확인 (최대 10건 훑기) | 5분 |
| 관심종목 뉴스 | 지정 종목 신규 뉴스 확인 (종목별 최대 5건 훑기) | 5분 |

## 설치

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 환경 설정

`.env` 파일을 프로젝트 루트에 생성하고 아래 값을 채웁니다.

```env
BOT_TOKEN=<텔레그램 봇 토큰>
CHAT_ID=<전송할 채널 또는 채팅방 ID>

TRANSLATE_ENABLED=true
OLLAMA_BASE_URL=http://localhost:11434
TRANSLATE_MODEL=gemma4:e4b
TRANSLATE_TIMEOUT=60
TRANSLATE_PROMPT_DIR=prompts
TRANSLATE_CONCURRENCY=1
CLS_FUTU_NEWS_LIMIT=10
STOCK_NEWS_LIMIT=5
SCHEDULE_INTERVAL_MINUTES=5
MAX_SENT_IDS=0
```

`CLS_FUTU_NEWS_LIMIT`와 `STOCK_NEWS_LIMIT`는 주기마다 반드시 보내는 기사 수가 아니라 신규 기사 확인 범위의 최대값입니다. 이미 보낸 기사는 `data/sent_ids.json` 기준으로 건너뛰며, 신규 기사가 부족하면 적게 보내거나 보내지 않습니다. `MAX_SENT_IDS=0`은 중복 방지용 기사 ID를 계속 보관한다는 뜻입니다.

봇 토큰은 [@BotFather](https://t.me/BotFather), 채팅방 ID는 [@userinfobot](https://t.me/userinfobot)에서 확인할 수 있습니다.

## Ollama 번역

봇은 Ollama의 `gemma4` 모델을 호출해 중국어 뉴스를 한국어로 번역합니다.

```bash
ollama pull gemma4
ollama serve
```

`TRANSLATE_ENABLED=false`로 설정하면 번역하지 않고 중국어 원문을 전송합니다. `TRANSLATE_ENABLED=true`이면 Ollama 호출, JSON 파싱, 타임아웃 실패 시 원문을 전송하지 않고 다음 주기에 재시도합니다.

프롬프트는 `prompts/` 아래 텍스트 파일로 관리합니다. 프롬프트를 수정한 뒤에는 봇을 재시작해야 합니다.

## 실행

```bash
python app\bot.py
```

시작 즉시 1회 실행 후 5분마다 반복합니다.

## 관심종목 설정

관심종목은 `data/watchlist.json`에 저장되며 텔레그램 명령어로 관리합니다.

```text
/add 300750
/list
/menu
```

- 홍콩 종목: 5자리 코드 (예: `09988`)
- 상하이 A주: 6자리 `6`으로 시작 (예: `600519`)
- 심천 A주: 6자리 `0` 또는 `3`으로 시작 (예: `300750`)

`/add`는 종목코드만 입력받고, 종목명은 AkShare로 자동 조회합니다. 삭제는 `/menu`에서 종목 버튼을 눌러 처리합니다.

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
| hanja | 영문명이 없는 중국어 종목명의 한국식 한자음 변환 |
| opencc-python-reimplemented | 간체 종목명을 번체로 변환해 한자음 변환 품질 보강 |
| apscheduler | 주기적 스케줄링 |
| python-dotenv | `.env` 파일 로드 |
| requests | Ollama HTTP API 호출 |
| tenacity | AkShare 네트워크 재시도 |
