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
app/news/              소스, 수집 파이프라인, 감성
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

- 뉴스 주기마다 `NEWS_GLOBAL_SOURCES`와 RSS 소스를 모두 실행한다. 주기는 20분이다.
- **번역 건수와 송출 건수는 다르다.** 한 주기에 소스당 `NEWS_GLOBAL_LIMIT`건을
  번역하고, 그중 `NEWS_DIGEST_SEND_LIMIT`건만 묶어 보낸다. 선별 기준은 impact가
  1순위, 같으면 감성의 세기, 그래도 같으면 최신순이다(`select_digest_rows`).
  **탈락분을 release하지 않는다** — release하면 다음 주기에 같은 기사를 다시
  번역해 Neurons만 태운다. 확정하고 `news_log`·`prediction_log`에는 그대로 남겨
  `/view`·`/market`·signal_scoring이 읽게 한다(`archive_unsent_articles`).
- **하루 기사 수량을 정하는 상한은 번역 상한이 아니라 `NEWS_SOURCE_ARTICLE_LIMIT`다.**
  소스를 이 깊이까지만 읽으므로 여기서 잘린 기사는 다음 주기에도 보이지 않는다.
  `gnews`는 이 값을 시장 수로, `gnews_us`·`gnews_kr`은 질의 수로 다시 나눠 쓴다.
- **Neurons 예산은 뉴스 번역이 대부분을 쓴다**(기사 1건 = 호출 1회). 리서치·브리핑·
  `/market`은 하루 10회 남짓이라 입력을 깊게 잡아도 총량에 거의 영향이 없다.
  수량을 늘릴 때만 무료 한도(하루 10,000)를 다시 계산한다.
- 일반 뉴스는 번역하지만 리서치 입력은 원문을 사용한다.
- 리서치 후보는 관심종목, 원문 종목명 매칭, 중화권 섹터, 미국 스크리너,
  한국 등락률에서 만든다. 분석 action은 `add`, `remove`, `watch`만 허용한다.
- 리서치 상태는 `history`, `sight`, `updated_at` 형식만 읽고 쓴다.
- 관심종목과 발송 이력도 현재 JSON 형식만 지원한다.
- `/market`은 기사별 번역 대신 시장·일자별 헤드라인 다이제스트를 분석한다.
  완료된 과거 일자는 저장 결과를 재사용하고 오늘만 다시 계산한다.
- **Polymarket 컨센서스는 기본 꺼짐(`POLYMARKET_ENABLED=false`)인 섀도 파일럿이다.**
  `market_sentiment`의 외부 소스이지 별도 기능 키가 아니다. 값은 거시 위험선호
  확률변화(pp)라 국가별 -1~+1 감성 점수와 축이 다르다 — 합산하거나 순위·리서치
  입력·브리핑 payload에 넣지 않고 `/market` 하단 별도 패널에만 그린다. 방향은
  `polymarket_rules.py`의 명시적 allowlist로만 정하고 LLM에 묻지 않는다.
  판정 근거는 `/system polymarket`이 계산한다. 자세한 규약은 `docs/aws-next-steps.md`.
- 종목 canonical code는 시장마다 형식이 다르다. CN·HK는 **접두사 없는 숫자 코드**
  (`600519`, `00700`)이고, US·KR만 `US:NASDAQ:AAPL`·`KR:KOSPI:005930` 형식이다
  (`stocks/universe.py`의 `stock_key`). KR 6자리는 A주 코드와 겹치므로 US·KR에만
  거래소를 붙인다 — 코드 문자열만으로 시장을 단정하지 않는다.

## 변경 원칙

- 환경 변수는 `app/core/config.py`에서만 읽고 `.env.example`에 현재 키를 기록한다.
- 상태 파일은 `data/<feature>/`에 둔다. 설정은 상태 파일에 저장하지 않는다.
- 번역·분석·브리핑은 Cloudflare Workers AI만 사용한다. 비밀값은 `.env`에만 두고
  로그나 예외에 포함하지 않는다.
- LLM JSON은 필수 필드를 엄격히 검사하고 현재 응답 envelope만 처리한다.
- 외부 소스 하나의 실패가 전체 뉴스 주기를 중단시키지 않도록 소스 단위로 격리한다.
- 새 호환 분기, 사용하지 않는 설정 플래그, 중복 helper를 만들지 않는다.
- 앞으로 할 일은 두 파일에만 모은다. 항목이 끝나면 지운다. 로컬 작업은
  `docs/next-steps.md`, 운영 서버에 접근해야 하는 작업은 `docs/aws-next-steps.md`다.
  서버 쪽은 이 작업공간에서 착수할 수 없어 분리해 두었다 — 섞으면 로컬에서
  손댈 수 있는 일이 착수 불가 항목에 묻힌다. 그 외 새 목록 파일은 만들지 않는다.
- 모듈은 한 책임을 유지하되 한두 함수만 담는 무의미한 파일 분할은 피한다.
- **시각은 `core/clock.py`의 `now()`·`today()`만 쓴다.** `datetime.now()`·`date.today()`는
  호스트 타임존을 따라가서 서버를 다른 타임존에 올리면 `/market`의 하루 경계와 보존
  기간이 통째로 밀린다. ruff의 `DTZ` 규칙이 이걸 막는다(테스트는 예외).
  저장된 타임스탬프를 `now()`와 비교할 때는 `ensure_kst()`로 감싼다 — aware 전환
  이전에 쓴 `data/` 파일에는 오프셋이 없어 그냥 비교하면 TypeError로 죽는다.
  예외는 둘뿐이다: Cloudflare 할당량 리셋은 UTC 00시 기준이고
  (`llm/backends.py`), 기사 시각은 소스 타임존을 `news/utils.py`가 KST로 변환한다.

## 배포

Lightsail 운영 절차는 `iac/terraform/README.md`가 유일한 배포 문서다. 부트스트랩은
봇을 자동 기동하지 않는다. 동일 Telegram 토큰의 중복 polling을 피하도록 로컬을
정지한 뒤 서버를 기동한다.
