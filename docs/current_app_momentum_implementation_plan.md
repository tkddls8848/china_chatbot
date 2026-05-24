# 현재 앱 기준 중국 정책/업종 모멘텀 기능 구현 계획

## 1. 현재 앱 구조 요약

현재 앱은 Telegram Bot 기반의 중국 시장 뉴스/관심종목 관리 도구다.

주요 구조:

- `app/bot.py`: Telegram Bot 진입점, 스케줄러, 명령어 등록
- `app/news/sources.py`: AkShare 기반 뉴스 수집
- `app/stock_db.py`: A주/HK 종목 DB 캐시 생성
- `app/watchlist/`: 관심종목 저장 및 Telegram 명령어
- `app/research/`: 사용자가 저장한 리서치 관점과 뉴스 기반 LLM 분석
- `data/`: JSON 기반 상태 저장

현재 앱의 장점:

- 이미 AkShare 의존성이 있다.
- Telegram 알림 인프라가 있다.
- APScheduler 기반 주기 실행 구조가 있다.
- `StockDatabase`로 종목 코드/이름 관리 기반이 있다.
- `/research` 흐름으로 후보 종목 제안 및 관심종목 반영 구조가 있다.

현재 앱의 한계:

- 가격/거래대금 시계열 저장 구조가 없다.
- 업종 분류와 업종 지수 저장 구조가 없다.
- 정책 뉴스와 가격 모멘텀을 결합하는 점수 엔진이 없다.
- 현재 리서치는 뉴스/LLM 중심이고, 정량 모멘텀 검증이 없다.

## 2. 구현 방향

기존 기능을 크게 변경하지 않고, 독립적인 `momentum` 모듈을 추가한다.

목표:

- 기존 뉴스 알림 기능은 유지한다.
- `/research`는 그대로 유지
- 신규 기능은 고정 스케줄러가 아니라 `/momentum` 명령어로 사용자가 호출할 때 실행한다.
- 초기 저장소는 현재 앱 스타일에 맞춰 `data/*.json` 또는 `data/*.parquet`를 사용한다.

## 3. 신규 디렉터리 구조

권장 추가 구조:

```text
app/
  momentum/
    __init__.py
    settings.py
    models.py
    universe.py
    sectors.py
    prices.py
    benchmarks.py
    breadth.py
    scoring.py
    policy.py
    service.py
    store.py
    handlers.py
    formatter.py

data/
  momentum/
    sector_map.json
    industry_keywords.json
    price_cache.json
    momentum_state.json
```

역할:

- `universe.py`: 거래 가능 종목 universe 구성
- `sectors.py`: 종목-업종 매핑 관리
- `prices.py`: 일봉 가격/거래대금 수집
- `benchmarks.py`: 업종 제외 벤치마크 및 동일가중 시장 계산
- `breadth.py`: 시장폭 지표 계산
- `scoring.py`: 업종/종목 모멘텀 점수 계산
- `policy.py`: 정책 키워드와 업종 매핑
- `service.py`: 수동 실행 파이프라인 조율
- `handlers.py`: `/momentum` Telegram 명령어 처리
- `formatter.py`: Telegram 메시지 포맷
- `store.py`: JSON/Parquet 저장소 추상화

## 4. 데이터 모델

### 4.1 종목 기본 정보

현재 `StockDatabase`의 종목 데이터를 재사용한다.

추가 필드:

```json
{
  "code": "300750",
  "display_name": "CATL",
  "market": "CHI",
  "sector_id": "battery",
  "sector_name": "배터리",
  "industry_name_cn": "电池",
  "tradable": true
}
```

초기에는 `data/momentum/sector_map.json`으로 관리한다.

### 4.2 가격 데이터

일봉 기준으로 저장한다.

```json
{
  "date": "2026-05-22",
  "code": "300750",
  "open": 0.0,
  "high": 0.0,
  "low": 0.0,
  "close": 0.0,
  "volume": 0.0,
  "amount": 0.0
}
```

초기 저장 형식은 Parquet를 권장한다. 이유는 JSON보다 일봉 시계열 처리와 Pandas 연산에 적합하기 때문이다.

### 4.3 업종 점수

```json
{
  "date": "2026-05-22",
  "sector_id": "robotics",
  "sector_name": "로봇",
  "price_score": 72.0,
  "ex_sector_rs_score": 81.0,
  "equal_weight_breadth_score": 76.0,
  "volume_score": 69.0,
  "policy_score": 55.0,
  "total_score": 73.4,
  "grade": "Strong Watch"
}
```

## 5. 핵심 계산 로직

### 5.1 업종 제외 벤치마크

각 업종별로 해당 업종 구성 종목을 제외한 시장 수익률을 계산한다.

```text
업종 제외 벤치마크 수익률 =
  전체 A주 수익률에서 해당 업종 구성 종목을 제외한 종목들의 수익률
```

계산 기준:

- 동일가중 기준을 기본값으로 사용
- 시가총액 데이터가 안정적으로 확보되기 전까지 시총가중은 후순위
- 5일, 20일, 60일 수익률을 모두 계산

필수 지표:

- `sector_return_5d`
- `sector_return_20d`
- `sector_return_60d`
- `ex_sector_market_return_20d`
- `ex_sector_relative_strength_20d`
- `ex_sector_relative_strength_rank`

### 5.2 동일가중 시장폭

업종 지수 상승이 소수 대형주 때문인지 업종 전체 확산인지 확인한다.

필수 지표:

- 업종 구성종목 동일가중 20일 수익률
- 업종 구성종목 수익률 중앙값
- 업종 내 20일선 위 종목 비율
- 업종 내 60일선 위 종목 비율
- 업종 내 20일 신고가 종목 비율
- 업종 내 전체 A주 동일가중 수익률 초과 종목 비율
- 업종 내 거래대금 증가 종목 비율

판정:

```text
확산형 상승:
  업종 동일가중 수익률 > A주 전체 동일가중 수익률
  AND 업종 내 20일선 위 종목 비율 상승
  AND 업종 내 거래대금 증가 종목 비율 상승

대형주 주도 상승:
  업종 가격 수익률 상승
  AND 동일가중 수익률 부진
  AND 시장폭 개선 미흡
```

### 5.3 업종 점수

초기 점수 모델:

```text
Total Score =
  Price Momentum Score * 0.25
+ Ex-Sector Relative Strength Score * 0.25
+ Equal-Weight Breadth Score * 0.20
+ Volume Score * 0.15
+ Policy Score * 0.15
```

등급:

- 80점 이상: `Actionable Watch`
- 65~79점: `Strong Watch`
- 50~64점: `Watch`
- 50점 미만: 알림 없음

## 6. Telegram 명령어 설계

기존 명령어와 충돌하지 않도록 `/momentum`을 추가한다.

명령어:

```text
/momentum
/momentum top
/momentum sector 로봇
/momentum refresh
/momentum run
```

동작:

- `/momentum`: 사용법 및 최근 요약
- `/momentum top`: 최근 업종 모멘텀 상위 목록
- `/momentum sector 로봇`: 특정 업종 상세 점수
- `/momentum refresh`: 수동 데이터 갱신, 점수 재계산, 최신 결과 저장
- `/momentum run`: `/momentum refresh`와 동일한 수동 분석 실행 별칭
- `/momentum refresh force`: 쿨다운을 무시하고 강제 재수집

제외 항목:

- `/momentum config`: 관심 업종 설정 기능은 만들지 않는다.
- `/momentum alerts`: 최근 발생 알림 이력 조회 기능은 만들지 않는다.

## 7. 수동 실행 통합

고정된 시간 스케줄러를 두지 않는다. 사용자가 Telegram에서 `/momentum refresh` 또는 `/momentum run`을 호출할 때 가격 데이터 갱신, 업종 제외 상대강도 계산, 동일가중 시장폭 계산, 점수 산출, 결과 저장을 한 번에 수행한다.

실행 흐름:

```text
사용자 호출: /momentum refresh 또는 /momentum run
1. 종목 universe와 업종 매핑 로드
2. 필요한 가격 데이터 수집 또는 캐시 갱신
3. 업종 제외 벤치마크 계산
4. 동일가중 시장폭 계산
5. 업종 점수 계산
6. 결과를 momentum_state.json에 저장
7. Telegram으로 상위 업종 요약 반환
```

환경변수:

```env
MOMENTUM_ENABLED=true
MOMENTUM_TOP_LIMIT=10
MOMENTUM_MIN_RESULT_SCORE=0
MOMENTUM_PRICE_LOOKBACK_DAYS=160
MOMENTUM_USE_POLICY_SCORE=true
MOMENTUM_REFRESH_COOLDOWN_MINUTES=10
MOMENTUM_PRICE_FETCH_DELAY_SECONDS=0.8
```

`MOMENTUM_REFRESH_COOLDOWN_MINUTES`는 사용자가 짧은 시간 안에 반복 호출할 때 불필요한 AkShare 재수집을 줄이기 위한 값이다. 쿨다운 안에서는 기존 캐시와 최근 계산 결과를 우선 사용한다.
강제 갱신이 필요하면 `/momentum refresh force`를 사용한다.

`MOMENTUM_PRICE_FETCH_DELAY_SECONDS`는 AkShare/Eastmoney 쪽에서 연속 요청을 끊는 현상을 줄이기 위한 종목별 요청 간격이다. 연결이 자주 끊기면 이 값을 1.0~2.0초로 높인다.

## 8. 구현 단계

### Phase 1: 저장소와 업종 매핑

목표:

- `momentum` 모듈 골격 생성
- 업종 매핑 JSON 도입
- 종목 universe 생성

작업:

- `app/momentum/store.py` 생성
- `data/momentum/sector_map.json` 샘플 생성
- `app/momentum/sectors.py` 생성
- `StockDatabase.get_candidate_universe()` 결과와 업종 매핑 결합

검증:

- 업종별 구성 종목 수 출력
- 업종 미매핑 종목 수 출력

### Phase 2: 가격 수집

목표:

- AkShare로 A주 일봉 데이터 수집
- Parquet 캐시 저장

작업:

- `app/momentum/prices.py` 생성
- 종목별 일봉 수집 함수 작성
- 실패 종목 로깅
- 기존 캐시와 병합

주의:

- 전체 A주를 한 번에 수집하면 오래 걸릴 수 있으므로 MVP에서는 업종 매핑된 종목부터 시작한다.
- 네트워크 실패 시 기존 캐시로 계산 가능해야 한다.

검증:

- 1개 업종 샘플 수집
- 20일/60일 수익률 계산 가능 여부 확인

### Phase 3: 업종 제외 벤치마크와 동일가중 시장폭

목표:

- 업종 제외 벤치마크 계산
- 동일가중 시장폭 계산

작업:

- `app/momentum/benchmarks.py` 생성
- `app/momentum/breadth.py` 생성
- 전체 A주 동일가중 수익률 계산
- 업종별 제외 시장 수익률 계산
- 업종 내 20일선/60일선 위 종목 비율 계산
- 업종 내 시장 초과수익 종목 비율 계산

검증:

- 특정 업종이 자기 자신을 벤치마크에 포함하지 않는지 테스트
- 구성 종목 수가 적은 업종의 계산 예외 처리

### Phase 4: 점수 엔진

목표:

- 업종별 모멘텀 점수 산출
- 상위 업종 랭킹 생성

작업:

- `app/momentum/scoring.py` 생성
- 가격 점수, 상대강도 점수, 시장폭 점수, 거래대금 점수 구현
- 정책 점수는 초기에는 키워드 매칭 횟수 기반으로 단순 구현
- 점수 결과를 `data/momentum/momentum_state.json`에 저장

검증:

- `/momentum top`에서 상위 업종 표시
- 점수 구성 요소가 메시지에 함께 표시

### Phase 5: Telegram 핸들러

목표:

- 사용자가 Telegram에서 모멘텀 결과를 조회할 수 있게 한다.

작업:

- `app/momentum/handlers.py` 생성
- `app/momentum/formatter.py` 생성
- `/momentum top`
- `/momentum sector 업종명`
- `/momentum refresh`
- `/momentum run`
- `bot.py`에 `CommandHandler("momentum", cmd_momentum)` 추가
- Telegram 메뉴에 `momentum` 추가

검증:

- 명령어 응답 길이 4096자 이하 유지
- HTML escape 처리
- 데이터 없음 상태 메시지 처리

### Phase 6: 수동 분석 실행 안정화

목표:

- 사용자가 호출할 때만 모멘텀 분석을 수행한다.
- 고정 시간 스케줄러는 만들지 않는다.
- 별도 알림 이력 조회 기능은 만들지 않는다.
- 관심 업종 설정 없이 전체 업종 랭킹 기준으로 결과를 반환한다.

작업:

- `handlers.py`에서 `/momentum refresh`와 `/momentum run`을 같은 실행 함수로 연결
- `formatter.py`에서 수동 분석 결과 메시지 생성
- `momentum_state.json`에 `last_refreshed_at`, `last_requested_at`, `last_result` 저장
- 쿨다운 안에서는 기존 캐시와 최근 결과를 우선 사용
- 사용자가 호출한 채팅에만 결과 반환
- 별도 `alert_history.json`은 생성하지 않음

검증:

- 짧은 시간 내 반복 호출 시 불필요한 데이터 재수집을 피하는지 확인
- `/momentum top` 결과와 `/momentum refresh` 결과가 같은 계산 결과를 사용
- 스케줄러 없이도 수동 명령만으로 분석이 완료되는지 확인

### Phase 7: 리서치 기능과 통합

목표:

- `/research run` 실행 시 모멘텀 상위 종목을 후보 universe에 추가한다.

작업:

- 모멘텀 상위 업종 내 종목 후보를 추출
- `build_research_candidate_universe()` 결과에 병합
- LLM 분석 payload에 정량 근거 추가

추가 evidence 예시:

```json
{
  "source": "momentum",
  "sector": "로봇",
  "grade": "Strong Watch",
  "ex_sector_relative_strength_20d": 8.2,
  "breadth_20d_above_ma": 0.72,
  "volume_ratio_20d": 1.8
}
```

## 9. 우선 구현 범위

첫 구현은 다음까지만 권장한다.

1. `momentum` 모듈 골격
2. 업종 매핑 JSON
3. 업종 매핑된 종목 가격 수집
4. 업종 제외 상대강도 계산
5. 동일가중 시장폭 계산
6. 업종 점수 계산
7. `/momentum top`
8. `/momentum refresh`
9. `/momentum run`

`/research` 통합은 두 번째 단계로 미룬다. 먼저 사용자가 직접 호출한 계산 결과가 납득 가능한지 확인하는 것이 중요하다.

## 10. 구현 시 주의사항

### 10.1 데이터 수집 속도

AkShare로 전체 종목 일봉을 매번 새로 수집하면 느릴 수 있다.

대응:

- 최초 160거래일만 수집
- 이후 최근 5~10일만 증분 수집
- 실패 종목은 스킵하고 다음 실행에서 재시도
- AkShare 연결 끊김이 잦으면 `MOMENTUM_PRICE_FETCH_DELAY_SECONDS`를 높여 요청 속도를 낮춤

### 10.2 업종 매핑 품질

업종 매핑이 부정확하면 상대강도와 시장폭 계산이 왜곡된다.

대응:

- MVP는 핵심 정책 산업군 10~15개만 수동 매핑
- 점진적으로 매핑 확대
- 미매핑 종목은 전체 동일가중 시장에는 포함하되 업종 점수 계산에서는 제외

### 10.3 구성 종목 수가 적은 업종

종목 수가 너무 적으면 시장폭 지표가 불안정하다.

대응:

- 업종 구성 종목 최소 8개 이상일 때만 업종 점수 산출
- 8개 미만은 `Low Coverage`로 표시

### 10.4 가격 데이터 결측

거래정지, 신규상장, 데이터 오류가 발생할 수 있다.

대응:

- 최소 60거래일 미만 종목은 60일 지표 제외
- 결측 종목은 시장폭 분모에서 제외
- 종목별 수집 실패 로그 유지

## 11. 예상 변경 파일

신규 파일:

```text
app/momentum/__init__.py
app/momentum/settings.py
app/momentum/models.py
app/momentum/store.py
app/momentum/sectors.py
app/momentum/prices.py
app/momentum/benchmarks.py
app/momentum/breadth.py
app/momentum/scoring.py
app/momentum/policy.py
app/momentum/service.py
app/momentum/formatter.py
app/momentum/handlers.py
data/momentum/sector_map.json
data/momentum/industry_keywords.json
```

수정 파일:

```text
app/bot.py
.env.example
requirements.txt
README.md
```

선택 수정:

```text
app/research/candidates.py
app/research/handlers.py
```

## 12. 검증 계획

기본 검증:

- `python -m compileall app`
- `/momentum top` 응답 확인
- `/momentum refresh` 수동 실행 확인
- 데이터 없는 상태에서도 오류 없이 메시지 반환

계산 검증:

- 업종 제외 벤치마크에 해당 업종 종목이 포함되지 않는지 확인
- 동일가중 수익률이 단순평균으로 계산되는지 확인
- 20일선 위 종목 비율 계산이 결측 종목을 제외하는지 확인
- 점수 등급 경계값 테스트

운영 검증:

- AkShare 네트워크 실패 시 기존 캐시 사용
- 고정 스케줄러 없이 `/momentum refresh` 또는 `/momentum run` 호출만으로 실행
- 짧은 시간 내 반복 호출 시 쿨다운 적용
- Telegram 메시지 길이 제한 준수
- 별도 알림 이력 파일이나 `/momentum alerts` 명령어가 생성되지 않는지 확인

## 13. 최종 권장 순서

먼저 `/momentum refresh`, `/momentum run`, `/momentum top`을 통해 사용자가 원할 때 계산 결과를 검토할 수 있게 만드는 것이 좋다.

권장 순서:

1. 수동 업종 매핑 10~15개 생성
2. 업종별 가격 데이터 수집
3. 업종 제외 상대강도와 동일가중 시장폭 계산
4. `/momentum refresh` 또는 `/momentum run`으로 수동 분석 실행
5. `/momentum top`으로 저장된 결과 확인
6. 점수 모델 보정
7. `/research` 후보 universe와 통합

이 순서가 현재 앱의 구조를 가장 적게 흔들면서, 정책 모멘텀 서비스의 핵심 가치를 빠르게 검증할 수 있는 경로다.
