# CLAUDE.md

AI 코딩 도구를 위한 프로젝트 컨텍스트. 코드만 읽어서는 알 수 없는 결정·규칙을 우선 기록한다.
버그를 고치면서 새 규칙이 드러나면 이 문서에 한 줄 추가한다.

## 프로젝트 개요

텔레그램 봇. 중국·홍콩·한국·글로벌 시장 뉴스를 수집해 Ollama LLM으로 번역·감성 분석하고,
관심종목 관리·시장 감성 차트·리서치 후보 관리·브리핑을 제공한다. 개발자 1인 프로젝트이며
**Windows에서 운영**되므로 코드는 항상 크로스 플랫폼이어야 한다(예: `bot.py`의
msvcrt/fcntl 분기, 경로는 `pathlib` 사용).

## 실행과 테스트

- 실행: `python app/bot.py` — `app/`이 import 루트다. 모듈은 `from core.config import ...`
  형태로 import 하며 `app.` 접두사를 붙이지 않는다.
- 테스트: `python -m pytest tests/` — **conftest.py가 없다.** 각 테스트 파일이 직접
  `sys.path.insert(0, str(ROOT / "app"))`와 더미 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`
  환경변수를 설정한다. 새 테스트 파일도 같은 서두를 따른다.
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
  지점이다. 명령어·인라인 메뉴·콜백 접두사·스케줄 잡·데이터 파일·프롬프트를 여기에 선언하고
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

## 시장·티커 규칙 (가장 사고가 잦았던 영역)

`app/stocks/market_data.py`가 기준 구현이다. 수정 전 반드시 읽을 것.

- 종목 코드 형식: 중국 A주 6자리(상하이 `6xxxxx`, 선전 `000~003`/`300`/`301` 시작),
  홍콩 5자리 숫자, 한국 6자리 숫자, 미국은 알파벳 티커.
- **리서치 로그의 market 태그를 그대로 믿지 않는다.** LLM이 홍콩 5자리·한국 6자리
  종목을 CN 계열로 오태깅한 사례가 있다. `normalize_market()`은 CN 계열 태그를 코드가
  실제 A주 형식일 때만 신뢰하고, 어긋나면 형식 기반으로 재추론한다. 채점 시에는
  StockDB의 종목별 market으로 보정한다.
- AkShare는 홍콩 또는 실제 A주 형식일 때만 호출한다. 잘못된 코드로 두드리면 동방재부가
  연결을 끊어 `RemoteDisconnected` 재시도만 반복된다.
- `yahoo_ticker()`는 접미사를 붙일 수 없는 조합(예: CN 태그가 붙은 한국 코드)에 빈
  문자열을 반환하고, 호출부는 이를 "조회 건너뜀"으로 처리한다. 무의미한 404를 만들지 말 것.
- 시세는 현지 소스(AkShare) 우선, Yahoo Finance는 독립 폴백이다.

## 외부 의존성의 알려진 함정

- **pandas**: 3.0의 문자열 추론 변경이 일부 AkShare 응답의 정규식 처리를 깨뜨려
  `config.py`에서 `future.infer_string=False`로 고정했다. 제거하지 말 것.
- **apscheduler**: `3.10.4`로 고정(4.x는 API 비호환).
- **동방재부 인기순위 API**(`QUANT_HOT_RANK_ENABLED`): 해외 IP에서 차단되므로 기본
  비활성. 활성화 실패를 버그로 오인하지 말 것.
- **pywencai**(问财 스크리닝): 비공식 API라 선택 설치·기본 비활성(`WENCAI_ENABLED`).
- 뉴스·시세 소스는 실패해도 다른 기능이 계속 동작해야 한다. 소스별 실패 임계·쿨다운
  (`NEWS_SOURCE_FAILURE_THRESHOLD`/`COOLDOWN`)이 있으므로 새 소스도 같은 패턴을 따른다.
- 감성 점수는 별도 모델이 아니라 Ollama 번역 파이프라인(`app/llm/translator.py`)이
  번역과 함께 산출한다. 프롬프트는 `prompts/*_ko.txt`이며 소스별로 분리되어 있다.

## 문서 위치

- README의 `docs/`(설계·작업 문서, 에러 기록)는 **개발자 로컬에만 있고 저장소에 없다.**
  원격 AI 세션에서는 볼 수 없으므로, 지속 가치가 있는 결정은 이 파일이나 코드 주석으로
  옮겨 기록한다.
- 관리 웹(web_admin)은 `WEB_ADMIN_PASSWORD` 미지정 시 기능이 켜져 있어도 기동을
  건너뛴다(의도된 안전장치).
