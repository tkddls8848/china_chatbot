# 유사 서비스·오픈소스 조사 및 기능 강화 방안

작성일: 2026-07-05

## 1. 서비스 목적 정의

현재 봇의 정체성은 다음 세 가지로 요약된다.

1. **나만의 시장뷰(sight) 기반 관심리스트 큐레이션** — LLM이 시장뷰·뉴스·후보군을 종합해 추가/삭제 후보를 제안하고, 사용자가 텔레그램 버튼으로 승인
2. **중국·홍콩 시장 뉴스의 한국어 브리핑** — Futu/CLS 전역 속보 + 관심종목별 뉴스를 Ollama로 번역·전송
3. **셀프호스팅 / 로컬 LLM / 저비용** — Ollama 기반, 외부 유료 API 최소화(EODHD만 옵션)

자동매매 봇이 아니며, "판단은 사용자가, 정보 수집·정리·제안은 봇이" 하는 **투자 리서치 비서**다. 과거에 모멘텀 스코어링·백테스트·대시보드 모듈(`app/momentum/`)을 구현했다가 리팩터링에서 제거한 이력(커밋 `0ea25ff` → `f86ab6b`)이 있으므로, 독립적인 정량 엔진을 다시 세우기보다 **정량 데이터를 LLM 분석의 컨텍스트로 주입**하는 방향이 목적성에 부합한다.

## 2. 유사 서비스·오픈소스 프로젝트 조사

### 2.1 직접 경쟁/유사 서비스 (셀프호스팅 모니터링 봇)

| 프로젝트 | 개요 | 참고할 점 |
|---|---|---|
| [PanWatch (盯盘侠)](https://github.com/TNT-Likely/PanWatch) | 셀프호스팅 AI 주식 모니터링. A주/홍콩/미국 실시간 시세, 조건 조합(AND/OR) 가격·등락률·거래대금 알림, MACD/RSI/KDJ/볼린저 자동 계산, TradingAgents 멀티에이전트 통합(회당 ~$0.05), Telegram 포함 6개 알림 채널, Docker 배포 | 조건형 가격 알림, 기술지표 요약, 멀티에이전트의 "경량 통합" 사례 |
| [daily_stock_analysis (DSA)](https://github.com/ZhuLinsen/daily_stock_analysis) | LLM 일일 종목 분석 리포트 봇. AkShare/Tushare/Pytdx/Baostock/YFinance 등 **다중 데이터소스 페일오버**, 다중 뉴스 검색 API 조합, 거래일 캘린더 인식(휴장일 자동 스킵), GitHub Actions 무료 스케줄, Telegram/Discord/이메일 푸시 | 데이터소스 이중화 구조, 거래일 인식 스케줄링, "일일 결정 대시보드" 리포트 포맷 |
| [aiagents-stock](https://github.com/oficcejo/aiagents-stock) | 애널리스트 팀 모방 멀티에이전트. **용호방(龙虎榜) 세력자금 추적**(전담 에이전트 5), **섹터 로테이션 경보**(에이전트 4), 실시간 진입/익절/손절 모니터링, 데이터소스 3계층 백업(텐센트→AkShare, 신랑→AkShare), wencai 스크리닝 연동 | 용호방·섹터 로테이션이라는 중국 시장 특화 시그널, 소스 백업 계층화 |

### 2.2 LLM 금융 분석 프레임워크

| 프로젝트 | 개요 | 참고할 점 |
|---|---|---|
| [TradingAgents (TauricResearch)](https://github.com/tauricresearch/tradingagents) | 펀더멘털/감성/기술/뉴스 애널리스트 + **Bull/Bear 토론** + 리스크팀 + 트레이더 역할의 멀티에이전트(LangGraph). Ollama 로컬 모델 지원 | 역할 분리와 찬반 토론 구조 — 관심리스트 추가/삭제 판단의 신뢰도를 높이는 검증된 패턴 |
| [A_Share_investment_Agent](https://github.com/24mlight/A_Share_investment_Agent) | A주 특화 멀티에이전트. AkShare 데이터 + 신랑재경 뉴스, 기술/기본면/감성/밸류에이션/거시 분석가 + 강세·약세 연구원 토론, SQLite TTL 캐시 | AkShare 기반이라 데이터 레이어 호환성 높음. 캐시 계층 설계 |
| [FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | 금융 뉴스 감성분석 특화 LoRA 파인튜닝 모델(HuggingFace 공개) | 뉴스별 감성 점수화 접근. 범용 모델 프롬프트로도 모방 가능 |
| [FinMem](https://github.com/pipiku915/finmem-llm-stocktrading) | **계층적 메모리**(단기/중기/장기)를 가진 LLM 트레이딩 에이전트 | 현재 `last_result` 1건만 저장하는 구조 → 분석 이력 메모리로 확장하는 근거 |

### 2.3 데이터·인프라 도구

| 프로젝트 | 개요 | 활용 방안 |
|---|---|---|
| [AkShare 추가 엔드포인트](https://akshare.akfamily.xyz/data/stock/stock.html) | 이미 의존성에 포함. 뉴스 3종 외에 시세·자금흐름·순위·공시·리포트 다수 | §3.1 참조 |
| [pywencai](https://github.com/zsrl/pywencai) | 동화순 问财 **자연어 스크리닝**("반도체 + 북향자금 순매수 상위" 같은 쿼리를 DataFrame으로) | 시장뷰 → 스크리닝 쿼리 변환으로 후보군 발굴. 단, 비공식 API·차단 리스크 있으므로 옵션 기능 |
| [RSSHub](https://docs.rsshub.app/zh/routes/finance) | 财联社(`/cls/telegraph`), 华尔街见闻(`/wallstreetcn/news`), 金十数据(`/jin10`) 등 중국 금융 뉴스 RSS 라우트. 셀프호스팅 가능 | CLS 404 장애의 구조적 해결책. `feedparser`가 이미 requirements에 있음 |
| [Ashare](https://github.com/mpquant/Ashare) / Tushare / efinance | 신랑·텐센트 이중 소스 시세 API 등 AkShare 대체재 | 시세 조회 페일오버 소스 |

## 3. 기능 강화 방안 (우선순위순)

### 3.1 [1순위] 뉴스 소스 다변화 + 페일오버 구조

현재 CLS가 404로 죽어 있고(`NEWS_ENABLE_CLS=false`), 전역 뉴스가 사실상 Futu 단일 소스다. DSA·aiagents-stock 공통 패턴은 **소스 어댑터 + 우선순위 페일오버**.

- AkShare 내 대체 전역 뉴스: `stock_info_global_em`(동방재부 전역), `stock_info_global_sina`(신랑), `stock_info_global_ths`(동화순), `news_cctv`(신문련파)
- RSSHub 셀프호스팅으로 财联社/华尔街见闻/金十 RSS 확보 (`feedparser` 이미 보유)
- `app/news/sources.py`를 소스 레지스트리로 확장: 소스별 `enabled/priority/healthy` 상태를 두고, 연속 실패 시 자동 강등 후 주기적 재시도 — 현재의 수동 `NEWS_ENABLE_CLS` 토글을 대체

### 3.2 [1순위] 관심종목 정량 컨텍스트 — "일일 시세·자금 요약"

뉴스 텍스트만으로는 시장뷰 분석의 근거가 얇다. AkShare 엔드포인트 몇 개로 관심종목별 정량 스냅샷을 만들어 (a) 텔레그램 다이제스트에 표기하고 (b) `MarketViewAnalyzer` payload에 `quant_context`로 주입한다.

| 데이터 | AkShare 엔드포인트 |
|---|---|
| A주/HK 실시간 시세·등락률 | `stock_zh_a_spot_em`, `stock_hk_spot_em` |
| 개별 종목 자금흐름(주력 순매수) | `stock_individual_fund_flow` |
| 업종/컨셉 보드 등락 랭킹 | `stock_board_industry_name_em`, `stock_board_concept_name_em` |
| 인기 순위(동방재부) | `stock_hot_rank_em` |
| 용호방 | `stock_lhb_detail_em` |
| 涨停 풀(단기 과열 시그널) | `stock_zt_pool_em` |
| 공시·리서치 리포트 | `stock_notice_report`, `stock_research_report_em` |

제거된 momentum 모듈과 달리 자체 스코어링·백테스트 없이 **원시 지표를 요약해 LLM과 사용자에게 그대로 보여주는 수준**으로 유지해 복잡도를 억제한다.

### 3.3 [2순위] 모닝/마감 브리핑 (다이제스트)

현재는 4분 주기 뉴스 스트림만 있다. DSA의 "일일 결정 대시보드"처럼 **정해진 시각의 요약 브리핑**을 추가한다.

- 개장 전(HKT 09:00 전): 밤사이 뉴스 요약 + 관심종목 전일 종가/이슈 + 오늘 볼 포인트(LLM 생성)
- 마감 후: 관심종목 등락 + 자금흐름 + 섹터 히트맵(상위/하위 보드) + 관련 뉴스 요약
- 거래일 캘린더 인식(A주/HK 휴장일 스킵) — `akshare.tool_trade_date_hist_sina` 활용
- 기존 APScheduler에 cron job 2개 추가로 구현 가능. `refresh_stock_db`와 동일 패턴

### 3.4 [2순위] 뉴스 감성·영향도 스코어링

FinGPT 사례처럼 번역 시 감성을 함께 뽑는다. 이미 번역 프롬프트에서 관련 종목·테마를 추출하고 있으므로, 같은 LLM 호출에 `sentiment(-1~1)`와 `watchlist_impact(높음/중간/낮음)` 필드만 추가하면 **추가 호출 비용 없이** 구현된다.

- 다이제스트에서 관심종목별 "오늘 뉴스 감성 합계" 표시
- 부정 뉴스 임계 초과 시 즉시 알림(예: 감성 -0.7 이하 + 관심종목 직접 관련)
- 시장뷰 분석 payload의 뉴스 항목에 감성 필드 포함

### 3.5 [3순위] 시장뷰 분석의 다단계화 (경량 멀티에이전트)

TradingAgents식 full 멀티에이전트는 로컬 Ollama(gemma급)에 과하다. PanWatch가 보여주듯 핵심 가치는 역할 수가 아니라 **찬반 검증 단계**다. 단일 호출 → 2~3 pass로 확장:

1. **Pass 1 (수집 요약)**: 뉴스+정량 컨텍스트를 종목별 브리프로 압축
2. **Pass 2 (찬반)**: 추가/삭제 후보마다 bull 근거·bear 근거를 각각 생성
3. **Pass 3 (큐레이터)**: 시장뷰와 대조해 최종 후보 + confidence 산출

기존 "적용 버튼" UX는 그대로 두고 근거의 질만 올린다. `MarketViewAnalyzer.analyze()` 내부 파이프라인 변경이라 외부 인터페이스 변화 없음.

### 3.6 [3순위] 분석 메모리와 큐레이션 성과 추적

FinMem의 계층 메모리를 단순화해 적용:

- `market_research.json`의 `last_result` 1건 → **분석 이력 리스트**(최근 N건)로 확장, 다음 분석 시 "직전 제안과 그 이유"를 프롬프트에 포함해 일관성/변화 감지
- 관심리스트 편입·편출 이벤트를 날짜·당시 가격과 함께 기록 → 주간 "시장뷰 성적표"(편입 후 수익률, 편출 회피 손실) 브리핑. 제거했던 backtest 모듈의 미니 버전이지만, 목적이 전략 검증이 아닌 **사용자 시장뷰의 피드백 루프**라는 점이 다름

### 3.7 [옵션] 후보군 발굴 강화

- 현재 후보군은 종목 DB(시총·업종)에서만 나옴 → 섹터 보드 상위 → 소속 종목 → Northbound 필터 교차로 "지금 강한 섹터의 적격 종목"을 후보에 추가
- pywencai로 시장뷰를 자연어 스크리닝 쿼리로 변환해 후보 확장(비공식 API이므로 `WENCAI_ENABLED=false` 기본, 실패해도 무시되는 보조 소스로)

### 3.8 [운영] 접근 제어·배포

- README에 명시된 갭인 **허용 사용자/채팅 ID 검증**을 핸들러 데코레이터로 추가 (`ALLOWED_CHAT_IDS` env)
- PanWatch·DSA 공통인 Docker 배포(compose에 Ollama + RSSHub 포함) 지원

## 4. 제안 로드맵

| 단계 | 항목 | 근거 |
|---|---|---|
| 1 | §3.1 뉴스 페일오버 + §3.2 정량 컨텍스트 | 현존 장애(CLS) 해결 + 기존 의존성만으로 구현, LLM 분석 품질 즉시 개선 |
| 2 | §3.3 브리핑 + §3.4 감성 스코어 | 사용자 체감 가치 큼, 기존 스케줄러·번역 호출에 얹는 저비용 확장 |
| 3 | §3.5 다단계 분석 + §3.6 메모리·성과 추적 | 핵심 차별화(시장뷰 큐레이션)의 신뢰도 강화 |
| 옵션 | §3.7 후보군 발굴, §3.8 운영 | 리스크(비공식 API)와 배포 환경에 따라 선택 |

## 참고 링크

- https://github.com/TNT-Likely/PanWatch
- https://github.com/ZhuLinsen/daily_stock_analysis
- https://github.com/oficcejo/aiagents-stock
- https://github.com/tauricresearch/tradingagents
- https://github.com/24mlight/A_Share_investment_Agent
- https://github.com/AI4Finance-Foundation/FinGPT
- https://github.com/pipiku915/finmem-llm-stocktrading
- https://github.com/zsrl/pywencai
- https://docs.rsshub.app/zh/routes/finance
- https://akshare.akfamily.xyz/data/stock/stock.html
- https://github.com/mpquant/Ashare
