# CLAUDE.md

AI 코딩 도구를 위한 프로젝트 컨텍스트. 코드만 읽어서는 알 수 없는 결정·규칙을 우선 기록한다.
버그를 고치면서 새 규칙이 드러나면 이 문서에 한 줄 추가한다.

## 프로젝트 개요

텔레그램 봇. 중국·홍콩·한국·글로벌 시장 뉴스를 수집해 Cloudflare Workers AI로 번역·감성 분석하고,
관심종목 관리·시장 감성 차트·리서치 후보 관리·브리핑을 제공한다. 개발자 1인 프로젝트이며
**Windows에서 개발하고 리눅스 VM에 배포**하므로 코드는 항상 크로스 플랫폼이어야 한다(예: `bot.py`의
msvcrt/fcntl 분기, 경로는 `pathlib` 사용).

## 실행과 테스트

- 실행: `python app/bot.py` — `app/`이 import 루트다. 모듈은 `from core.config import ...`
  형태로 import 하며 `app.` 접두사를 붙이지 않는다.
- 테스트: `python -m pytest -q` — `tests/conftest.py`가 `app/` import 경로,
  더미 Telegram 환경 변수와 워크스페이스 로컬 임시 디렉터리를 공통 설정한다.
- 봇은 `data/runtime/bot.lock`으로 단일 인스턴스를 강제한다.

## 설정 원칙

- `.env`가 모든 설정의 유일한 원본. `app/core/config.py`에서만 읽고, 다른 모듈은
  `os.environ`에 직접 접근하지 않는다. 새 설정은 반드시 `config.py` 상수 + `.env.example`
  항목으로 추가한다.
- `data/`는 설정이 아닌 수집 데이터 전용이며, **소유 기능 키의 하위 디렉토리**에 둔다
  (`data/news/`, `data/watchlist/`, `data/instruments/`, `data/signal_scoring/`,
  `data/research/`, `data/runtime/`). 레거시 평면 배치는 시작 시
  `core/data_layout.py`가 1회 이동시킨다. 새 데이터 파일도 이 규칙을 따른다.
- 런타임 변경(`/system gpu ...`)은 세션 한정이며 재시작하면 `.env` 값으로 돌아간다.

## 아키텍처: 기능 레지스트리

- 기능 단위는 `app/features/<키>/feature.py`의 `FeatureSpec`(base.py) 선언이 단일 조립
  지점이다. 명령어·인라인 메뉴·콜백 접두사·스케줄 잡·데이터 파일을 여기에 선언하고
  `features/__init__.py`의 `ALL_FEATURES`에 등록한다. 카탈로그는 `app/features/README.md`.
- 활성 목록은 `.env`의 `FEATURES_ENABLED`. 의존 기능이 빠지면 시작 단계에서
  `FeatureConfigurationError`로 실패한다(불완전 조합 방지가 의도).
- 콜백 디스패치: `CallbackSpec.handler`는 처리했으면 `True`를 반환한다. `False`면 같은
  접두사를 선언한 다음 기능으로 넘어간다.
- `handlers/navigation.py`의 `_context()` 프록시는 메뉴 버튼을 명령 핸들러로 위임할 때
  쓰는 가짜 컨텍스트다. **`user_data` 등 핸들러가 쓰는 속성을 반드시 전달해야 한다** —
  과거에 `user_data` 누락으로 `/add`가 AttributeError를 낸 적이 있다.
- 메뉴 편집 시 내용이 동일하면 텔레그램이 `BadRequest("Message is not modified")`를
  던진다. 이는 오류가 아니므로 무시한다(`cmd_menu` 참조).

## 시장·티커 규칙

- 종목 코드 형식: 중국 A주 6자리(상하이 `6xxxxx`, 선전 `000~003`/`300`/`301` 시작),
  홍콩 5자리 숫자, 한국 6자리 숫자, 미국은 알파벳 티커.
- 미국·한국 종목의 정식 키는 `US:NASDAQ:AAPL` / `KR:KOSPI:005930` 형태다. **한국 6자리
  코드는 A주 코드와 형식이 겹치므로** 코드만으로 시장을 단정하지 말고 거래소가 담긴
  키를 쓴다(`stocks/universe.py`의 `stock_key`). 시세도 이 키로 나뉜다: A주·홍콩은
  텐센트, 미국·한국은 Yahoo(`quotes.yahoo_symbol`).
## 리서치는 시장 균형이 기본값이다

중국·홍콩·미국·한국을 함께 다루므로, **우선순위 순서대로 상한까지 채우는 코드는
곧 중화권 전용이 된다.** 과거에 리서치 뉴스가 첫 소스(futu)로만 채워져 미국·한국
종목이 추천에 오르지 못한 적이 있다. 상한이 걸리는 자리마다 시장 회전을 넣는다.

- 뉴스 수집(`research/news.py`): 소스를 동시에 조회해 시장별 버킷을 만든 뒤
  `RESEARCH_NEWS_MARKETS` 순서로 라운드로빈 선택하고, **선택된 기사만 번역**한다.
  시장 태그는 기사의 `extra["market"]`(혼합 소스 gnews) → `SourceSpec.market` 순.
- 후보 발굴(`research/discovery.py`): 중화권(섹터·问财)·미국(yfinance 프리셋
  스크리너)·한국(FDR KRX 등락률) 결과를 `_interleave_by_market`으로 번갈아 배치한다.
  호출부가 앞에서 자르므로 **순서 자체가 균형 장치**다.
- 후보 universe 상한(`RESEARCH_MAX_CANDIDATES`)은 뉴스·키워드 후보가 다 먹으므로
  `RESEARCH_DISCOVERY_RESERVED_SLOTS`만큼 발굴 후보 자리를 남긴다.
- 컨텍스트 예산이 빠듯하다. 실측상 기사 6건 + 후보 10개가 `RESEARCH_CTX_MAX` 12288의
  거의 전부이며, 중국어 원문 기준 본문 260자가 한계선이라 `RESEARCH_NEWS_CONTENT_MAX_CHARS`
  기본값이 240이다. `RESEARCH_NEWS_MAX_ITEMS`를 올리면 ctx도 같이 올린다.
- **리서치 입력은 기본적으로 번역하지 않는다**(`RESEARCH_TRANSLATE_NEWS=false`). 분석
  모델이 다국어를 읽고, 종목명 매칭도 원문(cn_name·영문명)에서 더 잘 걸린다. 대신 번역
  파이프라인이 함께 주던 `mentioned_stocks`·`theme_candidates`·`sentiment`가 비므로,
  켜고 끌 때 후보 구성이 달라진다는 점을 기억한다.

## 후보는 근거 강도 순이다 (노이즈가 상한을 먹지 않게)

종목 DB가 15,000개라 **이름 문자열이 겹치는 후보는 언제나 수백 개가 나온다.** 근거 없는
후보가 상한(`RESEARCH_MAX_CANDIDATES`)을 채워 진짜 후보를 밀어낸 사례가 반복됐다.

- 등급: 관심종목 > LLM이 코드를 명시(mentioned_stocks·테마 codes) > 뉴스 본문 종목명
  매칭 > 시장 데이터 발굴 > 이름이 주제 키워드와 겹침. 마지막 등급
  (`RESEARCH_KEYWORD_CANDIDATES_ENABLED`)은 **기본 비활성**이고, 이름 매칭으로만 걸린
  테마 후보도 `RESEARCH_THEME_PATTERN_CANDIDATE_LIMIT`로 제한한다.
- 영문명 매칭에는 두 겹의 방어가 있다(`_build_name_matcher`). 종목 DB에서 여러 종목이
  공유하는 토큰은 빈도로 걸러내고(`RESEARCH_NAME_TOKEN_MAX_FREQUENCY`, 실측 tech=29·
  energy=83 vs apple=1), DB에선 드물지만 영어 기사에선 흔한 단어(Daily, Home) 때문에
  **여러 단어 이름은 토큰 2개 이상**이 같은 기사에 나와야 인정한다. 한 단어 이름
  (Alphabet)은 1개로 충분하다.
- 중국어·한국어 이름은 통째로 매칭하며 한글은 앞글자 경계를 요구한다("이닉스"가
  "하이닉스"에 걸리는 오탐 방지).

## 외부 의존성의 알려진 함정

- **pandas**: 3.0의 문자열 추론 변경이 일부 AkShare 응답의 정규식 처리를 깨뜨려
  `config.py`에서 `future.infer_string=False`로 고정했다. 제거하지 말 것.
- **apscheduler**: `3.10.4`로 고정(4.x는 API 비호환).
- **동방재부 인기순위 API**(`QUANT_HOT_RANK_ENABLED`): 해외 IP에서 차단되므로 기본
  비활성. 활성화 실패를 버그로 오인하지 말 것.
- **pywencai**(问财 스크리닝): 비공식 API라 선택 설치·기본 비활성(`WENCAI_ENABLED`).
- **yfinance 프리셋 스크리너**(`yf.screen`, 미국 후보 발굴): 1.5+ 전용 API이며 ETF·펀드가
  섞여 오므로 `quoteType == EQUITY`만 받는다. 실패는 빈 목록으로 흘린다.
- **FinanceDataReader**: `StockListing("KRX")`의 등락률 컬럼명이 버전마다 다르고
  오타(`ChagesRatio`)가 섞여 있어 후보 컬럼을 순서대로 찾는다.
- 뉴스·시세 소스는 실패해도 다른 기능이 계속 동작해야 한다. 소스별 실패 임계·쿨다운
  (`NEWS_SOURCE_FAILURE_THRESHOLD`/`COOLDOWN`)이 있으므로 새 소스도 같은 패턴을 따른다.
- 감성 점수는 별도 모델이 아니라 번역 파이프라인(`app/llm/translator.py`)이 번역과
  함께 산출한다. 프롬프트는 `prompts/*_ko.txt`이며 소스별로 분리되어 있다.

## LLM은 Cloudflare Workers AI 하나뿐이다 (로컬 추론 없음)

번역·시황 분석·브리핑이 모두 원격 Cloudflare를 쓴다. 로컬 Ollama 구현은 2026-08-02에
완전히 제거했다 — 무료 호스팅(1~2GB RAM, GPU 없음)에서 로컬 추론이 불가능하고,
실측상 로컬 4B가 금액을 10배 틀리는 등 품질도 원격 30B보다 나빴다.
**로컬 폴백을 되살리지 말 것.** 되살리려면 호스팅부터 다시 골라야 한다.

- 서비스 클래스는 프롬프트 구성·검증만 한다. HTTP 호출은 `app/llm/backends.py`가
  맡고, 조립은 `app/llm/factory.py`의 `build_*()` 한 곳에서만 한다. 기능에서
  `TranslationService(...)`·`MarketViewAnalyzer(...)`·`BriefingWriter(...)`를 직접
  만들지 않는다.
- **Cloudflare Qwen3에는 `/no_think`가 필수다.** 추론 모델인데 이 엔드포인트에는
  thinking을 끄는 옵션이 없어서, 그냥 두면 thinking이 `max_tokens`를 전부 먹고
  `finish_reason=length`로 content가 잘린다(실측: reasoning 3,510자 / content 14자,
  34 Neurons). 시스템 프롬프트 끝에 `/no_think`를 붙이면 정상 JSON이 오고 기사당
  8 Neurons로 떨어진다. `chat_template_kwargs.enable_thinking=false`는 content를
  아예 비우므로 대안이 아니다. 추론 모델을 새로 붙일 때 같은 함정을 확인한다.
- **assistant prefill은 쓸 수 없다.** OpenAI 호환 엔드포인트는 prefill을
  continuation이 아니라 완료된 대화로 보고 빈 응답을 준다(실측 completion_tokens=2).
  `_request_analysis()`는 응답이 `{`로 시작하지 않을 때만 보정하는 방식으로 대응한다.
- `ResilientBackend`가 재시도와 회로 차단을 담당한다. 폴백 공급자는 없으므로 회로가
  열리면 **명시적 실패**로 끝난다(요청이 조용히 사라지지 않는다). 무료 할당량 소진은
  다음 UTC 00시까지, 인증(401/403)·요청 형식(400/422) 오류는 재시작 전까지 연다.
  소진 뒤에도 계속 두드리면 기사마다 무의미한 왕복만 쌓이므로 회로를 빼지 말 것.
- **API 토큰·기사 원문을 로그나 예외 문자열에 넣지 않는다.** 외부 응답을 옮길 때는
  `_truncate()`로 자르고 `_redact()`로 토큰을 마스킹한다.
- **출력 길이는 상한이 아니라 프롬프트가 정한다.** `at most N`만 주면 모델은 상한보다
  훨씬 짧게 쓴다(실측: 상한 500자에서 77~105자, 8.9 Neurons). 목표 구간
  (`about X to Y`)과 담을 항목을 함께 지시하면 112자·10.3 Neurons로 늘어난다.
  **현재는 비용 때문에 의도적으로 상한만 둔다.** 분량을 늘려야 하면 여기가 손잡이다.
  단 원문에 정보가 없으면 무엇을 지시해도 짧게 나온다(본문 없는 RSS 기사).
- 과금 단위는 추정하지 않는다. 응답의 `usage.neurons`를 그대로 로그에 남기므로
  `grep neurons=`로 일일 소모를 합산한다. 무료 한도는 하루 10,000, UTC 00시 리셋.
- 할당량이 소진되면 그날 뉴스 다이제스트는 비고 `/research`는 실패하지만, 브리핑은
  `_write_llm_comment()`가 실패를 삼켜 **데이터 전용 브리핑으로 자동 degrade**한다.

## 문서 위치

- README의 `docs/`(설계·작업 문서, 에러 기록)는 **개발자 로컬에만 있고 저장소에 없다.**
  원격 AI 세션에서는 볼 수 없으므로, 지속 가치가 있는 결정은 이 파일이나 코드 주석으로
  옮겨 기록한다.
- 관리 웹(web_admin)은 `WEB_ADMIN_PASSWORD` 미지정 시 기능이 켜져 있어도 기동을
  건너뛴다(의도된 안전장치).
