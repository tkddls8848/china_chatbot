# AWS EC2 배포 가이드

텔레그램 봇과 관리 웹을 AWS EC2 한 대에 올려 상시 운영하기 위한 절차다.

## 0. 구조 요약

배포 대상은 프로세스 **하나**다. 관리 웹(`app/webadmin`)은 별도 서버가 아니라
봇과 같은 asyncio 이벤트 루프에 uvicorn을 얹는 구조이므로, systemd 유닛도
`python app/bot.py` 하나만 만들면 된다.

```
EC2 (Ubuntu 24.04)
├── systemd: china-chatbot.service   → app/bot.py (봇 + 관리 웹 :8787)
├── systemd: ollama.service          → 번역·리서치 LLM (:11434)
├── nginx                            → 443 → 127.0.0.1:8787 (관리 웹 노출 시에만)
└── data/                            → 상태 JSON 전부 (EBS 스냅샷으로 백업)
```

봇은 `data/runtime/bot.lock`에 파일 락을 잡아 중복 기동을 막는다(Linux는 `flock`).
따라서 배포 중 구버전이 살아 있으면 신버전이 즉시 종료되므로, 재시작은 항상
`systemctl restart`로 교체한다.

## 1. 인스턴스 선택

사이징을 결정하는 것은 봇 자체가 아니라 **Ollama의 CPU 추론**이다. 봇 프로세스만
보면 1GB 미만이지만, `qwen3.5:4b`를 4bit로 올리면 3GB 안팎을 상주로 먹는다.

| 용도 | 인스턴스 | 비고 |
|---|---|---|
| 권장 기본값 | `t3.large` (2vCPU/8GB) | 4B 모델 CPU 추론 + 봇이 무리 없이 공존 |
| 최소 | `t3.medium` (2vCPU/4GB) | 리서치 분석 동시 실행 시 OOM 위험 |
| 번역·리서치 끄고 수집만 | `t3.small` | `TRANSLATION_ENABLED=false`, `RESEARCH_ANALYSIS_ENABLED=false` |
| LLM 응답 속도 중시 | `g5.xlarge` | GPU. 비용이 10배 이상이라 상시 운영엔 비권장 |

- **스토리지**: gp3 30GB. 뉴스 로그와 yfinance 캐시가 누적되지만
  `NEWS_LOG_RETENTION_DAYS`로 정리되므로 여유롭다.
- **T 계열 크레딧**: 리서치 분석이 CPU를 길게 점유해 크레딧을 소진할 수 있다.
  Unlimited 모드를 켜두거나(기본값), 청구서가 튀면 `RESEARCH_MAX_CANDIDATES`와
  `NON_URGENT_WORKER_COUNT`를 낮춘다.

### 리전 선택 — 중국 데이터 소스와 직결된다

동방재부(Eastmoney) 계열 API는 해외 IP에서 차단·스로틀링된다. 그래서
`.env.example`도 `QUANT_HOT_RANK_ENABLED=false`가 기본이다. AWS 어느 리전에
띄우든 이 제약은 동일하니, **인기순위 등 동방재부 의존 기능은 계속 끈 채로 둔다.**

- 권장: `ap-northeast-2` (서울) — 한국 뉴스 소스와 지연이 낮고 TZ가 맞다.
- `cn-north-1` 등 중국 리전은 별도 계정과 ICP 등록이 필요해 현실적이지 않다.

### 보안 그룹

| 포트 | 소스 | 용도 |
|---|---|---|
| 22 | 본인 IP만 | SSH |
| 443 | 본인 IP 또는 0.0.0.0/0 | 관리 웹 (nginx 경유, 노출할 때만) |

**8787은 절대 열지 않는다.** 관리 웹은 봇을 제어하므로 반드시 nginx TLS 뒤에
두거나, 아예 열지 말고 SSH 터널로만 접근한다(5절).

텔레그램 봇은 폴링 방식(`run_polling`)이라 인바운드 포트가 필요 없다.

## 2. 기본 환경 구성

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-pip git nginx

# 브리핑 스케줄이 시스템 로컬 시각을 따르므로 반드시 맞춘다.
sudo timedatectl set-timezone Asia/Seoul
```

> **TZ가 중요한 이유**: `BRIEFING_MORNING_HOUR=8` 같은 설정은 APScheduler cron에
> 타임존 없이 전달되어 **시스템 로컬 시각**으로 해석된다. EC2 기본값인 UTC로 두면
> 조간 브리핑이 한국시간 17시에 나간다.

전용 사용자로 돌린다.

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin chatbot
```

## 3. 애플리케이션 배치

```bash
sudo -u chatbot -H bash
cd /home/chatbot
git clone <저장소 URL> china_chatbot
cd china_chatbot

python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
```

matplotlib이 차트를 그리므로 헤드리스 백엔드가 필요할 수 있다. 차트 생성 시
에러가 나면 서비스 환경변수에 `MPLBACKEND=Agg`를 추가한다.

### .env 작성

```bash
cp .env.example .env
chmod 600 .env          # 토큰과 관리 웹 비밀번호가 들어간다
nano .env
```

로컬 개발과 달라지는 값만 정리하면:

```env
TELEGRAM_BOT_TOKEN=<BotFather 토큰>
TELEGRAM_CHAT_ID=<알림 채팅 ID>
ALLOWED_CHAT_IDS=<허용할 채팅 ID 목록>   # 공개 배포 시 반드시 지정

OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_NUM_GPU=0                        # CPU 인스턴스면 0 유지

WEB_ADMIN_HOST=127.0.0.1                # nginx가 앞단이므로 그대로 둔다
WEB_ADMIN_PORT=8787
WEB_ADMIN_USER=admin
WEB_ADMIN_PASSWORD=<긴 무작위 문자열>    # 비우면 관리 웹이 아예 안 뜬다

QUANT_HOT_RANK_ENABLED=false            # 해외 IP 차단. 그대로 둔다
```

`ALLOWED_CHAT_IDS`를 비워두면 봇을 아는 누구나 명령을 쓸 수 있다. 배포 환경에서는
반드시 채운다.

### Ollama 설치와 모델 준비

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3.5:4b        # TRANSLATION_MODEL / RESEARCH_ANALYSIS_MODEL
```

설치 스크립트가 `ollama.service`를 등록하고 부팅 시 자동 기동하게 만든다.
기본 바인딩은 `127.0.0.1:11434`이며, **외부에 노출하지 않는다.**

### 병렬 슬롯 설정 (중요)

봇은 주기 뉴스 번역(긴급)과 리서치 분석(비긴급)을 **서로 다른 스레드**에서 돌려
번역이 방해받지 않게 한다(`app/core/workers.py`). 그러나 두 경로 모두 같은
`/api/chat` 엔드포인트를 치고, **Ollama는 기본적으로 요청을 직렬 처리**한다.
따라서 슬롯을 열어주지 않으면 스레드를 나눈 의미가 사라진다 — 리서치 분석
(`RESEARCH_ANALYSIS_TIMEOUT=600`)이 진행 중이면 뒤에 온 번역 요청이 큐에서
대기하다 `TRANSLATION_TIMEOUT=120`에 걸려 실패한다.

```bash
sudo systemctl edit ollama
```

```ini
[Service]
Environment="OLLAMA_NUM_PARALLEL=2"
Environment="OLLAMA_KEEP_ALIVE=5m"
```

```bash
sudo systemctl restart ollama
```

슬롯 2개를 **번역 1 + 리서치 1**로 나누는 구성이다. 애플리케이션 쪽 동시성이
이미 여기에 맞춰져 있다 — `TRANSLATION_CONCURRENCY=1`이고, 리서치는
`app/research/handlers.py:23`의 `max_workers=1` 실행기로 직렬화된다. 따라서 두
경로가 각자 슬롯 하나씩만 점유하며, 서로를 밀어내지 않는다.

> `OLLAMA_NUM_PARALLEL`은 **Ollama 서버 프로세스**가 읽는 환경변수다. `.env`에
> 적으면 봇 프로세스의 환경에만 로드되어 아무 효과가 없다. 반드시 위처럼
> systemd 유닛(로컬 개발이라면 Ollama를 띄우는 셸/서비스)에 설정한다.

**메모리 주의**: Ollama는 슬롯 수만큼 KV 캐시를 잡는다. 실질 컨텍스트가
`num_ctx × 2`가 되므로, `RESEARCH_CTX_MAX=24576`을 그대로 두면 t3.large(8GB)에서
빠듯하다. 8GB 인스턴스라면 `.env`에서 `RESEARCH_CTX_MAX=12288` 정도로 낮추고
`journalctl -u ollama`에 OOM이나 컨텍스트 축소 경고가 없는지 확인한다.

메모리를 더 아껴야 하면 `OLLAMA_NUM_PARALLEL=1`로 되돌리고, 대신 리서치 스케줄을
뉴스 수집 주기와 겹치지 않게 옮기는 편이 안전하다.

## 4. systemd 서비스 등록

`/etc/systemd/system/china-chatbot.service`:

```ini
[Unit]
Description=China Chatbot (Telegram bot + web admin)
After=network-online.target ollama.service
Wants=network-online.target

[Service]
Type=simple
User=chatbot
WorkingDirectory=/home/chatbot/china_chatbot/app
Environment=PYTHONUNBUFFERED=1
Environment=MPLBACKEND=Agg
ExecStart=/home/chatbot/china_chatbot/venv/bin/python bot.py
Restart=always
RestartSec=10

# 파일 쓰기는 data/ 와 임시 디렉토리로 제한
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=/home/chatbot/china_chatbot/data

[Install]
WantedBy=multi-user.target
```

`WorkingDirectory`가 `app/`인 것이 중요하다. 코드가 `from core.config import ...`
처럼 `app/`을 루트로 임포트하므로, 상위에서 실행하면 임포트가 깨진다.
`.env`와 `data/`는 프로젝트 루트 기준으로 해석된다.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now china-chatbot
sudo systemctl status china-chatbot
journalctl -u china-chatbot -f
```

기동 로그에 `봇 시작됨. 활성 기능: ...`이 찍히면 정상이다.

## 5. 관리 웹 접근

### 방법 A — SSH 터널 (권장, 추가 설정 없음)

관리 웹을 인터넷에 아예 노출하지 않는다. 로컬에서:

```bash
ssh -L 8787:127.0.0.1:8787 ubuntu@<EC2 퍼블릭 IP>
```

브라우저에서 `http://127.0.0.1:8787`로 접속한다. 보안 그룹에 443을 열 필요도,
인증서를 발급할 필요도 없다. 혼자 운영한다면 이 방법으로 충분하다.

### 방법 B — nginx + Let's Encrypt

여러 명이 쓰거나 모바일에서 접근해야 하면 도메인을 붙인다.

```bash
sudo apt install -y certbot python3-certbot-nginx
```

`/etc/nginx/sites-available/china-chatbot`:

```nginx
server {
    listen 80;
    server_name admin.example.com;

    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/china-chatbot /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d admin.example.com
```

certbot이 80 → 443 리다이렉트까지 잡아준다. 관리 웹 자체 인증은 HTTP Basic이라
**TLS 없이 노출하면 비밀번호가 평문으로 흐른다.** 반드시 인증서를 붙인 뒤 연다.

## 6. 운영

### 배포 갱신

```bash
sudo -u chatbot -H git -C /home/chatbot/china_chatbot pull
sudo -u chatbot -H /home/chatbot/china_chatbot/venv/bin/pip \
     install -r /home/chatbot/china_chatbot/requirements.txt
sudo systemctl restart china-chatbot
```

`requirements.txt`가 안 바뀌었으면 pip 단계는 건너뛴다.

### 상태 확인

- 텔레그램에서 `/system` — 기능별 활성 여부와 스케줄러 상태
- `journalctl -u china-chatbot -n 200 --no-pager`
- `journalctl -u ollama -n 100 --no-pager` — 번역이 조용히 실패할 때

### 백업

상태는 전부 `data/` 하위 JSON/JSONL이고 DB가 없다. 두 가지 중 택일한다.

- **EBS 스냅샷** (권장): Data Lifecycle Manager로 일 1회 자동 스냅샷.
- **S3 동기화**: 세밀한 복구가 필요하면 cron으로

  ```bash
  aws s3 sync /home/chatbot/china_chatbot/data \
      s3://<버킷>/china-chatbot/data --delete
  ```

  인스턴스에 S3 쓰기 권한 IAM 역할을 붙인다(액세스 키를 파일로 두지 않는다).

관심 종목(`data/watchlist/`)과 리서치 상태(`data/research/`)가 재구축 비용이 가장
크다. 뉴스 로그와 종목 DB는 유실돼도 재수집된다.

### 비용 개략 (ap-northeast-2, 온디맨드)

| 항목 | 월 |
|---|---|
| t3.large | 약 $70 |
| gp3 30GB | 약 $3 |
| 탄력적 IP (연결 상태) | $0 |

1년 이상 운영이 확실하면 Savings Plan으로 40% 가까이 줄어든다. 비용이 부담되면
LLM을 Ollama 대신 API로 빼고 `t3.small`로 내리는 편이 훨씬 크게 절감된다.

## 7. 문제 해결

| 증상 | 원인과 조치 |
|---|---|
| 기동 직후 바로 종료 | 다른 인스턴스가 `data/runtime/bot.lock`을 점유. `systemctl status`로 중복 프로세스 확인 |
| 브리핑이 엉뚱한 시각에 발송 | 시스템 TZ가 UTC. `timedatectl set-timezone Asia/Seoul` 후 재시작 |
| 번역·리서치가 조용히 비활성 | Ollama 미기동 또는 모델 미다운로드. `ollama list`로 확인 |
| 관리 웹이 안 뜸 | `WEB_ADMIN_PASSWORD`가 비어 있으면 기능이 켜져 있어도 건너뛴다 |
| 차트 명령에서 에러 | matplotlib 백엔드. 서비스에 `MPLBACKEND=Agg` 추가 |
| 중국 뉴스·시세만 실패 | 해외 IP 차단. 동방재부 의존 옵션이 켜졌는지 확인 |
| 리서치 중 OOM으로 재시작 반복 | 메모리 부족. 인스턴스 상향 또는 `RESEARCH_MAX_CANDIDATES` 축소 |

임포트 에러(`ModuleNotFoundError: core`)가 나면 대부분 `WorkingDirectory`가
`app/`이 아닌 경우다.
