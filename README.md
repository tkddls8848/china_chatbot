# China Chatbot

텔레그램으로 시장 뉴스, 관심종목 뉴스, 뉴스 감성, 리서치와 브리핑을 제공하는 봇입니다.

## 시작하기

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python app\bot.py
```

`.env`에는 최소한 아래 값을 설정해야 합니다.

```env
TELEGRAM_BOT_TOKEN=봇_토큰
TELEGRAM_CHAT_ID=전송할_채팅_ID
OLLAMA_BASE_URL=http://localhost:11434
```

모든 설정 항목과 기본값은 [`.env.example`](.env.example)에 있습니다.

## 기능

- 중국·홍콩·글로벌 뉴스 수집과 한국어 번역
- 국가·증시별 뉴스 감성 차트 (`/market`)
- 관심종목 뉴스, 감성 요약, 신호 성과 확인
- 뉴스 기반 시장 리서치와 후보 종목 관리
- 모닝·마감 브리핑 및 주간 성적표
- 중국·홍콩 종목 DB와 Yahoo 기반 한국 종목 시험 수집

## 텔레그램 명령

| 명령 | 용도 |
|---|---|
| `/market [일수]` | 국가별 뉴스 감성 차트 |
| `/menu`, `/list` | 관심종목 관리·목록 |
| `/add 종목코드` | 관심종목 추가 |
| `/view [종목코드]` | 종목별 뉴스 감성 |
| `/score [backtest]` | 감성 신호 성과 |
| `/research show\|set\|run\|clear` | 리서치 관리·실행 |
| `/briefing morning\|evening\|scorecard` | 브리핑 생성 |
| `/stockdb build` | 종목 DB 갱신 |
| `/system` | 시스템·뉴스 소스 상태 |

모든 명령은 처리 시작·완료·실패 상태를 채팅에 표시합니다.

## 디렉터리 구조

```text
china_chatbot/
├── app/                         # 봇 실행 코드
│   ├── bot.py                   # 앱 조립, 명령 등록, 스케줄러
│   ├── core/                    # 환경 설정, 접근 제어, 시스템 제어
│   ├── handlers/                # 공통 텔레그램 명령과 /market 차트 렌더링
│   ├── briefing/                # 브리핑·성적표·거래일 처리
│   ├── llm/                     # Ollama 번역, 리서치 분석, 브리핑 작성
│   ├── news/                    # 뉴스 소스, 수집 파이프라인, 과거 데이터 보강
│   ├── research/                # 리서치 후보 구성, 실행, 버튼 처리
│   ├── state/                   # 전송 이력, 뉴스·예측 로그, 성과 계산
│   ├── stocks/                  # 종목 DB, 시세·정량 데이터, 외부 식별자 보강
│   ├── watchlist/               # 관심종목 저장과 텔레그램 UI
├── prompts/                     # 번역·리서치·브리핑 프롬프트
├── scripts/                     # 백필과 신호 성과 오프라인 실행 도구
├── tests/                       # 기능별 회귀 테스트
├── docs/                        # 설계·향후 계획 문서
├── data/                        # 실행 중 생성되는 상태·캐시 (Git 제외)
├── .env.example                 # 환경 변수 예시
└── requirements.txt             # 실행 의존성
```

## 데이터와 외부 서비스

- `data/`에는 관심종목, 전송 이력, 뉴스·예측 로그, 종목 DB, 시세 캐시가 저장됩니다.
- 뉴스·시세 제공처 장애는 다른 기능을 중단시키지 않으며, 시세 조회는 재시도 후 일정 시간 쿨다운합니다.
- Ollama를 사용하려면 선택한 모델을 내려받고 서버를 실행해야 합니다. 번역을 끄려면 `TRANSLATION_ENABLED=false`로 설정합니다.
- `ALLOWED_CHAT_IDS`를 설정하면 지정한 채팅에서만 명령을 처리합니다.
