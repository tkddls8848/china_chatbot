# 서버 작업 (AWS Lightsail)

운영 서버에 접근해야 진행되는 일만 모은다. 끝난 항목은 지운다.
로컬 코드 작업은 `docs/next-steps.md`에 있다. 배포 절차 자체는
`iac/terraform/README.md`가 유일한 문서다 — 여기에는 절차를 옮겨 적지 않는다.

## 접속 경로 (2026-08-18 확인)

2026-08-15에 첫 배포가 실제로 끝났고(`f853dd9`), 그때 막힌 세 지점은 그 커밋이
고쳤다. **이 작업공간에서 서버에 닿을 수 있다** — 아래가 모두 갖춰져 있다.

| 경로 | 상태 |
|---|---|
| Terraform state | `iac/terraform/terraform.tfstate`·`terraform.tfvars` **있음** |
| 프로바이더 캐시 | `.terraform/` 초기화됨(aws 6.57.1, lock과 일치) |
| SSH 개인키 | `~/.ssh/id_ed25519` **있음**. `known_hosts`에 8/15 접속 기록 |
| Lightsail 권한 | `terraform apply`가 통과했다 = IAM 정책이 붙어 있다 |

접속 명령은 외워 쓰지 않고 output에서 꺼낸다.

```powershell
cd iac\terraform
terraform output -raw ssh_command
terraform output -raw web_admin_tunnel_command   # 8787은 방화벽에서 닫혀 있다
```

## 서버 상태 (2026-08-18 기준, 미확인 축)

| 축 | 확인 결과 |
|---|---|
| 서버 코드 커밋 | **미확인.** 배포는 8/15이고 그 뒤 `main`에 커밋 11개가 쌓였다 |
| 서버 `.env` | **미확인.** 다만 부트스트랩이 복사한 원본은 확정이다(작업 1) |
| Neurons 실사용 | **미측정.** 60분 주기·야간 다이제스트 적용 후 수치는 추정치뿐이다 |
| Polymarket 수집 | 로컬은 수집·표시 모두 꺼짐이고 스냅숏 파일도 없다. 서버 착수 여부 **미확인** |

## 실행 순서

```
1. 코드·설정 동기화(기동 차단 요소 먼저)  →  2. Neurons 실측(며칠)  →  3. Polymarket 수집·백필 동시 시작(일주일)  →  승격
```

1을 건너뛰고 2를 재면 옛 설정(20분 주기·깊이 30)의 소비를 재는 것이 된다.
3은 1의 결과가 무해함을 확인한 뒤에 켠다 — 한도가 이미 빠듯하면 새 수집을 얹을
때가 아니다(다만 Polymarket 자체는 Neurons를 쓰지 않는다).

**Polymarket 판정은 30일을 기다리지 않고, 수집과 백필을 나란히 시작한다.**
승격 조건은 두 축이고 서로를 대신하지 못한다.

| 축 | 무엇을 답하나 | 누가 재나 | 걸리는 시간 |
|---|---|---|---|
| 게이트의 실질(theme 수·기여도·일별 변화 밀도) | 이 지표가 쓸 만한가 | 백필 | 하루 |
| job 가동률 | 매일 08:35에 실제로 찍히는가 | 라이브 수집 | 일주일 |

백필을 기다렸다가 수집을 켤 이유가 없다. 수집은 Neurons를 쓰지 않고 표시도
꺼져 있어(`POLYMARKET_PANEL_ENABLED=false`) 켜 두는 비용이 사실상 없으며,
그동안 가동률 일주일이 저절로 쌓인다. 반대로 백필이 미달로 나오면 그 시점에
수집을 끄고 3-3의 철수를 밟으면 된다 — 며칠치 스냅숏을 버리는 것뿐이다.

두 축은 `/system polymarket` 한 화면에 나란히 나온다.

---

## 1. 서버를 현재 코드·설정으로 올린다

배포 이후 `main`에 커밋 11개가 쌓였고 그중 다섯은 서버 동작을 바꾼다: 60분 주기,
야간 다이제스트, 사전선별, 원자적 상태 쓰기, 빈 허용 목록 기동 차단.
`requirements.txt`는 **바뀌지 않았으므로** `pip install`은 필요 없다.

**순서가 중요하다. `.env`를 먼저 고치고 마지막에 한 번만 재기동한다.**
`git pull`만 먼저 하고 재기동하면 아래 1-1 때문에 봇이 뜨지 않는다.

### 1-1. 먼저 기동을 막는 것을 없앤다 — `ALLOWED_CHAT_IDS`

`485b670`부터 **유효한 chat_id가 하나도 없으면 `ConfigurationError`로 기동하지
않는다.** 빈 값을 전체 허용으로 읽던 분기를 없앴기 때문이다(상태가 채팅별로
나뉘어 있지 않아 설정 누락이 곧바로 공개 봇이 된다).

부트스트랩은 클론한 `.env.example`을 그대로 복사하는데, 8/15 시점 그 파일의
해당 줄은 **`ALLOWED_CHAT_IDS=`(빈 값)**이었다. 사람이 그 뒤에 채우지 않았다면
서버는 지금 빈 값이고, 새 코드로 재기동하는 순간 죽는다.

```bash
grep -n '^ALLOWED_CHAT_IDS=' ~/stock_chatbot/.env    # 값이 비어 있으면 채운다
```

숫자가 아닌 값만 있는 경우도 같게 막힌다(자리표시자를 지우지 않은 경우다).
`TELEGRAM_CHAT_ID`와 같은 값을 넣으면 된다. 쉼표로 여러 개도 가능하다.

### 1-2. `.env` 드리프트를 현재 값으로 맞춘다

아래는 추정이 아니다. 부트스트랩이 8/15 `.env.example`을 통째로 복사했고
(`user_data.sh.tftpl`의 `.env` 생성 단계), 그날 그 파일의 값이 왼쪽 열이다.
그 뒤 사람이 손댔을 수 있으니 **눈으로 확인하고 다른 줄만 고친다.**

| 키 | 8/15 배포분 | 현재 값 | 왜 |
|---|---:|---:|---|
| `FEATURES_ENABLED` | `news_prefilter` 없음 | 있음 | 사전선별을 켜야 관측이 시작된다 |
| `NEWS_SOURCE_ARTICLE_LIMIT` | 30 | 250 | 사전선별이 깊이를 CPU로 산다. Neurons는 안 늘어난다 |
| `SCHEDULER_INTERVAL_MINUTES` | 20 | 60 | 한 주기가 보는 후보 폭을 키운다 |
| `NEWS_DIGEST_SEND_LIMIT` | 3 | 2 | 번역 4건 중 2건만 송출 |
| `NEWS_GLOBAL_LIMIT` | 4 | 4 | 그대로 |

```env
FEATURES_ENABLED=instruments,quant,watchlist,news_prefilter,news,market_sentiment,research,briefing,signal_scoring,system_admin,web_admin
NEWS_SOURCE_ARTICLE_LIMIT=250
SCHEDULER_INTERVAL_MINUTES=60
NEWS_DIGEST_SEND_LIMIT=2
```

`NEWS_PREFILTER_MODE`(shadow)와 `NEWS_NIGHT_*`(켜짐, KST 00~07시)는 서버 `.env`에
없고 코드 기본값이 그대로 먹는다 — **없는 키를 새로 넣지 않는다.**
`POLYMARKET_*` 블록도 이 단계에서 손대지 않는다. 작업 3에서 스모크를 통과한
뒤에 켠다.

`NEWS_SOURCE_ARTICLE_LIMIT` 250은 `news_prefilter`가 함께 켜져 있을 때만 쓴다.
둘 중 하나만 올리면 깊이만 커지고 고르는 기준은 그대로다.

### 1-3. pull과 재기동

```bash
cd ~/stock_chatbot && git log -1 --oneline   # 어느 커밋에 서 있는지 먼저 본다
git pull
sudo systemctl restart stock-chatbot
journalctl -u stock-chatbot -f
```

- **재기동 시각은 08:35~10:35를 피한다.** 그 창이 Polymarket 스냅숏의 재시도
  구간이다(작업 3을 켠 뒤부터 해당). KST 07:00 야간 다이제스트 발송도 피한다 —
  그 job이 실패하면 큐가 다음 주간 주기로 넘어간다.
- 기동 로그에 `봇 시작됨. 활성 기능: ...`이 뜨고 목록에 `news_prefilter`가
  들어 있어야 한다.
- 첫 며칠은 `journalctl -u stock-chatbot | grep PREFILTER`로 `중단=budget`이
  매일 나오는지만 본다 — 매일 소진되면 예산이 아니라 관측량을 먼저 줄인다.
  배경 보정은 하루 3.6 CPU-hour 예산 안에서만 돌고, 긴급 뉴스 구간·load average
  1.5 이상에서는 스스로 물러난다.
- 승격 판정은 일주일 뒤 `/system prefilter`로 하고, 기준표는
  `docs/next-steps.md` 2번에 있다.

같은 토큰으로 두 프로세스가 폴링하면 양쪽이 번갈아 죽는다. 로컬 봇은 8/12
이후 꺼져 있다 — 다시 켜지 않는다.

---

## 2. 수집량 확대 후 Neurons 실사용 확인

작업 1이 끝난 뒤에야 의미가 있다. 그 전 로그는 20분 주기·깊이 30의 소비다.

| 구분 | 값 |
|---|---|
| 무료 한도 | 10,000 Neurons/일 (UTC 00시 = KST 09시 리셋) |
| 확대 전 실측 | 하루 272~323건 번역 ≈ 3,000~3,600 |
| 주기 60분 뒤 상한 | 하루 408건 번역 (주간 17주기 × 소스 6곳 × 4건) + 야간 요약 4회 |

**상한이 실측보다 큰 것이 요점이 아니다.** 20분 주기에서는 상한이 발행량보다
훨씬 커서 사실상 발행되는 대로 다 번역했고, 실제 소비는 소스의 발행량이 정했다.
60분 주기에서는 상한이 먼저 걸리므로 실제 소비가 이 표의 값에 가까워진다.
야간 7시간분은 기사별 번역에서 통째로 빠지고(시장당 1회 요약), 사전선별의 재탕
차단이 소스 간 중복까지 걷어낸다 — **얼마나 줄었는지는 아래 절차로 실측한다.**

**절차**

며칠간 로그의 `neurons=` 값을 합산한다. 하루 경계는 UTC 00시(KST 09시)다 —
KST 자정으로 끊어 세면 아침 9시 전 소비가 전날 몫으로 잘못 붙는다.

**서버에서 잰다.** 명령은 `terraform output verify_commands`에 들어 있고, 최근 7일을
UTC 일자별로 한 줄씩 뱉는다(`YYYY-MM-DD <합계>`).

```bash
journalctl -u stock-chatbot --since "$(date -u -d '6 days ago' '+%Y-%m-%d 00:00:00 UTC')" --until "$(date -u -d 'tomorrow' '+%Y-%m-%d 00:00:00 UTC')" -o short-iso-precise --utc --no-pager | awk 'match($0, /neurons=[0-9]+([.][0-9]+)?/) { day = substr($1, 1, 10); total[day] += substr($0, RSTART + 8, RLENGTH - 8) } END { for (day in total) printf "%s %.2f\n", day, total[day] }' | sort
```

**로컬 `bot.log`로는 이 측정을 할 수 없다.** 로그 포맷(`%(asctime)s`)이 호스트 로컬
시각을 오프셋 없이 찍어서 한 줄만 보고 UTC 일자를 복원할 방법이 없다. KST 호스트라는
외부 가정을 얹어야 환산되므로, 판정 근거로는 서버 수치만 쓴다.

**판정과 조치**

- 한도를 넘기면 `NEWS_SOURCE_ARTICLE_LIMIT`부터 내린다. 하루 기사량을 정하는
  상한은 전송 상한(`NEWS_GLOBAL_LIMIT`)이 아니라 이 값이다.
- 소진되면 그날 남은 시간 동안 `/research`와 `/market`이 **막힌다.** 뉴스
  다이제스트만 비는 게 아니다.
- 여유가 크게 남으면 깊이(본문 길이·후보 수)를 먼저 올린다. **깊이는 싸고 수량은
  비싸다** — 기사 1건이 호출 1회이므로 수량은 선형으로 늘어난다.

---

## 3. Polymarket 컨센서스 — 백필 판정 뒤 가동률 확인 (조건부)

### 전제: 즉시 편입은 비권고

Gamma API(`https://gamma-api.polymarket.com`)는 인증이 필요 없고 한국에서
HTTP 200으로 열린다. 기술 통합은 가능하고 LLM 비용도 0이다. 문제는 커버리지다.

실측(2026-08-10, `closed=false` · `volumeNum>=10,000` · `liquidityNum>=1,000` 기준):

| 지역 | 직접 주식·지수 | 거시 프록시 | 독립 이벤트 |
|---|---:|---:|---:|
| 중국 | **0** | 14 | 13 |
| 홍콩 | **0** | 0 | 0 |
| 한국 | **0** | 4 | 3 |
| 미국 | 11 | — | 6 |

홍콩은 유동성 상위가 당일 기온과 정치 마켓이었다. 한국은 북한 침공·Q3 GDP 구간·
한국은행 동결 3건뿐이고 KOSPI나 개별종목 마켓은 없다. 따라서 Polymarket 값은
**개별종목 감성이 아니라 글로벌 거시 위험선호의 외부 참고선**으로만 쓸 수 있다.

### 수집 경로는 2026-08-14에 고쳤다 (운영 상태는 미확인)

원래 구현은 스냅숏을 한 건도 남기지 못했다. 실 API로 확인한 원인이 셋이다.

1. `/markets/keyset` 응답은 레코드를 `markets`에 담는데 파서가 `data`를 봤다.
2. keyset은 커서가 어떤 이름으로도 넘어가지 않고(`limit`은 100에서 잘리고 offset은
   422) 같은 첫 페이지를 되돌려 준다 — 순회가 불가능하다.
3. 거래량 상위는 2028년 만기 계약이 덮고 있어 앞 페이지가 전부 `horizon_too_far`다.

그래서 `/markets` + offset 순회로 바꾸고 `end_date_max`를 서버에 넘긴다. 수정 뒤
실측으로 **계약 24건 / theme 5개 / 이벤트 20개**가 선정된다(승격 기준은 theme 3개,
일 3이벤트).

| 자리 | 파일 |
|---|---|
| Gamma `/markets` 클라이언트·파서 | `app/features/market_sentiment/polymarket.py` |
| 게이트·theme allowlist·polarity | `app/features/market_sentiment/polymarket_rules.py` |
| 08:35 KST 스냅숏 job | `app/features/market_sentiment/snapshot.py` |
| 스냅숏 저장·일별 정렬·게이트 계산 | `app/state/polymarket_consensus.py` |
| 과거 시세 백필(일회성 도구) | `app/features/market_sentiment/polymarket_history.py`, `app/polymarket_backfill.py` |
| 하단 패널 | `app/features/market_sentiment/chart.py` |

설계상 지킨 것(회귀 테스트가 붙어 있으니 바꿀 때 함께 본다):

- 표시 위치는 `/market` **하나만**. 하단에 별도 축·별도 패널로
  `24시간 거시 위험선호 확률변화(pp)`를 그린다.
- 기존 국가별 -1~+1 점수·기사 수·순위에 **합산하지 않는다.** CN/HK/US/KR 선으로
  복제하지도 않는다.
- `/research` 입력과 브리핑 payload에는 넣지 않는다. LLM을 거치지 않으므로
  **추가 Neurons는 0/일**이다.
- 전일·당일에 **같은 conditionId**가 있는 계약만 비교한다. 만료 계약을 다른 slug로
  잇지 않고, 빠진 날을 앞 값으로 채우지 않으며, 같은 날 두 번째 스냅숏은 저장하지
  않는다(08:35 값과 오후 값을 섞으면 일간 변화가 아니다).
- 집계는 계약 → 이벤트 중앙값 → theme 중앙값 → theme 평균으로 접는다. S&P 임계값
  8개짜리 이벤트가 한반도 이벤트 하나보다 8배 세지지 않는다.
- 방향은 명시적 allowlist로만 정한다. **LLM에게 묻지 않는다.** GDP 구간·금리
  결정처럼 국면 의존적인 질문은 제외한다.

### 3-1. 착수 조건: 서버 읽기 스모크

운영 Lightsail은 출구 IP가 달라 **한국 PC에서 열렸다는 사실이 서버 접근을
보장하지 않는다.** Gamma 시장 목록과 CLOB 과거 시세를 둘 다 확인한다(host가
달라 한쪽만 열릴 수 있다).

부트스트랩은 실행 의존성만 설치하므로 서버에는 pytest가 없다. 먼저 받는다.

```bash
cd ~/stock_chatbot
./venv/bin/pip install -r requirements-dev.txt
RUN_POLYMARKET_SMOKE=1 ./venv/bin/python -m pytest -q -m polymarket_smoke
```

- 통과하면 3-2로 간다.
- 서버에서 막히면 **거기서 끝낸다.** 프록시를 붙여 우회하지 않는다 — 우회로를
  유지할 가치가 있는 신호가 아니다. 3-3의 철수 절차를 밟는다.

### 3-2. 수집과 백필을 같은 날 시작해 일주일 뒤 승격

서버 `.env`에 아래 한 줄만 넣고 재기동한다. `POLYMARKET_PANEL_ENABLED`는
`false` 그대로 둔다 — **수집하되 표시하지 않는다.**

```env
POLYMARKET_ENABLED=true
```

같은 날 **서버에서** 백필을 한 번 돌린다. 로컬에서 돌려도 판정은 같지만, 서버
파일이어야 `/system polymarket`이 두 축을 함께 그린다.

```bash
cd ~/stock_chatbot && ./venv/bin/python app/polymarket_backfill.py
```

- 백필이 미달이면 **거기서 끝낸다.** 라이브를 30일 더 봐도 같은 항목이 통과할
  근거는 없다. `POLYMARKET_ENABLED`를 되돌리고 3-3으로 간다.
- 백필이 통과했으면 일주일 뒤 `/system polymarket`의 **최근 7일 스냅숏**이
  6일 이상인지만 확인하고 `POLYMARKET_PANEL_ENABLED=true`로 올린다.
- 스냅숏은 매일 08:35 KST에 찍고, 실패하면 **09:35·10:35에 재시도**한다. 세 번
  모두 놓친 날만 비고, 그날과 다음 날 변화가 계산되지 않는다. 그 이상 늦은
  따라잡기는 **일부러 넣지 않았다**(오후에 찍은 값은 다른 날과 같은 축에 놓을 수
  없다). 정상인 날에는 08:35 값만 남는다 — 그날 스냅숏이 이미 있으면 job이
  조회 없이 곧바로 끝난다.
- 그래도 **08:35~10:35 사이 재시작은 피하는 편이 낫다.** 배포가 필요하면 그
  시간대를 비켜서 한다. 창을 벗어난 재시작은 스냅숏에 영향을 주지 않는다.
- 진행 상황은 `/system polymarket`으로 아무 때나 볼 수 있다. 시스템 상태 화면의
  **🎲 폴리마켓** 버튼(`nav:system:polymarket`)이 같은 보고서를 연다.
- 게이트 임계값(`POLYMARKET_MIN_VOLUME` 등)은 백필과 라이브 사이에 바꾸지
  않는다. 바꾸면 두 표본이 달라져 백필 판정을 라이브에 얹을 수 없다. 그래서
  env가 아니라 `config.py`의 상수다 — 바꾸려면 코드를 고쳐야 하고 git에 남는다.
  env로 남은 Polymarket 키는 `POLYMARKET_ENABLED`·`POLYMARKET_PANEL_ENABLED`
  둘뿐이다.

승격 게이트는 `/system polymarket`과 백필이 같은 코드로 계산한다. 임계값·부등호·
분모가 코드와 이 표에서 일치하는지는 확인했다(6개 전부 일치, 최소 조건 `>=`·
최대 조건 `<=`로 경계 포함, 밀집일 비율의 분모는 30일이 아니라 유효 daily delta 수).

| 게이트 | 기준 | 백필로 판정되나 |
|---|---|---|
| 성공 스냅숏 | 30일 중 24일 이상(80%) | 데이터 유무만. 가동률은 라이브 |
| 유효 daily delta | 24일 이상 | 예 |
| 공통 이벤트 3개 이상인 날 | 유효일의 80% 이상 | 예 |
| 독립 theme | 3개 이상 | 예 |
| 최대 theme 기여도 | 50% 이하 | 예 |
| median spread | 5%p 이하 | 아니오(과거 호가가 없어 오늘 값만) |
| 최근 7일 스냅숏(가동률) | 6일 이상 | 아니오 — 라이브 수집 전용 |

승격한 뒤에는 `/market`을 한 번 호출해 하단 패널이 붙는지, 위 순위·캡션이
그대로인지 눈으로 확인한다.

### 3-3. 실패 시 철수 (하나라도 미달이면)

기준 미달을 "조금만 더 보자"로 넘기지 않는다. 아래를 그대로 실행하고 이 항목을
이 문서에서 지운다.

1. 서버 `.env`에서 `POLYMARKET_*` 전부 제거, 봇 재기동.
2. 서버·로컬의 `data/market_sentiment/polymarket_consensus.json`과
   `polymarket_backfill.json` 삭제.
3. 코드 제거 — 파일 통째 삭제:
   - `app/features/market_sentiment/polymarket.py`
   - `app/features/market_sentiment/polymarket_rules.py`
   - `app/features/market_sentiment/polymarket_history.py`
   - `app/features/market_sentiment/snapshot.py`
   - `app/polymarket_backfill.py`
   - `app/state/polymarket_consensus.py`
   - `tests/test_polymarket_{client,rules,consensus,panel,wiring,history,smoke}.py`
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
