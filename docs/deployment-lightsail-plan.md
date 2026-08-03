# Lightsail 배포 실행 계획

- 작성일: 2026-08-02
- 대상: `china_chatbot` 텔레그램 봇 (LLM은 Cloudflare Workers AI 원격)
- 이 문서 하나로 배포가 끝나도록 명령까지 포함한다.
- **Phase 1~2(인스턴스 생성·애플리케이션 설치)는 `iac/terraform/`에 코드화되어 있다.**
  `terraform apply` 한 번으로 인스턴스·고정 IP·방화벽 생성과 스왑·타임존·venv·systemd
  유닛·백업 cron 설치까지 끝난다. 이 문서는 그 코드의 **판단 근거**와, 코드가 대신할 수
  없는 Phase 0(코드 확정)·3(설정과 데이터 이관)·4(전환)·5(검증)를 담당한다.

## 0. 지금 상태에서의 블로커

**착수 전에 반드시 해소해야 하는 것 세 가지다.**

| # | 블로커 | 현재 | 조치 |
|---|---|---|---|
| B1 | **작업이 전부 미커밋** | 변경 48개 파일, 원격보다 앞선 커밋 0 | 커밋·푸시 먼저. 안 하면 서버가 **Ollama 시절 코드**를 받는다 |
| B2 | **텔레그램 토큰 중복 폴링** | 로컬 봇이 같은 토큰으로 폴링 중 | 서버 기동 전에 로컬 봇 정지 |
| B3 | 관리 웹 비밀번호 | `WEB_ADMIN_PASSWORD=password` | 서버 `.env`에 긴 무작위 문자열로 설정 |

> **B2가 가장 사고나기 쉽다.** `data/runtime/bot.lock`은 **머신 단위**라 다른 호스트의
> 중복 기동을 막지 못한다. 같은 봇 토큰으로 두 프로세스가 `getUpdates`를 치면 텔레그램이
> `Conflict: terminated by other getUpdates request`를 반환하고 **양쪽이 번갈아 죽는다.**
> 전환은 반드시 "로컬 정지 → 서버 기동" 순서로 한다.

## 1. 인스턴스 사양 결정

| 항목 | 선택 | 근거 |
|---|---|---|
| 서비스 | Lightsail **Instance** (Containers 아님) | Containers는 영속 디스크가 없어 `data/`가 사라진다 |
| 플랜 | **$7/월** (1GB / 2vCPU / 40GB SSD / 2TB) | $5(0.5GB)는 pandas 임포트 피크를 못 버틴다 |
| 블루프린트 | **Ubuntu 24.04 LTS** (OS Only) | Python 3.12 기본. 코드에 3.13 전용 문법 없음(확인 완료) |
| 리전 | **ap-northeast-2 (서울)** | KST 기준 스케줄, 한국·중국 소스와 지연 낮음 |
| 고정 IP | 연결 | 인스턴스에 붙어 있는 동안 무료. 재부팅해도 SSH 주소 유지 |
| 방화벽 | **SSH 22만** | 8787은 절대 열지 않는다. 관리 웹은 SSH 터널로 접근 |

## 2. 단계별 실행

### Phase 0 — 코드 확정 (로컬)

1. 전체 테스트 통과 확인: `python -m pytest -q`
2. 실계정 스모크 1회: `RUN_CLOUDFLARE_SMOKE=1 python -m pytest -q -m cloudflare_smoke`
3. 커밋·푸시 (`.env`는 `.gitignore` 대상이므로 올라가지 않는다)

**통과 기준**: `git status --short`가 비어 있고, `git rev-list --count origin/main..HEAD == 0`

### Phase 1 — 인스턴스 생성

1절 표대로 생성 → 고정 IP 연결 → SSH 접속 확인
`sudo timedatectl set-timezone Asia/Seoul`

**통과 기준**: `date`가 KST를 반환한다. TZ가 UTC면 브리핑이 9시간 어긋난다.

### Phase 2 — 애플리케이션 설치

1GB이므로 **스왑을 먼저 잡는다.** pip 설치 중 OOM이 가장 흔한 실패 지점이다.

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git
git clone https://github.com/tkddls8848/china_chatbot.git ~/china_chatbot
cd ~/china_chatbot && python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
```

**통과 기준**: 서버에서 `./venv/bin/python -m pytest -q`가 로컬과 같은 결과를 낸다.
여기서 깨지면 Python 3.12 비호환이므로 3.13을 따로 올린다(deadsnakes PPA).

### Phase 3 — 설정과 데이터 이관

`.env`는 **손으로 만든다**(커밋되지 않으므로). 로컬 값을 옮기되 두 곳만 바꾼다.

```env
WEB_ADMIN_PASSWORD=<긴 무작위 문자열>     # 'password' 금지
ALLOWED_CHAT_IDS=<본인 chat_id>          # 비우면 아무나 명령 가능
```

재구축 비용이 큰 상태만 옮긴다.

```bash
# 로컬(PowerShell)에서
scp -r data/watchlist data/research data/news ubuntu@<고정IP>:~/china_chatbot/data/
```

- `data/instruments`(5.4MB)는 옮기지 않아도 `/stockdb build`로 재생성된다
- `data/runtime/bot.lock`은 **옮기지 않는다**

**통과 기준**: `./venv/bin/python -c "import sys; sys.path.insert(0,'app'); import core.config"`가
`ConfigurationError` 없이 끝난다(= Cloudflare 자격증명이 채워졌다).

### Phase 4 — 전환 (다운타임 구간)

**순서를 지킨다.**

1. **로컬 봇 정지** (B2)
2. 서버에서 systemd 유닛 등록 후 `sudo systemctl enable --now china-chatbot`
3. `journalctl -u china-chatbot -f`로 기동 로그 확인

`/etc/systemd/system/china-chatbot.service`:

```ini
[Unit]
Description=China Chatbot (Telegram)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/china_chatbot/app
Environment=PYTHONUNBUFFERED=1
Environment=MPLBACKEND=Agg
ExecStart=/home/ubuntu/china_chatbot/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

두 줄이 함정이다. `WorkingDirectory`가 `app/`이 아니면 `ModuleNotFoundError: core`가
나고(코드가 `app/`을 import 루트로 쓴다), `MPLBACKEND=Agg`가 없으면 `/market` 차트가
헤드리스 환경에서 실패한다.

### Phase 5 — 검증

| 확인 | 방법 | 기대 |
|---|---|---|
| 기동 | `journalctl -u china-chatbot` | `봇 시작됨. 활성 기능: ...` |
| LLM 연결 | `journalctl \| grep '\[LLM\]'` | `result=success`, `neurons=` 값이 찍힘 |
| 회로 | `grep circuit_open` | 아무것도 안 나와야 정상 |
| 명령 | 텔레그램에서 `/system` | 상태 응답 |
| 뉴스 주기 | 10분 대기 | 다이제스트 수신 또는 `기사 준비: ...` 로그 |
| 브리핑 | `/briefing morning` | 수동 실행 성공 |
| 차트 | `/market` | 이미지 수신 (matplotlib·MPLBACKEND 확인) |
| 관리 웹 | `ssh -L 8787:127.0.0.1:8787 ...` | 브라우저에서 대시보드 |

**24시간 후**: `journalctl | grep -o 'neurons=[0-9.]*'`를 합산해 일일 소모를 확인한다.
예상 약 2,600(무료 한도 10,000의 26%). 5,000을 넘으면 `.env`의 뉴스 상한을 조정한다.

## 3. 롤백

| 상황 | 조치 |
|---|---|
| 기동 실패·오작동 | `sudo systemctl stop china-chatbot` → 로컬 봇 재기동 (즉시 복구) |
| 데이터 손상 | Lightsail 스냅샷에서 복원 |
| 코드 회귀 | 서버에서 `git checkout <직전 커밋>` 후 재시작 |

Phase 4 직전에 **수동 스냅샷을 하나 찍어둔다.** 되돌릴 지점이 생긴다.

## 4. 운영 인계

**백업** — 상태는 전부 `data/` 하위 JSON이고 DB가 없다. `crontab -e`:

```bash
0 3 * * * tar czf ~/backup-$(date +\%F).tgz -C ~/china_chatbot data && find ~ -name 'backup-*.tgz' -mtime +14 -delete
```

**갱신** — `git pull` → (requirements 변경 시) `./venv/bin/pip install -r requirements.txt`
→ `sudo systemctl restart china-chatbot`

**관리 웹 접근** — 포트를 열지 않고 SSH 터널로만 본다.

```bash
ssh -L 8787:127.0.0.1:8787 ubuntu@<고정IP>
# 브라우저에서 http://127.0.0.1:8787
```

**점검** — 주 1회 `journalctl -u china-chatbot | grep -c 'result=success'`로 실패율 확인

## 5. 비용

| 항목 | 월 |
|---|---|
| Lightsail $7 플랜 | $7 |
| 고정 IP (인스턴스에 연결된 상태) | $0 |
| 스냅샷 (사용 용량 $0.05/GB) | 약 $0.3~0.5 |
| Cloudflare Workers AI | **$0** (무료 한도의 26% 사용) |
| **합계** | **약 $7.5/월** |

### 정지해도 과금은 멈추지 않는다

EC2와 다른 지점이라 반드시 알아야 한다. AWS 공식 FAQ 표현:

> "Your Lightsail instances are charged only when they're in the **running or stopped** state."

즉 **인스턴스를 stop 해도 플랜 요금은 그대로 나간다.** 리소스가 예약된 채로 유지되기
때문이다. 과금을 실제로 멈추려면 **삭제**해야 하고, 삭제하면 그 달은 사용 시간만큼만
일할 계산된다.

**일시 중단하는 올바른 순서:**

1. 스냅샷 생성 (상태 보존)
2. 인스턴스 **삭제**
3. **고정 IP 해제** — 인스턴스에서 분리된 채 1시간이 지나면 **$0.005/시간**(약 $3.6/월)이
   붙는다. 인스턴스만 지우고 IP를 남겨 두면 계속 과금된다
4. 재개할 때 스냅샷에서 복원

중단 기간 동안 남는 비용은 **스냅샷 스토리지뿐**(사용 용량 기준 $0.05/GB-월, 대략
월 $0.3~0.5). `data/`는 스냅샷에 함께 들어가므로 별도 백업 없이도 복원된다.

> 봇 특성상 며칠 멈추면 뉴스 수집이 끊겨 감성 차트에 공백이 생긴다. 짧은 중단이라면
> 삭제보다 그냥 두는 편이(월 $7) 관리 비용이 낮다.

신규 AWS 계정이면 $200 크레딧 / 6개월이 적용되어 그동안은 실질 $0이지만, **6개월 후
계정이 닫히거나 과금이 시작된다.** 영구 무료가 필요하면 Oracle Cloud Always Free
(ARM 2 OCPU / 12GB, 기간 제한 없음) 또는 GCP Always Free(e2-micro)로 간다. 이 문서의
Phase 2~5는 그쪽에도 그대로 적용된다.

## 6. 미결 항목

- [ ] `requirements.txt`에 버전 핀이 거의 없다(`apscheduler`만 고정). 서버에서 pandas·
      akshare가 로컬과 다른 버전으로 깔릴 수 있다. Phase 2의 pytest가 이를 잡아주지만,
      재현성이 필요하면 `pip freeze`로 잠금 파일을 만들어 둔다.
- [ ] `signal_scoring` 기능 **키**가 내용과 어긋난다. 성과 채점(`/score`)이 빠지고
      종목 감성 뷰(`/view`)만 남았는데 키·데이터 경로는 `signal_scoring` 그대로다.
      바꾸려면 `FEATURES_ENABLED`와 `data/signal_scoring/` 이동이 함께 필요하므로
      **배포 후 별도 작업**으로 미룬다(배포 직전 데이터 경로 변경은 위험).
- [ ] 관리 웹을 외부에 노출할지 결정(현재 계획은 SSH 터널 전용).
