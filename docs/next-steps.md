# 다음 작업

앞으로 할 일만 모은다. 끝난 항목은 지운다. 완료된 작업의 기록은 git 이력이 맡는다.
**이 파일이 유일한 할 일 목록이다.** 새 목록 파일을 만들지 않는다.

## 현재 상태

| 축 | 상태 |
|---|---|
| 코드 | 푸시됨. Polymarket 파일럿까지 포함해 테스트 307개·ruff 통과 |
| 운영 서버 `.env` | **확대된 값이 반영되지 않았다.** 코드 푸시로는 전파되지 않는다 |
| Neurons 실사용 | **미측정.** 확대 후 수치는 추정치뿐이다 |
| Polymarket 수집 | 코드는 있고 기본 꺼짐(`POLYMARKET_ENABLED=false`) |

## 실행 순서

작업 1과 2는 서로 얽혀 있다. **2(서버 반영)를 먼저 하고 1(실측)을 그 위에서 재야**
확대된 설정의 실제 소비를 보는 것이 된다. 3은 1의 결과가 무해함을 확인한 뒤에
켠다 — 한도가 이미 빠듯하면 새 수집을 얹을 때가 아니다(다만 Polymarket 자체는
Neurons를 쓰지 않는다). 4는 언제 해도 되지만 지금은 보류다.

```
2. 서버 .env 반영  →  1. Neurons 실측(며칠)  →  3. Polymarket 파일럿(30일)  →  판정
                                                4. 환경변수 축소(보류)
```

---

## 1. 수집량 확대 후 Neurons 실사용 확인

주기를 20분으로 늘리고 수집·분석 깊이를 키운 뒤의 소비량은 아직
**추정치일 뿐 실측이 아니다.**

| 구분 | 값 |
|---|---|
| 무료 한도 | 10,000 Neurons/일 (UTC 00시 = KST 09시 리셋) |
| 확대 전 실측 | 하루 272~323건 번역 ≈ 3,000~3,600 |
| 확대 후 추정 | 7,000~8,000 (뉴스 5,000~6,000 + 리서치·브리핑·`/market` 1,700) |

**절차**

며칠간 로그의 `neurons=` 값을 합산한다. 하루 경계는 UTC 00시(KST 09시)다 —
KST 자정으로 끊어 세면 아침 9시 전 소비가 전날 몫으로 잘못 붙는다.

```bash
# 서버
journalctl -u stock-chatbot | grep neurons=
# 로컬 (로그는 파일이 아니라 표준 오류로 나간다)
python app\bot.py 2> bot.log
```

**판정과 조치**

- 한도를 넘기면 `NEWS_SOURCE_ARTICLE_LIMIT`부터 내린다. 하루 기사량을 정하는
  상한은 전송 상한(`NEWS_GLOBAL_LIMIT`)이 아니라 이 값이다.
- 소진되면 그날 남은 시간 동안 `/research`와 `/market`이 **막힌다.** 뉴스
  다이제스트만 비는 게 아니다.
- 여유가 크게 남으면 깊이(본문 길이·후보 수)를 먼저 올린다. **깊이는 싸고 수량은
  비싸다** — 기사 1건이 호출 1회이므로 수량은 선형으로 늘어난다.

---

## 2. 운영 서버(Lightsail)에 설정 반영

`.env`는 `.gitignore` 대상이라 **코드를 푸시해도 서버에 전파되지 않는다.**
확대된 값(주기 20분, fetch 깊이 20, 리서치 입력 16건×600자 등)을 서버 `.env`에
직접 반영해야 한다.

- 절차는 `iac/terraform/README.md`가 유일한 배포 문서다.
- 같은 토큰으로 두 프로세스가 폴링하면 양쪽이 번갈아 죽는다.
  **로컬 정지 → 서버 기동** 순서를 지킨다.
- 반영 대상은 `.env.example`과 서버 `.env`의 차분이다. 이번에 추가된
  `POLYMARKET_*` 블록은 이 단계에서 **넣지 않는다.** 작업 3에서 스모크를 통과한
  뒤에 켠다.

---

## 3. Polymarket 컨센서스 — 30일 섀도 파일럿 (조건부)

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

### 코드는 들어와 있다 (섀도 상태)

구현은 끝났고 기본값은 수집·표시 모두 꺼짐이다. 코드를 다시 쓸 일은 없고,
남은 건 **서버에서 켜고 30일 관찰한 뒤 승격 여부를 판정하는 운영**이다.

| 자리 | 파일 |
|---|---|
| Gamma keyset 클라이언트·파서 | `app/features/market_sentiment/polymarket.py` |
| 게이트·theme allowlist·polarity | `app/features/market_sentiment/polymarket_rules.py` |
| 08:35 KST 스냅숏 job | `app/features/market_sentiment/snapshot.py` |
| 스냅숏 저장·일별 정렬·게이트 계산 | `app/state/polymarket_consensus.py` |
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

### 3-1. 서버 읽기 스모크 (착수 조건)

운영 Lightsail은 출구 IP가 달라 **한국 PC에서 열렸다는 사실이 서버 접근을
보장하지 않는다.** 켜기 전에 서버에서 한 번 돌린다.

```bash
RUN_POLYMARKET_SMOKE=1 python -m pytest -q -m polymarket_smoke
```

- 통과하면 3-2로 간다.
- 서버에서 막히면 **거기서 끝낸다.** 프록시를 붙여 우회하지 않는다 — 우회로를
  유지할 가치가 있는 신호가 아니다. 3-4의 철수 절차를 밟는다.

### 3-2. 30일 섀도 운영

서버 `.env`에 아래 한 줄만 넣는다. `POLYMARKET_PANEL_ENABLED`는 `false` 그대로
둔다 — **수집하되 표시하지 않는다.**

```env
POLYMARKET_ENABLED=true
```

- 스냅숏은 매일 08:35 KST에 찍힌다. 봇이 그 시각에 내려가 있던 날은 스냅숏이
  비고, 그날과 다음 날 변화가 계산되지 않는다. 따라잡기 수집은 **일부러 넣지
  않았다**(오후에 찍은 값은 다른 날과 같은 축에 놓을 수 없다).
- 그래서 이 기간에는 **08:35 전후 재시작을 피한다.** 배포가 필요하면 그 시각을
  비켜서 한다.
- 진행 상황은 `/system polymarket`으로 아무 때나 볼 수 있다.
- 게이트 임계값(`POLYMARKET_MIN_VOLUME` 등)은 파일럿 도중에 바꾸지 않는다.
  바꾸면 앞뒤 기간의 표본이 달라져 30일을 한 창으로 볼 수 없다.

### 3-3. 승격 판정

`/system polymarket`이 아래를 계산해 보여 준다. **모두 통과할 때만**
`POLYMARKET_PANEL_ENABLED=true`로 올린다.

| 게이트 | 기준 |
|---|---|
| 성공 스냅숏 | 30일 중 24일 이상(80%) |
| 유효 daily delta | 24일 이상 |
| 공통 이벤트 3개 이상인 날 | 유효일의 80% 이상 |
| 독립 theme | 3개 이상 |
| 최대 theme 기여도 | 50% 이하 |
| median spread | 5%p 이하 |

승격한 뒤에는 `/market`을 한 번 호출해 하단 패널이 붙는지, 위 순위·캡션이
그대로인지 눈으로 확인한다.

### 3-4. 실패 시 철수 (하나라도 미달이면)

기준 미달을 "조금만 더 보자"로 넘기지 않는다. 아래를 그대로 실행하고 이 항목을
이 문서에서 지운다.

1. 서버 `.env`에서 `POLYMARKET_*` 전부 제거, 봇 재기동.
2. 서버 `data/market_sentiment/polymarket_consensus.json` 삭제.
3. 코드 제거 — 파일 통째 삭제:
   - `app/features/market_sentiment/polymarket.py`
   - `app/features/market_sentiment/polymarket_rules.py`
   - `app/features/market_sentiment/snapshot.py`
   - `app/state/polymarket_consensus.py`
   - `tests/test_polymarket_{client,rules,consensus,panel,wiring,smoke}.py`
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

---

## 4. 환경변수 축소 (보류, 재개 시 참고)

한 번 시도했다가 원복했다. 재개할 때 쓸 근거만 남긴다.

- `.env.example` 기준 100개 중 **반드시 채워야 하는 건 텔레그램 2 + Cloudflare 2,
  총 4개뿐이다.** 나머지는 모두 코드에 기본값이 있다(Polymarket 8개를 더한 뒤의
  수치이며, 파일럿을 철수하면 92개로 돌아간다).
- 불리언 플래그 중 최소 4개는 `FEATURES_ENABLED`와 중복이고,
  **중복된 쪽이 더 나쁜 상태를 만든다.** `false`로 두면 기능이 꺼지는 게 아니라
  명령과 메뉴는 남은 채 동작만 실패한다.

| 플래그 | `false`로 두면 |
|---|---|
| `STOCK_DB_ENABLED` | DB는 비었는데 `/stockdb` 명령·메뉴는 그대로 노출 |
| `QUANT_CONTEXT_ENABLED` | `QuoteService`가 껍데기로 생성 |
| `RESEARCH_ANALYSIS_ENABLED` | `/research run` 할 때마다 실패 |
| `MARKET_DIGEST_ENABLED` | `/market`이 분석기 준비 안 됨으로 실패 |

- 지금은 넷 다 `true`라 실제 영향은 없다. 끌 일이 생기면 이 플래그 대신
  `FEATURES_ENABLED`에서 기능 키를 빼는 쪽이 맞다.
- `POLYMARKET_ENABLED`/`POLYMARKET_PANEL_ENABLED`는 이 중복에 해당하지 않는다.
  수집과 표시를 따로 끊는 것이 섀도 파일럿의 요건이고, 파일럿이 끝나면 둘 다
  사라진다.
- 재개한다면 **중복 플래그 제거만 먼저** 하는 편이 안전하다. 상수 이관까지 한 번에
  하면 `QuoteService`의 8개 분기를 포함해 20개 파일이 함께 움직인다.
