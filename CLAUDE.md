# Stock Chatbot 개발 가이드

개인 운영용 Telegram 주식 봇이다. 중국·홍콩·미국·한국 뉴스, 종목 DB,
관심종목, 시장 감성, 리서치, 브리핑을 제공한다. 현재 데이터 형식과 현재 설정만
지원하며 과거 형식 마이그레이션이나 비활성 대체 경로를 추가하지 않는다.

## 실행과 검증

```powershell
.\venv\Scripts\python.exe app\bot.py
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m ruff check app tests
```

- Python 3.11+, `requirements.txt`, 개발 도구는 `requirements-dev.txt`.
- `app/`가 import root다. 내부 import는 `from core...`, `from news...` 형식을 쓴다.
- 테스트는 외부 API를 mock하며 Cloudflare smoke test는 기본 제외다.
- 파일 수정 뒤 관련 테스트와 전체 pytest를 실행한다.

## 구조

```text
app/bot.py             조립, Telegram 앱, 스케줄러
app/core/              설정, 런타임, 워커
app/features/          기능 등록과 명령 핸들러
app/handlers/          콜백 라우팅, 메뉴 구성, 인라인 네비게이션
app/news/              소스, 수집 파이프라인, 야간 다이제스트, 감성
app/llm/               Cloudflare 백엔드와 분석기
app/research/          뉴스 수집, 후보 발굴, 리서치 실행
app/briefing/          브리핑 생성과 A주 거래일 캘린더
app/stocks/            종목 DB와 시세
app/state/             발송·뉴스·시장 감성 상태
app/watchlist/         관심종목 상태
app/webadmin/          관리 웹 대시보드
prompts/               모델 프롬프트
iac/terraform/         Lightsail 배포
tests/                 자동화 테스트
```

기능 카탈로그 순서는 의존 순서다. `FeatureSpec`을 추가할 때 명령, 메뉴,
callback, persistent label을 한 곳에서 등록하고 `FEATURES_ENABLED` 기본값과
`.env.example`을 함께 갱신한다.

## 현재 동작 가정

- 뉴스 주기마다 `NEWS_GLOBAL_SOURCES`와 RSS 소스를 모두 실행한다. 주기는 60분이다.
  짧게 돌리면 번역 슬롯이 늘 최신순 상위로 채워져 같은 사건을 하루에 몇 번씩
  번역한다 — 텀을 늘려 한 주기가 보는 후보 폭을 키우고 그 안에서 고른다.
- **KST 00~07시에는 기사별 번역을 하지 않는다.** 그 시간의 주기는 원문만
  `night_queue.json`에 모으고(`collect_night_articles`), 07시에 시장별로 한 번씩만
  LLM을 불러 묶음 요약을 보낸다(`send_night_digest`). 자는 7시간을 기사별로
  번역하면 소스 6곳 × 시간당 4건 = 168 호출인데 아침에 읽는 내용은 그만큼 늘지
  않는다. 큐에 담긴 기사는 이미 예약(`reserve`)되어 있고 다이제스트를 보낸 뒤
  확정하므로, 주간 주기가 같은 기사를 다시 번역하지 않는다. 아침 첫 주간 주기가
  큐가 비어 있는지 먼저 확인한다 — 07시 job이 실패했거나 그때 봇이 꺼져 있었어도
  야간 뉴스를 통째로 잃지 않는다.
- **번역 건수와 송출 건수는 다르다.** 한 주기에 소스당 `NEWS_GLOBAL_LIMIT`건을
  번역하고, 그중 `NEWS_DIGEST_SEND_LIMIT`건만 묶어 보낸다. 선별 기준은 impact가
  1순위, 같으면 감성의 세기, 그래도 같으면 최신순이다(`select_digest_rows`).
  **탈락분을 release하지 않는다** — release하면 다음 주기에 같은 기사를 다시
  번역해 Neurons만 태운다. 확정하고 `news_log`·`prediction_log`에는 그대로 남겨
  `/view`·`/market`·signal_scoring이 읽게 한다(`archive_unsent_articles`).
- **기사 본문은 200자 내외이고 상한을 두 곳에서 지킨다.** `prompts/global_ko.txt`가
  180~220자를 지시하고, `format_digest_article`이 표시 직전에
  `NEWS_DIGEST_ARTICLE_MAX_CHARS`·`NEWS_DIGEST_TITLE_MAX_CHARS`로 다시 자른다.
  프롬프트만 믿지 않는다 — 모델이 길게 답하는 주기가 섞이면 한 주기에 올라오는
  총량이 예측 불가능해지고 채팅을 읽을 수 없다. 자르는 순서는 **절단 뒤
  escape**다(뒤집으면 `&amp;`가 끊겨 메시지 전체가 파싱 오류로 거부된다).
  본문은 상한 안의 **마지막 문장 끝**에서 자른다(`truncate_at_sentence`) —
  글자로 끊으면 반 문장이 남아 무슨 말인지 알 수 없다. 경계가 상한의 절반도
  안 되면 버리는 쪽이 많아지므로 그때만 글자 절단으로 돌아간다.
  본문 길이를 되돌릴 때는 `TRANSLATION_NUM_PREDICT`도 함께 본다.
- **번역 결과의 품질을 표시 전에 검사한다.** 봉투가 맞아도 모델이 원문을 그대로
  돌려주거나 제목을 되풀이하는 주기가 있다. `TranslationService._check_quality`가
  본문 길이·제목 반복·한글 비율을 보고 `TranslationQualityError`로 거른다.
  형식 오류와 타입이 갈리는 이유는 처리가 달라서다 — 형식 오류는 release해
  다시 시도하지만, 품질 미달은 같은 원문에 같은 응답이 다시 오므로 **확정**해
  매 주기 같은 기사에 Neurons를 태우지 않는다. 한 소스가 한 주기에 헛도는
  건수는 `NEWS_TRANSLATION_QUALITY_REJECT_LIMIT`에서 끊는다.
- **하루 번역량은 "주간 주기 수 × `NEWS_GLOBAL_LIMIT`"과 소스 발행량 중 작은 쪽이다.**
  20분 주기에서는 상한이 발행량보다 훨씬 커서 사실상 발행되는 대로 다 번역했다.
  60분 주기에서는 상한(주간 17주기 × 소스 6곳 × 4건 = 408건)이 먼저 걸리므로,
  **무엇을 고르는지가 비로소 의미를 갖는다.**
- **읽는 폭은 `NEWS_SOURCE_ARTICLE_LIMIT`가 정한다.** 소스를 이 깊이까지만 읽으므로
  여기서 잘린 기사는 다음 주기에도 보이지 않는다. 주기가 3배로 길어져 한 주기가
  덮어야 할 시간도 3배다 — 이 값을 내리면 그만큼 사각지대가 생긴다.
  `gnews`는 이 값을 시장 수로, `gnews_us`·`gnews_kr`은 질의 수로 다시 나눠 쓴다.
- **같은 사건을 두 번 번역하지 않는다.** 사전선별이 번역 전에 세 가지를 후보에서
  뺀다: 최근 `NEWS_PREFILTER_TRANSLATED_EVENT_COOLDOWN_HOURS` 안에 이미 번역한
  사건, 이번 주기에 다른 소스가 이미 집은 사건, 같은 소스 안의 같은 사건이다.
  소스 여섯 곳이 같은 발표를 옮겨 적는 것이 한 주기의 가장 흔한 중복이다.
  이것은 **순서를 바꾸는 일이 아니라 빼는 일이라** shadow/active 어느 쪽에서도
  똑같이 돈다 — 두 정책이 걸러진 뒤의 같은 풀에서 고르므로 섀도 비교의 baseline은
  그대로다. 무엇이 왜 빠졌는지는 주기별 `cycle` 관측 줄의 `gated_*`가 센다.
- **`news_prefilter`는 넓게 읽는 비용을 CPU로 내고 Neurons는 그대로 둔다.**
  번역 전에 원문 후보를 사건 단위로 묶고 점수를 매겨, 번역 대상을 "최신순
  상위 N건"에서 "점수 상위 N건"으로 바꾼다. 번역 건수는 `NEWS_GLOBAL_LIMIT`
  그대로라 **추가 Neurons는 0이다** — 그래서 `NEWS_SOURCE_ARTICLE_LIMIT`을 250까지
  올릴 수 있다. LLM을 부르지 않고 Aho-Corasick 종목 매칭·simhash 사건 군집·
  로컬 로지스틱 보정기만 쓴다.
- **사전선별은 `shadow`로 시작하고 `/system prefilter`가 승격 근거를 그린다.**
  shadow는 점수와 관측만 쌓고 번역 순서는 최신순 그대로 둔다. **shadow가
  답하지 못하는 것이 있다**: 라벨(impact)은 번역된 기사에만 붙고 shadow에서
  번역되는 것은 최신순 상위뿐이라, 사전선별이 새로 끌어올렸을 기사의 impact는
  끝내 관측되지 않는다. 따라서 shadow의 AUC는 "최신순이 이미 고른 기사들
  안에서의 순위"이지 "더 나은 기사를 찾아내는 능력"이 아니다. 후자는 `active`의
  탐색 슬롯(`NEWS_PREFILTER_EXPLORATION_SLOTS`)으로만 측정된다. 이 한계는
  `service.py`의 `SHADOW_CAVEATS`에 적어 두었고 지운 채로 승격하지 않는다.
- **관측 파일은 두 정책이 고르는 기사와 탐색분만 남긴다.** 후보 250건을 전부
  적으면 하루 수만 줄이 쌓이는데 라벨은 번역된 4건에만 붙어 나머지는 학습에
  쓸 수 없다. 남기지 않는 후보는 주기별 `cycle` 집계 줄로 센다.
  적재는 **offset 뒤만 이어 읽는다** — 파일 전체를 dict에 담으면 보존 기간이
  찬 시점에 1GB 인스턴스가 감당하지 못한다(실측: 2일치 221k줄에서 602MB).
- **Neurons 예산은 뉴스 번역이 대부분을 쓴다**(기사 1건 = 호출 1회). 리서치·브리핑·
  `/market`·야간 다이제스트는 하루 15회 남짓이라 입력을 깊게 잡아도 총량에 거의
  영향이 없다. 수량을 늘릴 때만 무료 한도(하루 10,000)를 다시 계산한다.
  **깊이는 싸고 수량은 비싸다** — 야간을 시장당 1회 요약으로 바꾼 것이 이 규칙을
  그대로 적용한 결과다.
- 일반 뉴스는 번역하지만 리서치 입력은 원문을 사용한다.
- 리서치 후보는 관심종목, 원문 종목명 매칭, 중화권 섹터, 미국 스크리너,
  한국 등락률에서 만든다. 분석 action은 `add`, `remove`, `watch`만 허용한다.
- 리서치 상태는 `history`, `sight`, `updated_at`, `last_result` 형식만 읽고 쓴다.
  `history`는 다음 분석 프롬프트에 들어가는 **압축본**이고, `last_result`는
  `/research show`가 실행 직후와 같은 화면을 다시 그리기 위한 **마지막 전체
  결과**다. 쓰임이 달라 합치지 않는다 — 합치면 프롬프트가 비대해지거나 show가
  얇아진다. 주제를 바꾸거나 지우면 둘 다 비운다.
- 관심종목과 발송 이력도 현재 JSON 형식만 지원한다.
- `/market`은 기사별 번역 대신 시장·일자별 헤드라인 다이제스트를 분석한다.
  완료된 과거 일자는 저장 결과를 재사용하고 오늘만 다시 계산한다.
- **Polymarket 컨센서스는 기본 꺼짐(`POLYMARKET_ENABLED=false`)인 섀도 파일럿이다.**
  `market_sentiment`의 외부 소스이지 별도 기능 키가 아니다. 값은 거시 위험선호
  확률변화(pp)라 국가별 -1~+1 감성 점수와 축이 다르다 — 합산하거나 순위·리서치
  입력·브리핑 payload에 넣지 않고 `/market` 하단 별도 패널에만 그린다. 방향은
  `polymarket_rules.py`의 명시적 allowlist로만 정하고 LLM에 묻지 않는다.
  판정 근거는 `/system polymarket`이 계산한다. 자세한 규약은 `docs/server-ops.md`.
- **승격 판정은 30일을 기다리지 않는다.** `app/polymarket_backfill.py`가 CLOB
  과거 시세로 지난 31일 스냅숏을 소급 작성해 같은 게이트를 돌린다. 결과는
  `polymarket_backfill.json`에 따로 쓰고 라이브 스냅숏과 섞지 않는다 — 백필에는
  과거 호가가 없고 수량 게이트가 조회 시점 값으로 적용돼 있다. 백필로 답할 수
  없는 두 가지(median spread, job 가동률)는 `polymarket_history.py` 첫머리에
  적어 두었고, 지운 채로 승격하지 않는다.
- **수집과 백필은 같이 돌린다.** 승격 조건은 백필 게이트 전부 통과 **그리고**
  최근 7일 중 6일 스냅숏이다. 서로를 대신하지 못한다 — 백필은 지표의 실질을
  하루에 판정하지만 job이 매일 도는지는 모르고, 라이브는 그 반대다.
  `/system polymarket`이 두 축을 한 화면에 그린다.
- 종목 canonical code는 시장마다 형식이 다르다. CN·HK는 **접두사 없는 숫자 코드**
  (`600519`, `00700`)이고, US·KR만 `US:NASDAQ:AAPL`·`KR:KOSPI:005930` 형식이다
  (`stocks/universe.py`의 `stock_key`). KR 6자리는 A주 코드와 겹치므로 US·KR에만
  거래소를 붙인다 — 코드 문자열만으로 시장을 단정하지 않는다.

## 변경 원칙

- 환경 변수는 `app/core/config.py`에서만 읽고 `.env.example`에 현재 키를 기록한다.
  운영자가 조정하지 않는 설정은 같은 모듈의 리터럴 상수로 둔다.
- **배경 CPU 작업(보정)은 예산 안에서만 돈다. 매 주기 필수인 foreground
  작업은 예산으로 재지 않는다.** 사전선별의 매 주기 후보 점수화(foreground)는
  이 기능을 쓰는 한 피할 수 없는 비용이라 텔레그램·뉴스 긴급 경로와
  마찬가지로 무제한으로 둔다. 예산(`NEWS_PREFILTER_CALIBRATION_DAILY_BUDGET_SECONDS`)은
  보정(calibration)만 재는 하루 총량이고, `foreground_cpu_seconds`는 관측만
  하지 이 값을 깎지 않는다 — 둘을 한 풀에서 같이 깎던 예전 구조에서는
  foreground만으로 하루치를 다 써 보정이 한 번도 못 도는 굶주림이 있었다
  (실측: trial 0 · 남은 예산 0.00h로 매번 중단). 순간 부하(버스트)는 이
  예산이 아니라 보정 조각의 실행 주기·회당 CPU·조각 단위
  (`NEWS_PREFILTER_MAINTENANCE_*`)가 낮게 누른다 — 1분마다 최대 15초 페이스면
  보정 자체의 하루 이론상 최대치가 1,440회 × 15초 = 6.0h라, 예산(6.0h)이
  실제 상한으로 걸린다(1분·10초 페이스는 실측(2026-08-22)에서 매 주기가
  슬라이스를 꽉 채우고 urgent 정지가 드물어 일감 부족이 아니라 페이스
  자체가 병목임을 확인한 뒤 1.5배로 올렸다). 조각마다
  `wait_for_urgent_idle`·load average·남은 예산을 다시
  확인해 오래 가로막지 않는다. Lightsail `micro_3_0`(2 vCPU, vCPU당
  baseline 10% = 하루 4.8 vCPU-hour)의 `NEWS_PREFILTER_LIGHTSAIL_*` 상수는
  참고치일 뿐 위 계산에 관여하지 않는다.
- **15초 페이스를 매일 쓰면 관측 총사용률이 baseline 위에 계속 머물러
  버스트 크레딧을 쓰기만 한다**(실측 2026-08-23: 12%). Lightsail 크레딧
  잔량은 API로 못 읽으므로(`GetInstanceMetricData`가 IAM에서 막혀 있다)
  코드가 남은 크레딧을 보고 스스로 조절할 수 없다. 그래서
  `run_prefilter_maintenance`(`features/news_prefilter/feature.py`)가
  `today()` 날짜 홀짝으로 이틀에 하루는 충전일로 강제한다 — 그날은 슬라이스를
  `NEWS_PREFILTER_MAINTENANCE_RECHARGE_SLICE_SECONDS`(4초, baseline을 확실히
  밑도는 값)로 낮춰 순 충전이 나게 하고, 나머지 하루는 평소 15초로 쓴다.
  이 이틀 주기는 시작점일 뿐이다 — Lightsail 콘솔의 실제 burst capacity
  그래프가 계속 내려가면 충전일을 늘리고, 여유가 쌓이기만 하면 지출일을
  늘린다.
- 상태 파일은 `data/<feature>/`에 둔다. 설정은 상태 파일에 저장하지 않는다.
- **상태 파일은 `core/storage.py`의 원자적 쓰기로만 저장한다.** 대상 파일을 직접
  열어 쓰면 그 순간 내용이 비고, 실패하면 잘린 JSON이 남아 다음 기동이 상태를
  통째로 잃는다. 저장 실패를 로그로 삼키지 않는다 — 호출자가 반환값으로 판단하는
  것(스냅숏을 남겼는가, 관심종목이 저장됐는가)이 있어서, 실패를 성공으로 보고하면
  사라진 줄 모르는 상태가 된다. 메모리는 저장에 성공한 뒤에 바꾸거나 되돌린다.
- **`ALLOWED_CHAT_IDS`가 비면 기동하지 않는다.** 빈 목록을 전체 허용으로 읽는
  분기를 되살리지 않는다 — 상태가 채팅별로 나뉘어 있지 않아 설정 누락이 곧바로
  공개 봇이 된다. 오타로 유효한 ID가 남지 않은 경우도 같게 막는다.
- 번역·분석·브리핑은 Cloudflare Workers AI만 사용한다. 비밀값은 `.env`에만 두고
  로그나 예외에 포함하지 않는다.
- LLM JSON은 필수 필드를 엄격히 검사하고 현재 응답 envelope만 처리한다.
- 외부 소스 하나의 실패가 전체 뉴스 주기를 중단시키지 않도록 소스 단위로 격리한다.
- 새 호환 분기, 사용하지 않는 설정 플래그, 중복 helper를 만들지 않는다.
- **문서는 절차서 하나, 배포서 하나, 그리고 계획서뿐이다. 그 외 새 목록 파일을
  만들지 않는다.** `docs/server-ops.md`는 이미 떠 있는 서버를 상대로 반복하는
  **절차서**다(접속·배포·설정·실측·판정·백업·장애). 절차이므로 항목이 끝나도
  지우지 않는다. 인스턴스 생성·최초 전환·삭제는 `iac/terraform/README.md`에만 있다.
  나머지는 **계획서**이고 항목이 끝나면 지운다 — 완료 기록은 git 이력이 맡는다.
  현재 계획서는 둘이다: `docs/polymarket-web.md`(리서치·시장 컨센서스의 웹 서비스화,
  세력 행동 추정, 미 대통령 게시물 추적)와 `docs/market-anomaly.md`(시장 감성을
  추세에서 이상 탐지로 바꾸기). **계획서를 새로 파는 것은 주제가 기존 계획서와
  독립일 때뿐이고, 다 끝나면 파일째 지운다.** 종류를 섞지 않는다: 절차서에 할 일을
  적으면 끝난 일이 남고, 계획서에 절차를 적으면 계획을 지울 때 절차까지 사라진다.
- 모듈은 한 책임을 유지하되 한두 함수만 담는 무의미한 파일 분할은 피한다.
- **시각은 `core/clock.py`의 `now()`·`today()`만 쓴다.** `datetime.now()`·`date.today()`는
  호스트 타임존을 따라가서 서버를 다른 타임존에 올리면 `/market`의 하루 경계와 보존
  기간이 통째로 밀린다. ruff의 `DTZ` 규칙이 이걸 막는다(테스트는 예외).
  저장된 타임스탬프를 `now()`와 비교할 때는 `ensure_kst()`로 감싼다 — aware 전환
  이전에 쓴 `data/` 파일에는 오프셋이 없어 그냥 비교하면 TypeError로 죽는다.
  예외는 셋뿐이다: Cloudflare 할당량 리셋은 UTC 00시 기준이고
  (`llm/backends.py`), 기사 시각은 소스 타임존을 `news/utils.py`가 KST로 변환하며,
  사전선별의 하루 CPU 예산도 Neurons와 같은 UTC 00시에 리셋한다
  (`features/news_prefilter/service.py`) — 두 예산의 경계를 맞춰 두면 한쪽이
  소진된 날을 다른 쪽 로그와 같은 일자로 읽을 수 있다.

## 배포

Lightsail 운영 절차는 `iac/terraform/README.md`가 유일한 배포 문서다. 부트스트랩은
봇을 자동 기동하지 않는다. 동일 Telegram 토큰의 중복 polling을 피하도록 로컬을
정지한 뒤 서버를 기동한다.
