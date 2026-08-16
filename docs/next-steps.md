# 다음 작업

로컬에서 할 수 있는 일만 모은다. 끝난 항목은 지운다. 완료된 작업의 기록은 git
이력이 맡는다. **새 목록 파일을 만들지 않는다.**

운영 서버(AWS Lightsail)에 접근해야 진행되는 일은 `docs/aws-next-steps.md`에
따로 있다. 그쪽은 이 작업공간에서 착수할 수 없어 분리했다 — Terraform state,
SSH 개인키, Lightsail IAM 권한이 모두 없다.

## 1. Polymarket 승격 게이트를 백필로 판정한다

30일을 기다리는 대신 지난 31일 시세를 지금 읽어 같은 게이트를 돌린다. 봇을
세우거나 `POLYMARKET_ENABLED`를 켤 필요가 없고, 읽기 전용이라 Neurons도 쓰지
않는다.

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

- 여유 있게 통과 → `docs/aws-next-steps.md` 3-2로 간다(수집만 켜고 일주일,
  가동률만 확인한 뒤 패널 승격).
- 미달 → 3-3의 철수 절차를 그대로 밟는다. 라이브로 30일을 더 봐도 같은 항목이
  통과할 근거는 없다.
