# China Chatbot

텔레그램에서 중국·홍콩·한국·글로벌 시장 뉴스를 수집하고, 번역·감성 분석·관심 종목 관리·브리핑을 제공하는 봇입니다.

## 시작하기

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python app\bot.py
```

`.env`에는 아래 값이 필요합니다.

```env
TELEGRAM_BOT_TOKEN=<BotFather 토큰>
TELEGRAM_CHAT_ID=<알림을 받을 채팅 또는 채널 ID>
CLOUDFLARE_ACCOUNT_ID=<Cloudflare 계정 ID>
CLOUDFLARE_API_TOKEN=<Workers AI 실행 권한 토큰>
```

전체 설정과 기본값은 [`.env.example`](.env.example)에서 확인할 수 있습니다.

### LLM은 Cloudflare Workers AI를 사용합니다

번역·감성 분석·리서치·브리핑 코멘트가 모두 Cloudflare Workers AI(`@cf/qwen/qwen3-30b-a3b-fp8`)로 동작합니다. 로컬 GPU나 별도 추론 서버가 필요 없어서 **1GB 메모리 무료 VM에서도 돌아갑니다.**

- 무료 한도는 **하루 10,000 Neurons**이며 UTC 00시(한국시간 오전 9시)에 리셋됩니다. 실측 기준 기사 1건 번역이 약 8~14 Neurons, 리서치 분석 1회가 약 110 Neurons입니다.
- 한도가 소진되면 다음 리셋까지 호출을 멈춥니다. 그날 뉴스 다이제스트는 비고 `/research`는 실패하지만, 브리핑은 지수·헤드라인만 담은 데이터 전용 브리핑으로 자동 전환됩니다.
- 실사용량은 로그에서 바로 확인합니다: `grep 'neurons=' bot.log`
- 한도를 넘겨 쓰려면 Workers Paid 플랜에서 초과분이 1,000 Neurons당 $0.011입니다.
- API 토큰은 `.env`에만 두고 커밋하지 않습니다. 로그와 예외 메시지에는 토큰이 남지 않습니다.

배포는 [`docs/deployment-lightsail-plan.md`](docs/deployment-lightsail-plan.md)를 참고하세요.

## 테스트

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

실제 Cloudflare 계정을 호출하는 스모크 테스트는 기본 실행에서 제외되며, 자격증명과 무료 할당량을 소비합니다.

```powershell
$env:RUN_CLOUDFLARE_SMOKE='1'
python -m pytest -q -m cloudflare_smoke
```

## 주요 기능

- 중국·홍콩·미국·한국·글로벌 시장 뉴스 수집과 한국어 번역
- 시장별 뉴스 감성 차트 (`/market`)
- 관심 종목 뉴스·감성 요약
- 뉴스 기반 시장 리서치 후보 관리 (중화권·미국·한국 균형 수집과 추천)
- 장중·마감 브리핑 및 주간 스코어카드
- 중국·홍콩·한국·미국 종목 DB

## 텔레그램 명령

| 명령 | 설명 |
|---|---|
| `/market [일수]` | 시장별 뉴스 감성 차트 |
| `/menu`, `/list` | 관심 종목 목록 |
| `/add 종목코드` | 관심 종목 추가 |
| `/view [종목코드]` | 종목별 뉴스 감성 |
| `/research show\|set\|run\|clear` | 리서치 후보 관리 |
| `/briefing morning\|evening\|scorecard` | 브리핑 또는 성과표 생성 |
| `/stockdb build` | 종목 DB 갱신 |
| `/system` | 시스템 상태 확인 |

## 관리 웹 (선택)

봇 프로세스에 내장되는 관리용 웹 대시보드로, 관심 종목·뉴스·리서치·시스템 상태를 브라우저에서 확인·관리합니다. 다른 기능과 같이 `FEATURES_ENABLED`의 `web_admin` 키로 켜고 끄며, 봇을 제어하므로 비밀번호를 지정해야만 기동합니다.

```env
FEATURES_ENABLED=...,web_admin
WEB_ADMIN_HOST=127.0.0.1
WEB_ADMIN_PORT=8787
WEB_ADMIN_USER=admin
WEB_ADMIN_PASSWORD=<반드시 지정>
```

- `WEB_ADMIN_PASSWORD`를 지정하지 않으면 기능이 켜져 있어도 자동으로 건너뜁니다.
- 모든 요청은 HTTP Basic 인증 뒤에 있으며, 봇과 같은 이벤트 루프에서 동작해 텔레그램과 상태를 공유합니다.
- 외부에 노출할 때는 HTTPS 역방향 프록시(예: Nginx/Caddy/Cloudflare) 뒤에 두는 것을 권장합니다.

접속 후 `http://<호스트>:<포트>/`에서 시스템 상태, 관심 종목 추가·삭제, 최근 뉴스, 리서치 후보를 확인할 수 있습니다.

## 종목 DB

`/stockdb build`는 AkShare에서 중국·홍콩 종목을, FinanceDataReader와 Nasdaq Trader에서 각각 한국·미국 전체 상장종목을 수집합니다.

종목 DB는 `data/instruments/stock_db.json`에 캐시됩니다. FIGI·ISIN 같은 식별자 필드는 기존 데이터 구조 호환성을 위해 빈 값으로 남아 있으며, 외부 식별자 매핑 API는 사용하지 않습니다.

## 데이터와 접근 제어

- `data/`에는 관심 종목, 발송 이력, 뉴스·신호 로그, 종목 DB가 코드와 같은 기준으로 **소유 기능별 하위 디렉토리**(`news/`, `watchlist/`, `instruments/`, `signal_scoring/`, `research/`, `runtime/`)에 저장됩니다. 이전 버전의 평면 배치(`data/*.json`) 파일은 봇 시작 시 자동으로 새 위치로 이동합니다.
- `ALLOWED_CHAT_IDS`에 쉼표로 구분한 채팅 ID를 설정하면 해당 채팅에서만 명령을 처리합니다.
- 뉴스·시세 제공처가 일시적으로 실패해도 다른 기능은 계속 동작하며, 다음 주기에 다시 수집합니다.

## 프로젝트 구조

```text
app/        봇, 명령 처리, 뉴스·LLM·종목 DB·관심 종목 모듈
prompts/    번역·리서치·브리핑 프롬프트
scripts/    운영 및 보조 스크립트
tests/      자동화 테스트
docs/       설계와 작업 문서
data/       실행 중 생성되는 상태·캐시 데이터, 소유 기능별 하위 디렉토리 (Git 제외)
```
