# 다음 작업

로컬에서 할 수 있는 일만 모은다. 끝난 항목은 지운다. 완료된 작업의 기록은 git
이력이 맡는다. **새 목록 파일을 만들지 않는다.**

운영 서버(AWS Lightsail)에 접근해야 진행되는 일은 `docs/aws-next-steps.md`에
따로 있다. 그쪽은 이 작업공간에서 착수할 수 없어 분리했다 — Terraform state,
SSH 개인키, Lightsail IAM 권한이 모두 없다.

## 1. 뉴스 사전선별을 shadow에서 active로 승격할지 판정한다

`news_prefilter`는 번역 전에 원문 후보를 사건 단위로 묶고 점수를 매긴다. 번역
건수는 `NEWS_GLOBAL_LIMIT` 그대로라 **추가 Neurons는 0**이고, 그 대신
`NEWS_SOURCE_ARTICLE_LIMIT`을 30 → 250으로 올려 CPU로 깊이를 산다.

**지금은 `shadow`다.** 점수와 관측만 쌓고 번역 순서는 최신순 그대로다.

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_news_prefilter.py
```

일주일 뒤 `/system prefilter`로 아래를 본다.

| 축 | 무엇을 답하나 | 승격 기준 |
|---|---|---|
| 두 정책의 불일치 | 바꿀 이유가 있는가 | 최신순만·사전선별만이 각각 유의미하게 있어야 한다. 0이면 바꿔도 같은 기사다 |
| 점수 AUC | 점수가 impact를 가르는가 | 0.5(무작위)보다 뚜렷이 높아야 한다 |
| 모델 검증 AP | 보정기가 기저보다 나은가 | `validation_ap` > `validation_prevalence` |
| CPU 예산 | 3.6h/일 안에 들어오는가 | 소진으로 중단되는 날이 없어야 한다 |

**AUC를 "더 나은 기사를 찾는 능력"으로 읽지 않는다.** shadow에서 번역되는 것은
최신순 상위뿐이라 라벨도 거기에만 붙는다. 즉 이 AUC는 *최신순이 이미 고른
기사들 안에서의 순위*다. 사전선별이 새로 끌어올렸을 기사가 실제로 좋았는지는
`active`의 탐색 슬롯이 그 기사를 번역해 봐야 알 수 있다. 같은 경고가
`/system prefilter` 하단과 `service.py`의 `SHADOW_CAVEATS`에 있다.

**판정과 조치**

- 네 축이 모두 통과 → `.env`에 `NEWS_PREFILTER_MODE=active`. 탐색 슬롯 1개가
  번역 슬롯 하나를 임의 깊이 기사에 배정하기 시작하므로, 그 뒤부터 편향 없는
  라벨이 쌓인다. 다시 일주일 뒤 AUC를 재읽는다.
- 불일치가 0에 가까움 → 깊이만 올린 셈이니 `NEWS_SOURCE_ARTICLE_LIMIT`을 되돌리고
  기능을 끈다. 점수가 순서를 못 바꾸면 유지할 값이 없다.
- AUC가 0.5 근처 → active로 올리지 않는다. 가중치를 손보기 전에 어떤 feature가
  실제로 살아 있는지 본다(실측: 종목 매칭은 원문 제목의 8.2%에서만 걸린다).

## 2. Polymarket 승격 게이트를 백필로 판정한다

30일을 기다리는 대신 지난 31일 시세를 지금 읽어 같은 게이트를 돌린다. 봇을
세우거나 `POLYMARKET_ENABLED`를 켤 필요가 없고, 읽기 전용이라 Neurons도 쓰지
않는다.

**여기서 돌리는 것은 판정을 하루라도 빨리 보기 위해서다.** 서버에서는 수집을
켜는 날 백필도 함께 돌린다(`docs/aws-next-steps.md` 3-2) — `/system polymarket`이
두 축을 한 화면에 그리려면 백필 파일이 서버에 있어야 한다. 둘 중 어느 쪽을
먼저 하든 판정 결과는 같다.

```powershell
$env:RUN_POLYMARKET_SMOKE=1; .\venv\Scripts\python.exe -m pytest -q -m polymarket_smoke
.\venv\Scripts\python.exe app\polymarket_backfill.py
```

**스모크를 먼저 통과시킨다.** 백필은 Gamma가 아니라 CLOB(`clob.polymarket.com`)
에서 시세를 읽는데 host가 달라 한쪽이 열렸다고 다른 쪽이 열리지 않고, 응답
봉투는 mock으로 확인되지 않는다. 스모크가 막히면 거기서 끝낸다 — 프록시로
우회하지 않고 `docs/aws-next-steps.md` 3-3의 철수 절차를 밟는다.

결과는 `data/market_sentiment/polymarket_backfill.json`에만 쓴다. 라이브 스냅숏
파일과 섞지 않는다.

**백필이 답하지 못하는 것이 둘 있다.** 지우고 승격하지 않는다.

- median spread는 오늘 선정분으로만 계산된다(과거 호가가 남지 않는다).
- 수집 job이 매일 08:35에 실제로 도는지는 라이브로만 확인된다.

한계의 전체 목록은 `app/features/market_sentiment/polymarket_history.py`
첫머리에 있다. 유동성 게이트가 31일 내내 "오늘의 유동성"으로 적용되는 낙관
편향이 특히 크다 — 통과가 아슬아슬하면 통과로 읽지 않는다.

**판정과 조치**

- 여유 있게 통과 → `docs/aws-next-steps.md` 3-2로 간다(수집을 켜고 백필을 서버에서
  한 번 더 돌린 뒤, 일주일 가동률만 확인하고 패널 승격).
- 미달 → 3-3의 철수 절차를 그대로 밟는다. 라이브로 30일을 더 봐도 같은 항목이
  통과할 근거는 없다.
