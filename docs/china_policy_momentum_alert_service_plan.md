# 중국 섹터 모멘텀 감지기 MVP 구현계획

## 1. 결정 사항

초기 버전은 "정책 뉴스 기반 종목 추천 서비스"가 아니라 "장마감 기준 중국 A주 섹터 모멘텀 감지기"로 만든다.

첫 릴리스의 핵심은 다음 3가지다.

1. 업종별 가격 모멘텀과 상대강도 랭킹을 매일 계산한다.
2. 거래대금과 시장폭으로 실제 수급 확산 여부를 확인한다.
3. 강한 업종 안에서 후보 종목을 압축해 장마감 알림으로 보낸다.

정책 문서 수집과 중국어 NLP는 v1 필수 기능에서 제외하고, 초기에는 사람이 관리하는 `policy_keyword_sector_map` 테이블만 둔다. 정책 키워드는 알림 설명용 보조 정보로 사용하며, 알림 발생 조건의 필수 항목으로 쓰지 않는다.

## 2. MVP 범위

### 2.1 포함 기능

- 중국 A주 종목 마스터 수집
- 일봉 OHLCV와 거래대금 수집
- 업종 분류 매핑
- 거래 가능 종목 필터링
- 업종별 시가총액가중 수익률 계산
- 업종별 동일가중 수익률 계산
- A주 전체 동일가중 시장 수익률 계산
- 업종 제외 동일가중 벤치마크 계산
- 업종 상대강도 랭킹 계산
- 업종 거래대금 모멘텀 계산
- 업종 시장폭 계산
- 업종 알림 등급 산출
- 강한 업종 내 후보 종목 산출
- 장마감 Telegram 알림
- Streamlit 대시보드
- 신호 이력 저장 및 단순 백테스트

### 2.2 제외 기능

- 장중 실시간 알림
- 자동매매
- 정교한 정책 문서 크롤링
- LLM 기반 정책 해석
- 유료 데이터 벤더 완전 연동
- 포트폴리오 최적화
- 사용자별 복잡한 알림 룰

## 3. 데이터 원칙

### 3.1 1차 데이터 소스

개발 단계에서는 AKShare 또는 Tushare 중 하나를 선택한다. 둘 다 구현하지 않는다.

우선순위는 다음 기준으로 결정한다.

1. A주 전체 종목 마스터를 안정적으로 받을 수 있는가
2. 일봉 가격, 거래량, 거래대금을 받을 수 있는가
3. ST, 상장폐지, 거래정지 정보를 받을 수 있는가
4. 업종 분류 또는 업종 매핑에 필요한 필드를 받을 수 있는가
5. 과거 데이터 재수집이 가능한가

MVP는 내부 연구 도구로만 운영한다. 상업 서비스 전환 전에는 데이터 라이선스와 재배포 가능 여부를 별도로 검토한다.

### 3.2 필수 원천 필드

종목 마스터:

- `symbol`
- `exchange`
- `name`
- `list_date`
- `delist_date`
- `is_st`
- `is_delisting_risk`
- `industry_code`
- `industry_name`

일봉:

- `trade_date`
- `symbol`
- `open`
- `high`
- `low`
- `close`
- `adj_close`
- `volume`
- `turnover`
- `is_suspended`
- `limit_up`
- `limit_down`

업종 구성:

- `trade_date`
- `symbol`
- `industry_code`
- `industry_name`

업종 구성은 반드시 날짜별 스냅샷으로 저장한다. 현재 업종 구성으로 과거를 다시 계산하면 생존자 편향과 룩어헤드 편향이 생긴다.

### 3.3 거래 가능 종목 정의

특정 거래일 `D`에 다음 조건을 모두 만족하는 종목만 계산에 포함한다.

- `list_date <= D - 120거래일`
- `delist_date is null or delist_date > D`
- `is_st = false`
- `is_delisting_risk = false`
- `is_suspended = false`
- 최근 20거래일 중 거래일 수가 15일 이상
- 최근 20거래일 평균 거래대금이 3천만 위안 이상

위 기준은 설정값으로 분리한다.

```yaml
min_listing_days: 120
min_trading_days_20d: 15
min_avg_turnover_20d_cny: 30000000
exclude_st: true
exclude_delisting_risk: true
```

## 4. 저장 구조

MVP는 PostgreSQL 하나로 시작한다. TimescaleDB는 PostgreSQL 확장으로만 검토하고, ClickHouse와 Redis는 도입하지 않는다.

### 4.1 테이블

`stocks`

- `symbol` primary key
- `exchange`
- `name`
- `list_date`
- `delist_date`
- `created_at`
- `updated_at`

`stock_status_daily`

- `trade_date`
- `symbol`
- `is_st`
- `is_delisting_risk`
- `is_suspended`
- primary key: `trade_date, symbol`

`stock_daily_prices`

- `trade_date`
- `symbol`
- `open`
- `high`
- `low`
- `close`
- `adj_close`
- `volume`
- `turnover`
- `limit_up`
- `limit_down`
- primary key: `trade_date, symbol`

`stock_industry_daily`

- `trade_date`
- `symbol`
- `industry_code`
- `industry_name`
- primary key: `trade_date, symbol`

`sector_daily_metrics`

- `trade_date`
- `industry_code`
- `industry_name`
- `sector_return_method`
- `member_count`
- `tradable_member_count`
- `ret_5d`
- `ret_20d`
- `ret_60d`
- `eq_ret_5d`
- `eq_ret_20d`
- `eq_ret_60d`
- `ex_sector_rs_20d`
- `equal_market_rs_20d`
- `rs_rank`
- `market_rs_rank`
- `turnover_ratio_5d_20d`
- `breadth_above_ma20`
- `breadth_above_ma60`
- `breadth_outperform_market_20d`
- `breadth_above_ma20_delta`
- `new_high_20d_count`
- `new_high_60d_count`
- `score_total`
- `alert_level`
- primary key: `trade_date, industry_code`

`stock_candidate_daily`

- `trade_date`
- `symbol`
- `industry_code`
- `ret_20d`
- `sector_ret_20d`
- `excess_ret_20d`
- `turnover_ratio_5d_20d`
- `above_ma20`
- `above_ma60`
- `breakout_20d`
- `breakout_60d`
- `limit_up_flag`
- `overheat_flag`
- `candidate_score`
- primary key: `trade_date, symbol`

`alerts`

- `id`
- `trade_date`
- `alert_type`
- `industry_code`
- `symbol`
- `alert_level`
- `title`
- `body`
- `payload_json`
- `sent_at`
- `created_at`

`policy_keyword_sector_map`

- `keyword`
- `industry_code`
- `industry_name`
- `weight`
- `is_active`
- primary key: `keyword, industry_code`

## 5. 지표 산식

모든 수익률은 조정종가 `adj_close` 기준으로 계산한다.

### 5.1 종목 수익률

```text
ret_Nd(symbol, D) = adj_close(symbol, D) / adj_close(symbol, D - N거래일) - 1
```

N은 5, 20, 60을 사용한다.

### 5.2 업종 시가총액가중 수익률

MVP에서 시가총액 데이터를 안정적으로 확보하지 못하면 업종 공식 지수를 사용한다. 공식 지수가 없으면 동일가중 수익률을 기본 업종 수익률로 사용한다.

구현 우선순위:

1. 데이터 소스가 제공하는 업종 지수 수익률
2. 시가총액 데이터가 있으면 시가총액가중 구성종목 수익률
3. 둘 다 없으면 동일가중 구성종목 수익률

이 선택 결과는 `sector_return_method` 설정값과 실행 로그에 남긴다.

### 5.3 업종 동일가중 수익률

```text
eq_ret_Nd(sector, D) = average(ret_Nd(symbol, D))
```

대상은 `D` 기준 거래 가능 종목이다. 결측 수익률이 있는 종목은 제외한다.

### 5.4 A주 전체 동일가중 시장 수익률

```text
market_eq_ret_Nd(D) = average(ret_Nd(symbol, D))
```

대상은 전체 A주 거래 가능 종목이다.

### 5.5 업종 제외 동일가중 벤치마크

```text
ex_sector_eq_ret_Nd(sector, D)
  = average(ret_Nd(symbol, D) for symbol not in sector)
```

대상은 전체 A주 거래 가능 종목 중 해당 업종 소속 종목을 제외한 종목이다.

### 5.6 상대강도

```text
ex_sector_rs_20d = eq_ret_20d(sector, D) - ex_sector_eq_ret_20d(sector, D)
equal_market_rs_20d = eq_ret_20d(sector, D) - market_eq_ret_20d(D)
```

업종 수가 적으면 원점수보다 횡단면 순위가 안정적이다. 따라서 알림 판단은 다음 percentile rank를 사용한다.

```text
rs_rank = percentile_rank(ex_sector_rs_20d across sectors)
market_rs_rank = percentile_rank(equal_market_rs_20d across sectors)
```

### 5.7 거래대금 모멘텀

```text
turnover_ratio_5d_20d(sector, D)
  = sum(turnover over last 5 days for sector tradable members) / 5
    /
    (sum(turnover over last 20 days for sector tradable members) / 20)
```

업종 구성 종목 수가 10개 미만이면 알림 대상에서 제외한다.

### 5.8 시장폭

```text
breadth_above_ma20 = count(close > ma20) / tradable_member_count
breadth_above_ma60 = count(close > ma60) / tradable_member_count
breadth_outperform_market_20d = count(ret_20d > market_eq_ret_20d) / tradable_member_count
```

전일 대비 변화도 함께 저장한다.

```text
breadth_above_ma20_delta = breadth_above_ma20(D) - breadth_above_ma20(D - 1)
```

### 5.9 신고가

```text
breakout_20d = adj_close(D) >= max(adj_close from D - 20거래일 to D)
breakout_60d = adj_close(D) >= max(adj_close from D - 60거래일 to D)
```

가격제한폭 상한가에 잠긴 종목은 후보에는 포함하되 `limit_up_flag`를 표시한다. 실제 매수 가능성이 낮기 때문이다.

## 6. 점수 모델

MVP는 percentile 기반 점수로 시작한다. 모든 하위 점수는 0~100 범위다.

```text
price_score =
  percentile_rank(eq_ret_20d) * 0.60
  + percentile_rank(eq_ret_60d) * 0.40

relative_strength_score =
  percentile_rank(ex_sector_rs_20d) * 0.70
  + percentile_rank(equal_market_rs_20d) * 0.30

volume_score =
  percentile_rank(turnover_ratio_5d_20d)

breadth_score =
  percentile_rank(breadth_above_ma20) * 0.40
  + percentile_rank(breadth_above_ma60) * 0.30
  + percentile_rank(breadth_outperform_market_20d) * 0.30

total_score =
  price_score * 0.30
  + relative_strength_score * 0.30
  + volume_score * 0.20
  + breadth_score * 0.20
```

정책 점수는 v1 점수 모델에 넣지 않는다.

## 7. 알림 조건

### 7.1 업종 알림 등급

`Watch`

- `total_score >= 70`
- `rs_rank >= 70`
- `turnover_ratio_5d_20d >= 1.2`

`Strong Watch`

- `total_score >= 80`
- `rs_rank >= 80`
- `turnover_ratio_5d_20d >= 1.5`
- `breadth_above_ma20 >= 0.60`

`Actionable Watch`

- `total_score >= 90`
- `rs_rank >= 85`
- `market_rs_rank >= 80`
- `turnover_ratio_5d_20d >= 1.8`
- `breadth_above_ma20 >= 0.70`
- `breadth_outperform_market_20d >= 0.60`

알림 피로도를 줄이기 위해 같은 업종의 같은 등급 알림은 5거래일 동안 중복 발송하지 않는다. 단, 등급이 상승하면 즉시 발송한다.

### 7.2 리스크 알림

이미 `Strong Watch` 이상이었던 업종에 대해 다음 조건 중 2개 이상이 발생하면 약화 알림을 보낸다.

- 업종 동일가중 누적지수가 20일 이동평균 아래로 하락
- `rs_rank < 50`
- `breadth_above_ma20`가 3거래일 전 대비 0.15 이상 하락
- `turnover_ratio_5d_20d >= 1.5`인데 `eq_ret_5d <= 0`

### 7.3 종목 후보 조건

종목 후보는 `Strong Watch` 이상 업종 안에서만 생성한다.

기본 조건:

- 거래 가능 종목
- 최근 20거래일 평균 거래대금 5천만 위안 이상
- `ret_20d > sector_eq_ret_20d`
- `turnover_ratio_5d_20d >= 1.5`
- `above_ma20 = true`

가점 조건:

- 20일 신고가
- 60일 신고가
- `ret_20d` 업종 내 상위 20%
- `turnover_ratio_5d_20d` 업종 내 상위 20%

과열 표시:

- `ret_5d >= 0.25`
- 또는 `adj_close / ma20 - 1 >= 0.20`
- 또는 최근 5거래일 중 상한가 2회 이상

과열 종목은 제외하지 않고 `overheat_flag = true`로 표시한다.

## 8. 배치 파이프라인

MVP는 하루 1회 장마감 후 실행한다.

권장 실행 시각:

- 중국 본토 장마감 이후 데이터 안정화를 고려해 한국시간 18:30 이후

### 8.1 작업 순서

1. `sync_stock_master`
2. `sync_stock_status_daily`
3. `sync_stock_industry_daily`
4. `sync_stock_daily_prices`
5. `build_tradable_universe`
6. `calculate_stock_returns`
7. `calculate_sector_metrics`
8. `calculate_sector_scores`
9. `generate_stock_candidates`
10. `evaluate_alerts`
11. `send_telegram_alerts`
12. `run_signal_backtest_snapshot`

각 작업은 재실행 가능해야 한다. 같은 `trade_date`로 다시 실행하면 기존 결과를 upsert한다.

### 8.2 실패 처리

- 원천 데이터 수집 실패 시 해당 날짜 배치를 중단한다.
- 일부 종목 가격 결측은 허용하되, 업종 거래 가능 종목 수가 10개 미만이면 해당 업종 점수 계산을 건너뛴다.
- 알림 발송 실패는 `alerts`에 실패 상태를 남기고 3회 재시도한다.
- 배치 완료 후 누락 업종 수, 누락 종목 수, 발송 알림 수를 로그에 남긴다.

## 9. 코드 구조

권장 디렉터리 구조:

```text
china_chatbot/
  app/
    config/
      settings.py
    data_sources/
      akshare_client.py
      tushare_client.py
    db/
      models.py
      session.py
      migrations/
    jobs/
      sync_market_data.py
      calculate_metrics.py
      generate_alerts.py
      send_alerts.py
    momentum/
      universe.py
      returns.py
      sector_metrics.py
      scoring.py
      candidates.py
      backtest.py
    notifications/
      telegram.py
    dashboard/
      streamlit_app.py
  docs/
  tests/
```

첫 구현에서는 `akshare_client.py`와 `tushare_client.py` 중 하나만 활성화한다.

## 10. 대시보드

Streamlit으로 시작한다.

필수 화면:

- 오늘의 업종 랭킹
- Watch 이상 업종 목록
- 업종 상세 지표
- 업종 내 후보 종목
- 최근 알림 이력
- 백테스트 요약

업종 상세 화면에 반드시 보여줄 항목:

- 5일, 20일, 60일 동일가중 수익률
- 업종 제외 상대강도
- 상대강도 percentile rank
- 거래대금 배수
- 20일선 위 종목 비율
- 시장 초과수익 종목 비율
- 후보 종목 목록
- 과열 후보 표시

## 11. 백테스트

백테스트는 복잡한 포트폴리오 수익률이 아니라 신호 품질 검증부터 한다.

### 11.1 검증 대상

각 업종 알림 발생일 `D`에 대해 다음을 계산한다.

- `D+5` 업종 동일가중 초과수익
- `D+10` 업종 동일가중 초과수익
- `D+20` 업종 동일가중 초과수익
- `D+20`까지 최대낙폭
- 신호 후 5거래일 내 `Strong Watch` 유지 여부
- 신호 후 20거래일 내 리스크 알림 발생 여부

초과수익 기준은 A주 전체 동일가중 시장 수익률이다.

### 11.2 최소 합격 기준

MVP를 실제 알림으로 쓰기 전 다음 기준을 통과해야 한다.

- 최근 3년 기준 `Strong Watch` 이상 신호가 월평균 3~20개 범위
- `Strong Watch` 이상 신호의 `D+10` 평균 초과수익이 0보다 큼
- `Actionable Watch`의 `D+20` 평균 초과수익이 `Watch`보다 큼
- `D+20` 최대낙폭 중위값이 허용 범위 내인지 확인
- 특정 업종 1~2개가 전체 성과를 대부분 설명하지 않는지 확인

수익률 기준을 통과하지 못하면 임계값을 낮추지 말고 먼저 오탐 원인을 분석한다.

## 12. 구현 단계

### Phase 0: 데이터 소스 결정

기간: 2~3일

산출물:

- 선택한 데이터 소스 1개
- 필드 가용성 표
- 최근 3년 일봉 샘플
- 업종 매핑 샘플
- 결측률 리포트

완료 기준:

- A주 90% 이상 종목의 최근 3년 일봉 수집 가능
- 거래대금 필드 확보
- ST 또는 거래정지 필터링에 필요한 필드 확보
- 업종 코드 매핑 가능

### Phase 1: DB와 수집 배치

기간: 3~5일

작업:

- PostgreSQL 스키마 작성
- 종목 마스터 수집
- 일봉 수집
- 업종 스냅샷 저장
- 재실행 가능한 upsert 구현

완료 기준:

- 특정 날짜를 지정해 원천 데이터를 재수집할 수 있음
- 일봉 데이터 중복 저장이 발생하지 않음
- 결측률과 수집 종목 수를 로그로 확인할 수 있음

### Phase 2: 모멘텀 엔진

기간: 5~7일

작업:

- 거래 가능 유니버스 생성
- 종목 수익률 계산
- 업종 동일가중 수익률 계산
- A주 전체 동일가중 수익률 계산
- 업종 제외 상대강도 계산
- 거래대금 모멘텀 계산
- 시장폭 계산
- 점수 모델 구현

완료 기준:

- 특정 거래일의 `sector_daily_metrics`가 생성됨
- 업종별 구성 종목 수와 거래 가능 종목 수가 확인됨
- 상위 업종 랭킹이 대시보드 없이 CLI 또는 SQL로 확인 가능

### Phase 3: 알림과 후보 종목

기간: 3~5일

작업:

- 업종 알림 등급 평가
- 중복 알림 억제
- 후보 종목 산출
- 과열 플래그 산출
- Telegram 발송
- 알림 이력 저장

완료 기준:

- 장마감 배치 1회로 업종 알림과 후보 종목이 생성됨
- 같은 업종 같은 등급 중복 알림이 5거래일 동안 억제됨
- 알림 본문에 핵심 지표와 후보 종목이 포함됨

### Phase 4: 대시보드와 백테스트

기간: 5~7일

작업:

- Streamlit 업종 랭킹 화면
- 업종 상세 화면
- 후보 종목 화면
- 알림 이력 화면
- 신호 품질 백테스트

완료 기준:

- 최근 거래일 기준 Watch 이상 업종을 볼 수 있음
- 업종별 상세 지표와 후보 종목을 확인할 수 있음
- 최근 3년 신호 품질 요약을 볼 수 있음

## 13. 알림 예시

```text
[Strong Watch] 중국 로봇 업종 모멘텀 감지

- 20일 동일가중 수익률: +12.4%
- 업종 제외 상대강도: +8.1%
- 상대강도 순위: 상위 12%
- 거래대금: 20일 평균 대비 1.7배
- 20일선 위 종목 비율: 68%
- 시장 초과수익 종목 비율: 63%

후보 종목:
- 000000.SZ: 20일 +18.7%, 거래대금 2.4배, 60일 신고가
- 600000.SH: 20일 +15.2%, 거래대금 1.9배, 20일 신고가

주의:
- 일부 후보는 단기 이격도가 높아 추격 리스크가 있습니다.
```

## 14. 운영 체크리스트

매일 확인:

- 원천 데이터 수집 성공 여부
- 수집 종목 수
- 가격 결측 종목 수
- 업종 매핑 누락 종목 수
- Watch 이상 업종 수
- 발송 알림 수

매주 확인:

- 알림 후 5일, 10일 초과수익
- 알림 빈도
- 특정 업종 쏠림
- 후보 종목 과열 비율
- 거래정지/ST 필터 누락 여부

## 15. 다음 버전 후보

v1이 안정화된 뒤 다음 기능을 추가한다.

- 정책 문서 크롤러
- 정책 문서 중요도 등급
- 정책 키워드와 업종 매핑 자동 추천
- H주와 홍콩 상장 중국 ETF 확장
- 사용자 관심 업종별 알림
- 이메일 리포트
- 유료 데이터 벤더 연동

## 16. 성공 기준

MVP 성공은 예측 정확도가 아니라 운영 가능한 신호 체계 확보로 판단한다.

필수 성공 기준:

- 장마감 배치가 10거래일 연속 성공
- 데이터 결측과 수집 실패가 로그로 추적됨
- Watch 이상 알림이 과도하게 많이 발생하지 않음
- Strong Watch 이상 신호가 백테스트에서 시장 대비 양의 초과수익을 보임
- 후보 종목이 모두 거래 가능 종목 필터를 통과함
- 알림 이력과 계산 근거를 재현할 수 있음

이 기준을 통과한 뒤 정책 모멘텀 엔진을 붙인다.
