# 실행 가이드

## 구성 요소

| 구성 요소 | 역할 |
|-----------|------|
| **FastAPI 웹앱** | REST API + 텔레그램 미니앱 프론트엔드 서빙 |
| **텔레그램 봇** | 명령어 처리 + 모닝/마감 브리핑 + 가격 알림 |
| **RSSHub** | 중국 금융 뉴스 RSS 피드 수집 서버 |
| **로컬 LLM (선택)** | 중국어→한국어 번역 (NLLB-200) |

---

## 1. 사전 준비

### 1-1. Python 환경

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 1-2. .env 파일 생성

```bash
cp .env.example .env
```

`.env` 필수 항목:

```env
TELEGRAM_BOT_TOKEN=<BotFather에서 발급받은 토큰>
TELEGRAM_OWNER_ID=<본인 텔레그램 숫자 ID>
WEBAPP_URL=<웹앱 외부 접근 URL, 예: https://xxxx.ngrok-free.app>
```

텔레그램 ID 확인: `@userinfobot` 에 /start 전송

---

## 2. RSSHub (뉴스 수집 서버)

뉴스 기능을 쓰려면 RSSHub가 먼저 실행되어 있어야 합니다.

### Docker로 실행 (권장)

```bash
docker run -d --name rsshub -p 1200:1200 diygod/rsshub:latest
```

### Docker Compose로 실행 (앱과 함께)

```bash
docker compose up -d rsshub
```

정상 동작 확인:

```
http://localhost:1200/healthz
```

---

## 3. FastAPI 웹앱

```bash
python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

- API 문서: `http://localhost:8000/docs`
- 미니앱 화면: `http://localhost:8000/index.html`
- 헬스체크: `http://localhost:8000/health`

텔레그램 미니앱은 HTTPS가 필요합니다. 로컬 개발 시 ngrok 사용:

```bash
ngrok http 8000
# 출력된 https://xxxx.ngrok-free.app 을 .env의 WEBAPP_URL에 설정
```

---

## 4. 텔레그램 봇

웹앱과 **별도 터미널**에서 실행합니다.

```bash
python -m src.bot.main
```

사용 가능한 명령어:

| 명령어 | 설명 |
|--------|------|
| `/start` | 미니앱 버튼 표시 |
| `/market` | 시장 현황 요약 |
| `/news` | 최신 뉴스 |
| `/alert` | 가격 알림 목록 |

스케줄러도 봇 프로세스 안에서 함께 실행됩니다:
- 매 15분: 시장 지수 캐시 갱신, 가격 알림 체크
- 매 30분: RSS 피드 갱신, 번역 잡
- 09:00: 모닝 브리핑 전송
- 15:30: 장 마감 요약 전송

---

## 5. 로컬 번역 (선택)

중국어 뉴스 제목을 한국어로 자동 번역합니다.
RTX 3060 laptop 기준 ~1.2 GB VRAM 사용.

### 활성화

`.env`에 추가:

```env
TRANSLATE_ENABLED=true
TRANSLATE_BACKEND=local
TRANSLATE_LOCAL_MODEL=facebook/nllb-200-distilled-600M
```

첫 실행 시 HuggingFace에서 모델 자동 다운로드 (~1.2 GB).
이후 `~/.cache/huggingface/` 에 캐싱되어 재다운로드 없음.

### Ollama 백엔드 (대안, 고품질)

Ollama 설치 후:

```bash
ollama pull qwen2.5:7b
```

`.env`:

```env
TRANSLATE_ENABLED=true
TRANSLATE_BACKEND=ollama
OLLAMA_BASE_URL=http://localhost:11434
TRANSLATE_MODEL=qwen2.5:7b
```

---

## 6. 전체 로컬 실행 순서

```
터미널 1: docker run -d --name rsshub -p 1200:1200 diygod/rsshub:latest
터미널 2: python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
터미널 3: python -m src.bot.main
(선택) ngrok http 8000
```

---

## 7. Docker Compose로 한번에 실행

앱 + RSSHub를 함께 띄우려면:

```bash
docker compose up -d
```

> 번역(LLM)은 Docker 외부(로컬 Python 또는 Ollama)에서 별도 실행해야 합니다.
> GPU 접근이 필요하기 때문입니다.

---

## 8. DB 초기화 / 마이그레이션

앱 첫 실행 시 `data/app.db` (SQLite)가 자동 생성됩니다.
별도 마이그레이션 명령 없이 바로 사용 가능합니다.

스키마를 직접 초기화하려면:

```bash
python -c "from src.db.session import create_tables; create_tables()"
```
