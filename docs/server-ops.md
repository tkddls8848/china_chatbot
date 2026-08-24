# 서버 운영 (AWS Lightsail)

봇이 서버에서 도는 동안 반복해서 하는 일을 모은 **실행 문서**다. 할 일 목록이
아니라 절차서이므로 항목이 끝나도 지우지 않는다.

**다른 문서와의 경계.** 인스턴스를 처음 만들고 로컬에서 서버로 넘기는 일회성
절차는 `iac/terraform/README.md`가 유일한 문서다 — 여기에 옮겨 적지 않는다.
이 문서는 그 뒤, **이미 떠 있는 서버를 상대로** 하는 일만 다룬다.

| 문서 | 다루는 것 |
|---|---|
| `iac/terraform/README.md` | 인스턴스 생성, 부트스트랩, 최초 전환(cutover), 삭제 |
| **이 문서** | 접속, 상태 확인, 배포 갱신, 설정 변경, 실측, 판정, 백업·복구, 장애 대응 |
| `docs/polymarket-web.md` | 웹 서비스화 계획 (앞으로 만들 것) |

---

## 0. 운영 리전

운영 서버는 도쿄의 1GB `micro_3_0` 인스턴스(`ap-northeast-1a`)다. Polymarket이
한국 IP를 지역 차단(451)해 도쿄 실측 후 이전했으며, 서울 인프라는 2026-08-24에
삭제했다. `iac/terraform/`의 `default` workspace와 `terraform.tfvars`가 도쿄 서버만
관리하고, `iam-policy.json`의 리전 조건도 `ap-northeast-1`만 허용한다. 실제 AWS
관리형 정책 갱신은 IAM 관리자 자격 증명으로 새 정책 버전을 적용한다.

## 1. 접속

명령을 외워 쓰지 않고 Terraform output에서 꺼낸다. 로컬 작업공간에 state·tfvars·
프로바이더 캐시(aws 6.57.1)와 SSH 개인키(`~/.ssh/id_ed25519`)가 모두 있다.

```powershell
cd iac\terraform
terraform output -raw ssh_command
terraform output -raw public_ip
terraform output -raw web_admin_tunnel_command   # 8787은 방화벽에서 닫혀 있다
```

| output | 쓰임 |
|---|---|
| `ssh_command` | SSH 접속 |
| `web_admin_tunnel_command` | 관리 웹 터널. 실행 후 `http://127.0.0.1:8787` |
| `bootstrap_status_command` | 부트스트랩 완료 마커 확인 |
| `verify_commands` | 기동 후 검증 묶음 (Neurons 집계 명령 포함) |
| `rollback_command` | 서버 정지 |

방화벽은 **22번만 열려 있고** 허용 IP가 집 회선으로 좁혀져 있다. 도쿄는
`manage_firewall = false`라 Terraform이 방화벽을 관리하지 않는다. 집 IP가 바뀌어
접속이 막히면 `curl -s https://checkip.amazonaws.com`으로 확인하고 Lightsail 콘솔에서
허용 IP를 바꾼다. 도쿄 운영 IAM은 `OpenInstancePublicPorts`를 허용하지 않으므로
`terraform.tfvars`를 고쳐 `apply`하는 방식은 실패한다.

관리 웹 비밀번호는 부트스트랩이 무작위로 만들어 서버 `.env`에 넣었다.

```bash
grep WEB_ADMIN_PASSWORD ~/stock_chatbot/.env
```

## 2. 상태 확인

```bash
systemctl status stock-chatbot --no-pager
systemctl is-enabled stock-chatbot          # enabled 여야 재부팅 후 자동 기동된다
cd ~/stock_chatbot && git log -1 --oneline  # 서버가 어느 커밋에 서 있나
journalctl -u stock-chatbot -n 50 --no-pager
```

기동 로그에 `봇 시작됨. 활성 기능: ...`이 뜨고 목록이 기대와 같아야 한다.

`is-enabled`가 `disabled`면 **재부팅 후 봇이 올라오지 않는다.** 부트스트랩은
유닛 설치만 하고 `enable`은 전환 명령(`terraform output cutover_commands`)이
`systemctl enable --now`로 한다 — `start`만 했다면 지금 켠다.

```bash
sudo systemctl enable stock-chatbot
```

자주 보는 로그 축:

```bash
journalctl -u stock-chatbot | grep PREFILTER | tail -20   # 사전선별 CPU·보정
journalctl -u stock-chatbot | grep -i error | tail -20
journalctl -u stock-chatbot -f                            # 실시간
```

## 3. 코드 갱신 (배포)

서버는 clone한 `main`을 pull한다. **작업 브랜치에만 커밋해 두면 서버는 옛 코드를
받는다** — 먼저 `main`에 병합하고 push한다.

```bash
cd ~/stock_chatbot
git log -1 --oneline        # 갱신 전 커밋을 기억해 둔다 (되돌릴 지점)
git pull
./venv/bin/pip install -r requirements.txt   # requirements.txt가 바뀐 경우에만
sudo systemctl restart stock-chatbot
journalctl -u stock-chatbot -f
```

**`.env`를 함께 고쳐야 하는 변경이면 `.env`를 먼저 고치고 마지막에 한 번만
재기동한다.** pull부터 하고 재기동하면 새 코드가 옛 설정을 거부해 봇이 뜨지
않는 경우가 있다(대표적으로 `ALLOWED_CHAT_IDS`, 5절).

같은 토큰으로 두 프로세스가 폴링하면 텔레그램이 `Conflict: terminated by other
getUpdates request`를 돌려주고 **양쪽이 번갈아 죽는다.** 로컬 봇을 켜 둔 채로
서버를 재기동하지 않는다.

## 4. 재기동을 피할 시간대

봇이 꺼져 있는 동안 지나간 스케줄은 **따라잡지 않는다.** APScheduler jobstore가
메모리라 놓친 실행은 그냥 사라진다. 아래 창을 피해서 재기동한다.

| JST | 무엇 | 놓치면 |
|---|---|---|
| **08:35 ~ 10:35** | Polymarket 스냅숏(08:35, 재시도 09:35·10:35) | 그날 스냅숏이 통째로 빈다. 가동률 게이트(7일 중 6일)에서 하루를 깎는다 |
| **07:00** | 야간 다이제스트 발송 | 큐가 다음 주간 주기로 넘어간다(첫 주간 주기가 큐를 확인하므로 유실은 아니다) |
| 매시 정각 부근 | 뉴스 주기(60분) | 그 주기 한 번을 건너뛴다. 다음 주기가 같은 후보를 다시 본다 |

가장 안전한 창은 **11:00 ~ 23:00 사이의 정각 직후**다. 재부팅도 같은 기준으로
잡는다 — `data/`는 영구 루트 디스크에 있어 재부팅으로 사라지지 않지만,
스냅숏 창을 덮으면 그날 하루치를 잃는다.

## 5. 설정 변경

**`.env`는 비밀값·자격증명만 갖는다**(토큰, 비밀번호, 프록시 URL, chat id).
그 외 모든 설정 — 기능 켜기/끄기, 수량·주기 같은 튜닝값 — 은
`app/core/config.py`의 리터럴 상수다(2026-08-23 정리). 값을 바꾸려면 코드를
고치고 git에 커밋한다 — 서버 `.env`를 직접 고치던 예전 방식은 무엇을 언제
왜 바꿨는지가 서버에만 남고 git 이력에는 없었다.

```bash
cd ~/stock_chatbot
git log -1 --oneline        # 갱신 전 커밋을 기억해 둔다
git pull
sudo systemctl restart stock-chatbot
```

지금 서버 `.env`에 남아 있어야 하는 키는 `.env.example`에 적힌 것뿐이다:
`TELEGRAM_BOT_TOKEN`·`TELEGRAM_CHAT_ID`·`ALLOWED_CHAT_IDS`·
`CLOUDFLARE_ACCOUNT_ID`·`CLOUDFLARE_API_TOKEN`·`CLOUDFLARE_MODEL`(모델
폐기·개명에 코드 배포 없이 대응하는 유일한 예외)·`WEB_ADMIN_USER`·
`WEB_ADMIN_PASSWORD`·`POLYMARKET_PROXY_URL`. 이 목록 밖의 키가 `.env`에
남아 있다면(예: 옛 `NEWS_GLOBAL_LIMIT=4`) 지운다 — `load_dotenv`가 이걸
`os.environ`에 얹어도 더 이상 아무도 읽지 않으니 무해하지만, 다음에 값을
바꿀 때 "여기 있는 값이 진짜인가" 혼란을 남긴다.

**`ALLOWED_CHAT_IDS`가 비면 `ConfigurationError`로 기동하지 않는다.** 빈 값을
전체 허용으로 읽던 분기를 없앴기 때문이다(상태가 채팅별로 나뉘어 있지 않아
설정 누락이 곧바로 공개 봇이 된다). 숫자가 아닌 자리표시자만 남은 경우도 같게
막힌다. `TELEGRAM_CHAT_ID`와 같은 값을 넣으면 되고, 쉼표로 여러 개도 된다.

```bash
grep -n '^ALLOWED_CHAT_IDS=' ~/stock_chatbot/.env
```

## 6. Neurons 실사용 측정

| 구분 | 값 |
|---|---|
| 무료 한도 | 10,000 Neurons/일 (**UTC 00시 = JST 09시** 리셋) |
| 60분 주기 상한 | 하루 408건 번역 (주간 17주기 × 소스 6곳 × 4건) + 야간 요약 4회 |
| 20분 주기 시절 실측 | 하루 272~323건 ≈ 3,000~3,600 |

**상한이 실측보다 큰 것이 요점이 아니다.** 20분 주기에서는 상한이 발행량보다
훨씬 커서 사실상 발행되는 대로 다 번역했고 실제 소비는 소스 발행량이 정했다.
60분 주기에서는 상한이 먼저 걸리므로 실제 소비가 표의 값에 가까워진다. 반대로
야간 7시간분이 기사별 번역에서 통째로 빠지고 사전선별의 재탕 차단이 소스 간
중복을 걷어낸다 — 순증인지 순감인지는 재 봐야 안다.

**서버에서 잰다.** 같은 명령이 `terraform output verify_commands`에 들어 있다.
최근 7일을 UTC 일자별로 한 줄씩(`YYYY-MM-DD <합계>`) 뱉는다.

```bash
journalctl -u stock-chatbot --since "$(date -u -d '6 days ago' '+%Y-%m-%d 00:00:00 UTC')" --until "$(date -u -d 'tomorrow' '+%Y-%m-%d 00:00:00 UTC')" -o short-iso-precise --utc --no-pager | awk 'match($0, /neurons=[0-9]+([.][0-9]+)?/) { day = substr($1, 1, 10); total[day] += substr($0, RSTART + 8, RLENGTH - 8) } END { for (day in total) printf "%s %.2f\n", day, total[day] }' | sort
```

**로컬 `bot.log`로는 이 측정을 할 수 없다.** 로그 포맷(`%(asctime)s`)이 호스트
로컬 시각을 오프셋 없이 찍어 한 줄만 보고 UTC 일자를 복원할 수 없다. JST
호스트라는 외부 가정을 얹어야 환산되므로 판정 근거로는 서버 수치만 쓴다.

**판정과 조치**

- 한도를 넘기면 `config.py`의 `NEWS_SOURCE_ARTICLE_LIMIT`부터 내리고 커밋한다.
  하루 기사량을 정하는 상한은 송출 상한(`NEWS_DIGEST_SEND_LIMIT`)이 아니라
  이 값이다.
- 소진되면 그날 남은 시간 동안 `/research`와 `/market`이 **막힌다.** 뉴스
  다이제스트만 비는 게 아니다.
- 여유가 크게 남으면 깊이(본문 길이·후보 수)를 먼저 올린다. **깊이는 싸고
  수량은 비싸다** — 기사 1건이 호출 1회이므로 수량은 선형으로 늘어난다.

## 7. 사전선별(shadow → active) 판정

`news_prefilter`는 번역 전에 원문 후보를 사건 단위로 묶고 점수를 매긴다. 번역
건수는 `NEWS_GLOBAL_LIMIT` 그대로라 **추가 Neurons는 0**이고, 대신
`NEWS_SOURCE_ARTICLE_LIMIT`을 250으로 올려 CPU로 깊이를 산다.

**"일주일 뒤"의 시작점은 서버에 켠 날이다.** 로컬에서 대신 쌓을 수 없다 —
관측은 뉴스 주기가 돌아야 생기고 로컬 봇은 돌지 않는다.

켠 뒤 첫 며칠은 CPU만 본다.

```bash
journalctl -u stock-chatbot | grep PREFILTER | grep 중단= | tail -20
```

`중단=budget`이 **매일** 나오면 예산이 아니라 관측량을 먼저 줄인다. 배경 보정은
하루 4.32 CPU-hour(`NEWS_PREFILTER_CALIBRATION_DAILY_BUDGET_SECONDS`) 안에서만
돌고, 직전 1분의 foreground CPU를 빼 전체 2 vCPU의 9% 안에서 적응적으로
페이스를 잡는다. 긴급 뉴스·버스트 우선 작업·load average 1.5 이상에서도
스스로 물러난다.

일주일 뒤 `/system prefilter`로 네 축을 본다.

| 축 | 무엇을 답하나 | 승격 기준 |
|---|---|---|
| 두 정책의 불일치 | 바꿀 이유가 있는가 | 최신순만·사전선별만이 각각 유의미하게 있어야 한다. 0이면 바꿔도 같은 기사다 |
| 점수 AUC | 점수가 impact를 가르는가 | 0.5(무작위)보다 뚜렷이 높아야 한다 |
| 모델 검증 AP | 보정기가 기저보다 나은가 | `validation_ap` > `validation_prevalence` |
| CPU 예산 | 3.6h/일 안에 들어오는가 | 소진으로 중단되는 날이 없어야 한다 |

**AUC를 "더 나은 기사를 찾는 능력"으로 읽지 않는다.** shadow에서 번역되는 것은
최신순 상위뿐이라 라벨도 거기에만 붙는다. 즉 이 AUC는 *최신순이 이미 고른 기사들
안에서의 순위*다. 사전선별이 새로 끌어올렸을 기사가 실제로 좋았는지는 `active`의
탐색 슬롯이 그 기사를 번역해 봐야 안다. 같은 경고가 `/system prefilter` 하단과
`service.py`의 `SHADOW_CAVEATS`에 있다.

**판정과 조치**

- 네 축 통과 → `config.py`의 `NEWS_PREFILTER_MODE`를 `"active"`로 바꾸고
  커밋·배포한다. 탐색 슬롯 1개가 번역 슬롯 하나를 임의 깊이 기사에 배정하기
  시작하므로 그 뒤부터 편향 없는 라벨이 쌓인다. 다시 일주일 뒤 AUC를 재읽는다.
- 불일치가 0에 가까움 → 깊이만 올린 셈이니 `NEWS_SOURCE_ARTICLE_LIMIT`을 30으로
  되돌리고(커밋) 기능을 끈다. 점수가 순서를 못 바꾸면 유지할 값이 없다.
- AUC가 0.5 근처 → 올리지 않는다. 가중치를 손보기 전에 어떤 feature가 실제로
  살아 있는지 본다(실측: 종목 매칭은 원문 제목의 8.2%에서만 걸린다).

## 8. Polymarket 컨센서스 파일럿

기본 꺼짐(`POLYMARKET_ENABLED=false`)인 섀도 파일럿이다. `market_sentiment`의
외부 소스이지 별도 기능 키가 아니다.

### 무엇으로 쓸 수 있나

Gamma API는 인증이 필요 없고 LLM 비용도 0이다. 문제는 커버리지다. 실측
(2026-08-10, `closed=false` · `volumeNum>=10,000` · `liquidityNum>=1,000`):

| 지역 | 직접 주식·지수 | 거시 프록시 | 독립 이벤트 |
|---|---:|---:|---:|
| 중국 | **0** | 14 | 13 |
| 홍콩 | **0** | 0 | 0 |
| 한국 | **0** | 4 | 3 |
| 미국 | 11 | — | 6 |

홍콩은 유동성 상위가 당일 기온과 정치 마켓이었다. 한국은 북한 침공·Q3 GDP 구간·
한국은행 동결 3건뿐이고 KOSPI나 개별종목 마켓은 없다. 따라서 이 값은 **개별종목
감성이 아니라 글로벌 거시 위험선호의 외부 참고선**으로만 쓸 수 있다.

설계상 지킨 것(회귀 테스트가 붙어 있으니 바꿀 때 함께 본다):

- 표시 위치는 `/market` **하나만**. 하단 별도 축에 `24시간 거시 위험선호
  확률변화(pp)`를 그린다.
- 국가별 -1~+1 점수·기사 수·순위에 **합산하지 않는다.** CN/HK/US/KR 선으로
  복제하지도 않는다.
- `/research` 입력과 브리핑 payload에 넣지 않는다 → **추가 Neurons 0/일**.
- 전일·당일에 **같은 conditionId**가 있는 계약만 비교한다. 만료 계약을 다른
  slug로 잇지 않고, 빠진 날을 앞 값으로 채우지 않으며, 같은 날 두 번째 스냅숏은
  저장하지 않는다(08:35 값과 오후 값을 섞으면 일간 변화가 아니다).
- 집계는 계약 → 이벤트 중앙값 → theme 중앙값 → theme 평균으로 접는다. S&P
  임계값 8개짜리 이벤트가 한반도 이벤트 하나보다 8배 세지지 않는다.
- 방향은 `polymarket_rules.py`의 명시적 allowlist로만 정한다. **LLM에게 묻지
  않는다.** GDP 구간·금리 결정처럼 국면 의존적인 질문은 제외한다.

| 자리 | 파일 |
|---|---|
| Gamma `/markets` 클라이언트·파서 | `app/features/market_sentiment/polymarket.py` |
| 게이트·theme allowlist·polarity | `app/features/market_sentiment/polymarket_rules.py` |
| 08:35 JST 스냅숏 job | `app/features/market_sentiment/snapshot.py` |
| 스냅숏 저장·일별 정렬·게이트 계산 | `app/state/polymarket_consensus.py` |
| 과거 시세 백필(일회성 도구) | `polymarket_history.py`, `app/polymarket_backfill.py` |
| 하단 패널 | `app/features/market_sentiment/chart.py` |

### 8-1. 착수 전 읽기 스모크

운영 Lightsail은 출구 IP가 달라 **한국 PC에서 열렸다는 사실이 서버 접근을
보장하지 않는다.** Gamma 시장 목록과 CLOB 과거 시세를 둘 다 확인한다(host가
달라 한쪽만 열릴 수 있다). 부트스트랩은 실행 의존성만 깔므로 pytest를 먼저 받는다.

```bash
cd ~/stock_chatbot
./venv/bin/pip install -r requirements-dev.txt
RUN_POLYMARKET_SMOKE=1 ./venv/bin/python -m pytest -q -m polymarket_smoke
```

막히면 **거기서 끝낸다.** 프록시로 우회하지 않는다 — 착수도 안 한 신호를 위해
우회로를 만들어 둘 가치가 없다. 8-5의 철수를 밟는다.

이 판단은 **착수 전 단계에만** 적용된다. 이미 며칠·몇 주 정상 수집하던 라이브
job이 도중에 막히면(가동률 게이트가 이미 값을 쌓아 온 신호라는 뜻) 별개
상황이다 — 8-4를 본다.

### 8-2. 수집과 백필은 같은 날 시작한다

승격 조건은 두 축이고 **서로를 대신하지 못한다.**

| 축 | 무엇을 답하나 | 누가 재나 | 걸리는 시간 |
|---|---|---|---|
| 게이트의 실질(theme 수·기여도·변화 밀도) | 이 지표가 쓸 만한가 | 백필 | 하루 |
| job 가동률 | 매일 08:35에 실제로 찍히는가 | 라이브 수집 | 일주일 |

백필을 기다렸다 수집을 켤 이유가 없다. 수집은 Neurons를 쓰지 않고 표시도 꺼져
있어 켜 두는 비용이 사실상 없으며, 그동안 가동률 일주일이 저절로 쌓인다.

`config.py`의 `POLYMARKET_ENABLED`를 `True`로 바꾸고 커밋·배포한다.
`POLYMARKET_PANEL_ENABLED`는 `False` 그대로 둔다 — **수집하되 표시하지
않는다.**

같은 날 **서버에서** 백필을 한 번 돌린다. 로컬에서 돌려도 판정은 같지만, 서버
파일이어야 `/system polymarket`이 두 축을 한 화면에 그린다.

```bash
cd ~/stock_chatbot && ./venv/bin/python app/polymarket_backfill.py
```

결과는 `data/market_sentiment/polymarket_backfill.json`에만 쓴다. 라이브 스냅숏과
섞지 않는다 — 백필에는 과거 호가가 없고 수량 게이트가 조회 시점 값으로 적용돼
있다. 유동성 게이트가 31일 내내 "오늘의 유동성"으로 적용되는 낙관 편향이 특히
크다. **통과가 아슬아슬하면 통과로 읽지 않는다.**

### 8-3. 승격 게이트

`/system polymarket`(또는 시스템 상태 화면의 **🎲 폴리마켓** 버튼)이 두 축을
한 화면에 그린다. 백필과 라이브가 같은 코드로 계산한다.

| 게이트 | 기준 | 백필로 판정되나 |
|---|---|---|
| 성공 스냅숏 | 30일 중 24일 이상(80%) | 데이터 유무만. 가동률은 라이브 |
| 유효 daily delta | 24일 이상 | 예 |
| 공통 이벤트 3개 이상인 날 | 유효일의 80% 이상 | 예 |
| 독립 theme | 3개 이상 | 예 |
| 최대 theme 기여도 | 50% 이하 | 예 |
| median spread | 5%p 이하 | 아니오(과거 호가가 없어 오늘 값만) |
| 최근 7일 스냅숏(가동률) | 6일 이상 | 아니오 — 라이브 전용 |

백필이 답하지 못하는 두 가지(median spread, job 가동률)는
`polymarket_history.py` 첫머리에도 적어 두었다. **지운 채로 승격하지 않는다.**

- 백필 미달 → **거기서 끝낸다.** 라이브를 30일 더 봐도 같은 항목이 통과할 근거는
  없다. `config.py`의 `POLYMARKET_ENABLED`를 `False`로 되돌리고(커밋) 8-5로 간다.
- 백필 통과 → 일주일 뒤 최근 7일 스냅숏이 6일 이상인지만 확인하고
  `config.py`의 `POLYMARKET_PANEL_ENABLED`를 `True`로 올린다(커밋). 그 뒤
  `/market`을 한 번 호출해 하단 패널이 붙는지, 위 순위·캡션이 그대로인지
  눈으로 확인한다.

게이트 임계값(`POLYMARKET_MIN_VOLUME` 등)과 `POLYMARKET_ENABLED`·
`POLYMARKET_PANEL_ENABLED`는 전부 `config.py`의 상수다 — 바꾸려면 코드를
고쳐야 하고 git에 남는다. 백필과 라이브 사이에 게이트 임계값을 바꾸지
않는 이유는 바꾸면 두 표본이 달라져 백필 판정을 라이브에 얹을 수 없어서다.
env로 남은 폴리마켓 키는 `POLYMARKET_PROXY_URL` 하나뿐이다(지역 차단용
자격증명이 섞여 있어 git에 올릴 수 없다, 8-4).

### 8-4. 라이브 수집이 지역 차단(451)에 막히면 — 프록시

정상 수집 중이던 job이 어느 날부터 `HTTP 451`(법적 사유로 이용 불가)로
연속 실패하는 경우다. `journalctl -u stock-chatbot | grep POLYMARKET`에서
`result=bad_request status=451`이 매 재시도(08:35·09:35·10:35)마다 찍히고
코드·설정 변경 없이 시작됐다면, Gamma가 이 서버 출구 IP의 지역을 막기
시작했다는 뜻이다(8-1의 "착수도 안 한 신호" 판단과는 다른 상황).

`PolymarketClient`·`PolymarketHistoryClient`는 원래 `session=`을 받으므로,
막혔을 때만 프록시를 문 세션을 넘긴다. 평소엔 아무 세션도 넘기지 않아
직접 호출 그대로다 — 이 경로 전체가 `POLYMARKET_PROXY_URL` 한 줄로
켜지고 지워진다.

| 자리 | 파일 |
|---|---|
| 프록시 세션 팩토리(요청 시에만 관여) | `app/features/market_sentiment/polymarket_proxy.py` |

```env
# 비어 있으면(기본) 직접 호출한다. 지역 차단(451)이 뜰 때만 채운다.
POLYMARKET_PROXY_URL=http://user:pass@proxy-host:port
```

`.env`에 넣고 재기동한 뒤 다음 재시도 창(정시 35분)까지 기다려
`journalctl`에서 `result=`가 더 이상 뜨지 않는지 확인한다. socks5 프록시를
쓰려면 서버에 `pip install pysocks`가 먼저 있어야 한다(requests의 SOCKS
지원 의존성이고 이 프로젝트가 기본으로 깔지 않는다).

떼어낼 때는 `.env`에서 `POLYMARKET_PROXY_URL`을 지우고 재기동하면 된다.
완전히 걷어내려면(신호로서 가치가 없다고 판단한 경우) 이 값을 지운 뒤
`polymarket_proxy.py` 파일과 `feature.py`·`polymarket_backfill.py`의
`build_polymarket_session` 호출 두 곳도 함께 지운다.

이걸로도 안 풀리면(프록시 출구도 막히거나, 프록시를 구할 수 없으면) 8-5를
밟는다.

#### 지금 세워 둔 프록시 (2026-08-22)

한국(AWS 서울·KT 회선 둘 다) 전부 `gamma-api.polymarket.com`·`clob.polymarket.com`이
451이고 도쿄(`ap-northeast-1`)는 둘 다 200임을 임시 인스턴스로 실측한 뒤, 같은
리전에 상시용 프록시를 세웠다.

| 항목 | 값 |
|---|---|
| 인스턴스 | `polymarket-proxy-tokyo` (`ap-northeast-1a`, `nano_3_0`, `ubuntu_22_04`) |
| 프록시 | tinyproxy, 포트 80(기본 개방 포트라 `OpenInstancePublicPorts` 불필요) |
| 접근 제어 | `Allow` ACL을 이 서버의 고정 IP(`3.34.234.102`)로 제한 + Basic Auth 이중 |
| 자격 증명 | 서버 `.env`의 `POLYMARKET_PROXY_URL`에만 있다. 여기(git)에는 적지 않는다 |

**이 인스턴스는 terraform이 관리하지 않는다** — AWS CLI로 직접 만들었다. 붙였다
뗄 수 있는 부속물로 두는 게 목적이라, 본 배포(`iac/terraform/`)에 편입하지
않았다. 유지보수(재기동·설정 변경)는 Lightsail 콘솔의 브라우저 SSH로 한다
— `stock-chatbot-deployer` IAM 자격으로는 `ap-northeast-1`의
`GetInstanceAccessDetails`·`OpenInstancePublicPorts`가 막혀 있어(`iam-policy.json`의
리전 조건과는 별개로, 허용된 도쿄 리전에서도 CLI로 키를 뽑아내거나
방화벽을 여는 건 항상 막힌다) 로컬 CLI로는 SSH 키를
받을 수 없다.

프록시 출구(도쿄)가 막히는 날이 오면 인스턴스를 지우고 다른 리전에 새로
세운다 — 상태를 갖지 않는 부속물이라 다시 만드는 비용이 낮다.

### 8-5. 철수 (하나라도 미달이면)

기준 미달을 "조금만 더 보자"로 넘기지 않는다.

1. `config.py`의 `POLYMARKET_ENABLED`·`POLYMARKET_PANEL_ENABLED`를 둘 다
   `False`로 바꾸고 커밋·배포한다. 서버 `.env`에 `POLYMARKET_PROXY_URL`이
   있으면 지우고 재기동한다.
2. 서버·로컬의 `data/market_sentiment/polymarket_consensus.json`과
   `polymarket_backfill.json` 삭제.
3. 코드 제거 — 파일 통째 삭제:
   - `app/features/market_sentiment/polymarket.py`
   - `app/features/market_sentiment/polymarket_rules.py`
   - `app/features/market_sentiment/polymarket_history.py`
   - `app/features/market_sentiment/polymarket_proxy.py`(8-4에서 붙였다면)
   - `app/features/market_sentiment/snapshot.py`
   - `app/polymarket_backfill.py`
   - `app/state/polymarket_consensus.py`
   - `tests/test_polymarket_{client,rules,consensus,panel,wiring,history,smoke,proxy}.py`
4. 코드 제거 — 부분 되돌리기:
   - `app/core/config.py`의 `POLYMARKET_*` 블록
   - `app/features/market_sentiment/feature.py`의 서비스·job 조립
   - `app/features/market_sentiment/handlers.py`의 `_consensus_panel_series`,
     패널 상수 2개, 캡션 주석
   - `app/features/market_sentiment/chart.py`의 `_draw_consensus_panel`과
     `consensus` 인자(2패널 레이아웃으로 환원)
   - `app/features/system_admin/handlers.py`의 `polymarket` 하위 명령과 라벨·포매터
   - `app/features/system_admin/feature.py`의 usage 문자열
   - `app/state/__init__.py`의 export 2개
   - `pytest.ini`의 `polymarket_smoke` 마커
   - `.env.example`·`README.md`·`CLAUDE.md`·`app/features/README.md`의 관련 문단
5. `python -m pytest -q`와 `ruff check app tests`로 원상 복구를 확인한다.

## 9. 백업·복구·재부팅

상태는 전부 `~/stock_chatbot/data/` 하위 JSON/JSONL이고 DB가 없다. 보호 장치는 셋이다.

| 장치 | 주기 | 자리 |
|---|---|---|
| tar 백업 cron | 매일 03:00 JST, 14일 보관 | `/home/<app_user>/backup-YYYY-MM-DD.tgz` |
| Lightsail 자동 스냅샷 | 매일 04:00 JST (19:00 UTC) | 콘솔 |
| 원자적 쓰기 | 매 저장 | `core/storage.py` (임시파일 → fsync → `os.replace`) |

```bash
ls -la ~/backup-*.tgz | tail -5                      # 백업이 실제로 도는지
tar tzf ~/backup-$(date +%F).tgz | head              # 내용 확인
tar xzf ~/backup-YYYY-MM-DD.tgz -C /tmp/restore      # 복구는 다른 경로에 풀고 골라 덮는다
```

**재부팅으로 `data/`는 사라지지 않는다.** 영구 루트 디스크에 있어 reboot도
stop/start도 보존한다. 사라지는 것은 인스턴스를 **삭제·재생성**할 때뿐이고,
그때는 `data/`가 별도 볼륨이 아니라 루트 디스크에 있으므로 스냅샷/백업 tar에
없는 것은 전부 잃는다.

재부팅으로 실제 손해가 나는 것은 셋뿐이다.

- 4절의 스케줄 창을 덮으면 그 실행분(특히 Polymarket 하루치)이 빈다.
- `event_memory.json`은 60초에 한 번 저장하므로 직전 1분의 `translated_at`
  표시를 잃을 수 있다(사건 한둘이 재번역될 수 있다).
- 사전선별 보정이 `observations.jsonl`을 처음부터 한 번 다시 읽는다(읽기 offset이
  메모리 전용이다). 손실이 아니라 CPU 비용이고 그날 예산에서 나간다.

`cloud-init` user_data는 인스턴스당 1회만 실행되므로 재부팅으로 부트스트랩이 다시
돌지 않는다. 다시 돌려야 하면 SSH로 직접 실행한다(`iac/terraform/README.md`).

## 10. 장애 대응

**봇이 뜨지 않는다.**

```bash
journalctl -u stock-chatbot -n 80 --no-pager
```

| 로그 | 원인 | 조치 |
|---|---|---|
| `ConfigurationError` + 허용 목록 | `ALLOWED_CHAT_IDS`가 비었다 | 5절 |
| `Conflict: terminated by other getUpdates` | 로컬 봇이 같이 켜져 있다 | 한쪽을 끈다 |
| `ModuleNotFoundError: core` | `WorkingDirectory`가 `app/`이 아니다 | 유닛 파일 확인 |
| `No module named pytest` | 부트스트랩은 실행 의존성만 깐다 | `pip install -r requirements-dev.txt` |
| 차트 관련 실패 | `MPLBACKEND=Agg`가 없다 | 유닛 파일 확인 |

**직전 배포로 되돌린다.** 서버에서 커밋을 되돌리고 재기동한다.

```bash
cd ~/stock_chatbot && git log --oneline -5
git checkout <직전 커밋>          # 확인 후 main을 고치고 다시 pull로 복귀한다
sudo systemctl restart stock-chatbot
```

**서버를 세운다.** `terraform output -raw rollback_command`. 로컬 봇을 다시 켤
때는 서버가 확실히 멈춘 뒤에 켠다.

**메모리·CPU를 본다.** 1GB에 스왑 2G다.

```bash
free -h; uptime; systemctl status stock-chatbot --no-pager | grep Memory
```

load average가 상시 1.5 이상이면 사전선별이 스스로 물러나 보정이 진행되지
않는다. 그 상태가 계속되면 관측량이나 bundle을 다시 본다 —
`NEWS_PREFILTER_LIGHTSAIL_VCPUS`는 `micro_3_0`(2 vCPU, baseline 10%)에,
`NEWS_PREFILTER_TARGET_CPU_UTILIZATION`은 평시 9%에 맞춰져 있다. bundle을
바꾸면 vCPU 수를 함께 바꾼다.

`journalctl | grep PREFILTER`에는 보정 CPU와 직전 주기의 `foreground` CPU가
함께 찍힌다. 두 값을 합친 주기당 목표 상한은 10.8 CPU-second다. 리서치,
야간 다이제스트, 시장 컨센서스 처리 중에는 `버스트 우선 작업 진행 중 · 보정
양보`가 찍힌다. 이 작업들은 9% 제한 밖에서 실행되어 모아 둔 burst capacity를
우선 사용한다. 콘솔의 CPU 평균이 계속 9%를 넘으면 목표값보다 먼저 봇 외
프로세스와 스케줄 중첩 여부를 확인한다.
