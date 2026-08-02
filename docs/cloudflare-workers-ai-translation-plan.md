# Cloudflare Workers AI 번역 연동 구현 계획

- 상태: **완료(2026-08-02). 단 이 문서의 "Ollama 폴백" 설계는 이후 폐기됐다.**
  무료 호스팅으로 옮기면서 로컬 Ollama 구현을 코드·설정에서 전부 제거했고,
  이제 번역·리서치·브리핑이 모두 Cloudflare 단독으로 동작한다. 폴백 대신
  `ResilientBackend`의 재시도·회로 차단이 그 자리를 대신한다.
  현재 배포 절차는 `docs/deployment-lightsail-plan.md`를 본다.
- 작성일: 2026-08-01
- 적용 범위: 뉴스 번역·요약·종목/테마 추출·감성 분석
- 기준안: **Cloudflare Qwen3 우선 호출 + 로컬 Ollama Qwen 자동 폴백**

## 1. 목표

현재 로컬 Ollama의 Qwen이 담당하는 뉴스 번역 작업을 Cloudflare Workers AI에서도 수행할 수 있게 한다. Cloudflare 무료 할당량과 서비스 장애에 영향을 받더라도 뉴스 파이프라인이 중단되지 않도록 로컬 Ollama를 폴백으로 유지한다.

구현 목표는 다음과 같다.

1. 기본 번역 공급자를 환경변수로 `ollama` 또는 `cloudflare` 중 선택한다.
2. Cloudflare 사용 시 `@cf/qwen/qwen3-30b-a3b-fp8` 모델을 기본으로 사용한다.
3. Cloudflare의 타임아웃, 일일 할당량 초과, 인증 오류 또는 응답 오류가 발생하면 로컬 Ollama로 자동 전환한다.
4. 기존 `TranslationResult` 계약과 뉴스·리서치 소비 코드는 최대한 변경하지 않는다.
5. API 토큰이나 기사 원문이 로그에 노출되지 않게 한다.
6. 공급자별 성공률, 지연시간, 폴백 횟수와 대략적인 토큰 사용량을 관찰할 수 있게 한다.

## 2. 현재 구조 분석

현재 번역 경로는 다음과 같다.

```text
뉴스 수집
  -> app/news/utils.py의 비동기 래퍼와 Semaphore
  -> app/llm/translator.py의 TranslationService
  -> Ollama /api/chat
  -> JSON 파싱 및 보정
  -> 뉴스 전송·감성 로그·리서치 입력
```

주요 파일과 역할은 다음과 같다.

| 파일 | 현재 역할 | 변경 필요성 |
|---|---|---|
| `app/llm/translator.py` | 프롬프트 구성, Ollama 호출, 재작성, JSON 파싱 | 공급자 호출 부분 분리 |
| `app/features/news/feature.py` | `TranslationService` 생성 및 Semaphore 설정 | 공급자 팩토리 연결 |
| `app/core/config.py` | Ollama 및 번역 환경변수 로딩 | Cloudflare 설정 추가 |
| `app/news/utils.py` | 동기 번역 서비스를 스레드에서 호출 | 공개 인터페이스 유지 시 변경 없음 |
| `app/news/pipeline.py` | 번역 결과를 뉴스·감성 로그에 사용 | 변경 없음이 목표 |
| `app/research/news.py` | 선택적으로 같은 번역 서비스 사용 | 변경 없음이 목표 |
| `app/core/system_control.py` | 로컬 Ollama GPU 설정 전파 | 폴백 Ollama에만 적용되도록 호환 유지 |
| `.env.example` | 실행 설정 예시 | 공급자·자격증명 설정 추가 |

현재 번역 결과는 단순 번역문이 아니다. 다음 구조를 한 번의 LLM 요청으로 생성한다.

```json
{
  "title": "한국어 제목",
  "content": "한국어 단신",
  "mentioned_stocks": ["600519", "AAPL"],
  "theme_candidates": [],
  "sentiment": 0.4,
  "impact": "medium"
}
```

이 때문에 번역 전용 `@cf/meta/m2m100-1.2b`는 1차 구현의 대체 모델로 사용하지 않는다. M2M100은 중국어↔한국어 번역은 가능하지만 종목·테마 추출과 감성·영향도 평가를 생성하지 못한다. 이를 사용하려면 번역과 구조화 분석을 두 단계로 나눠야 하므로 호출 수와 코드 복잡도가 증가한다.

## 3. 기술 결정

### 3.1 공급자 우선순위

| 순위 | 공급자 | 모델 | 용도 |
|---|---|---|---|
| 1 | Cloudflare Workers AI | `@cf/qwen/qwen3-30b-a3b-fp8` | 운영 기본 번역·요약·구조화 분석 |
| 2 | 로컬 Ollama | 기존 `TRANSLATION_MODEL` | Cloudflare 실패·할당량 초과 시 폴백 |
| 보류 | Cloudflare Workers AI | `@cf/meta/m2m100-1.2b` | 향후 순수 번역 단계가 분리될 때 검토 |

Cloudflare Qwen3는 현재 프롬프트의 다국어 처리와 JSON 결과 요구를 한 모델에서 유지할 수 있다. 모델이 바뀌더라도 `TranslationResult`와 후속 파이프라인 계약은 유지한다.

### 3.2 API 방식

애플리케이션 서버에서 Cloudflare의 OpenAI 호환 엔드포인트를 직접 호출한다.

```text
POST https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/v1/chat/completions
Authorization: Bearer {API_TOKEN}
Content-Type: application/json
```

기본 요청 형태:

```json
{
  "model": "@cf/qwen/qwen3-30b-a3b-fp8",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "temperature": 0.1,
  "max_tokens": 1024,
  "stream": false
}
```

1차 구현은 기존의 강한 JSON 프롬프트와 `_extract_json_object()` 파서를 그대로 활용한다. Cloudflare JSON Schema 모드는 실제 Qwen3 호환성을 스모크 테스트로 확인한 뒤 활성화한다. JSON 모드를 사용하더라도 현재 파서는 방어 계층으로 남긴다.

### 3.3 목표 구조

```text
TranslationService
  ├─ 프롬프트 구성·길이/미번역 재작성·결과 검증
  └─ TranslationBackendRouter
       ├─ primary: CloudflareWorkersAIBackend
       └─ fallback: OllamaTranslationBackend
```

공급자 전용 HTTP 형식과 공통 번역 규칙을 분리한다. `TranslationService.translate_article()`의 공개 시그니처는 유지한다.

## 4. 환경변수 설계

다음 설정을 추가한다.

```env
# 번역 공급자 선택.
TRANSLATION_PROVIDER=cloudflare
TRANSLATION_FALLBACK_ENABLED=true
TRANSLATION_FALLBACK_PROVIDER=ollama

# Cloudflare Workers AI.
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_API_TOKEN=
CLOUDFLARE_AI_BASE_URL=https://api.cloudflare.com/client/v4
CLOUDFLARE_TRANSLATION_MODEL=@cf/qwen/qwen3-30b-a3b-fp8
CLOUDFLARE_TRANSLATION_TIMEOUT=45
CLOUDFLARE_MAX_ATTEMPTS=2
CLOUDFLARE_FAILURE_THRESHOLD=3
CLOUDFLARE_FAILURE_COOLDOWN_SECONDS=300
```

기존 설정은 로컬 기본 공급자와 폴백에 계속 사용한다.

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_NUM_GPU=-1
TRANSLATION_MODEL=qwen3.5:4b
TRANSLATION_TIMEOUT=120
TRANSLATION_NUM_PREDICT=1024
TRANSLATION_CONCURRENCY=1
```

설정 규칙:

- `TRANSLATION_PROVIDER=cloudflare`일 때만 Cloudflare 계정 ID와 API 토큰을 필수 검증한다.
- `TRANSLATION_PROVIDER=ollama`이면 Cloudflare 자격증명 없이 기존과 동일하게 기동한다.
- API 토큰은 `.env`에만 저장하고 Git에 커밋하지 않는다.
- 예외 메시지, 요청 헤더, 전체 HTTP 응답을 그대로 로그에 남기지 않는다.
- 롤백은 `TRANSLATION_PROVIDER=ollama`로 변경하고 프로세스를 재시작하는 방식으로 한다.

## 5. 상세 구현 단계

### 단계 1. 공급자 인터페이스 분리

새 파일 `app/llm/backends.py`를 추가한다.

공통 인터페이스 예시:

```python
class TranslationBackend(Protocol):
    name: str

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str: ...
```

같은 파일에 다음 구현을 둔다.

- `OllamaTranslationBackend`
  - 현재 `_request_translation()`의 `/api/chat` 호출 코드를 이동한다.
  - `think=False`, `format="json"`, `num_gpu` 동작을 유지한다.
  - `set_num_gpu()`를 제공한다.
- `CloudflareWorkersAIBackend`
  - OpenAI 호환 Chat Completions 엔드포인트를 호출한다.
  - 응답의 `choices[0].message.content`를 검증해 문자열로 반환한다.
  - Cloudflare 오류 코드와 HTTP 상태를 내부 예외로 정규화한다.
- `TranslationBackendError`
  - `provider`, `status_code`, `retryable`, `quota_exhausted` 정보를 가진다.
  - 토큰, 헤더, 기사 본문은 포함하지 않는다.

HTTP 연결 재사용을 위해 공급자별 `requests.Session`을 보유하고, 요청 타임아웃은 반드시 명시한다.

### 단계 2. 라우터와 폴백 구현

`TranslationBackendRouter`를 추가해 다음 순서로 처리한다.

1. 회로가 닫혀 있으면 Cloudflare를 호출한다.
2. 연결 오류, 읽기 타임아웃, HTTP 429, HTTP 5xx는 설정된 횟수만큼 재시도한다.
3. Cloudflare 호출이 최종 실패하면 로컬 Ollama를 한 번 호출한다.
4. 폴백 성공 시 번역 전체를 성공으로 반환하되 공급자 전환을 경고 로그로 남긴다.
5. Cloudflare와 Ollama가 모두 실패하면 기존 `TranslationError`로 변환한다.

오류별 정책:

| 오류 | Cloudflare 재시도 | Ollama 폴백 | 회로 처리 |
|---|---:|---:|---|
| 연결/읽기 타임아웃 | 예 | 예 | 연속 실패 횟수 반영 |
| HTTP 429 일반 제한 | `Retry-After` 범위 내 1회 | 예 | 짧은 쿨다운 |
| 일일 무료 할당량 소진 | 아니요 | 예 | 다음 UTC 00시까지 열기 |
| HTTP 500/502/503/504 | 예 | 예 | 연속 실패 횟수 반영 |
| HTTP 401/403 | 아니요 | 예 | 재시작 전까지 열고 오류 로그 |
| HTTP 400/422 | 아니요 | 예 | 요청 형식 오류로 오류 로그 |
| 빈 응답/형식 불일치 | 1회 | 예 | 연속 실패 횟수 반영 |

회로 차단 상태는 프로세스 메모리에만 둔다. 영속화하지 않으며 성공 응답 후 연속 실패 카운터를 초기화한다.

### 단계 3. `TranslationService` 리팩터링

`app/llm/translator.py`를 다음 원칙으로 수정한다.

- 생성자에서 URL과 모델을 직접 받는 대신 기본·폴백 백엔드를 주입받는다.
- 프롬프트 구성, 180자 제한 재작성, 중국어 제목 감지, JSON 파싱 로직은 그대로 유지한다.
- 기존 `_request_translation()`은 백엔드 `generate()` 호출로 대체한다.
- `set_num_gpu()`는 등록된 Ollama 백엔드에만 전달한다.
- `translate_article(source, title, content)`와 `TranslationResult`는 유지한다.

마이그레이션 중 테스트 호환성이 필요하면 기존 생성자 인자를 한 단계 동안 지원한 뒤 제거한다. 최종적으로는 `build_translation_service(config)` 팩토리에서 백엔드 구성을 담당하게 한다.

### 단계 4. 설정 및 서비스 조립

`app/core/config.py`에 공급자 설정을 추가하고 허용값을 검증한다.

- 허용 공급자: `ollama`, `cloudflare`
- Cloudflare가 활성 공급자이지만 필수 값이 비어 있으면 시작 시 이해 가능한 설정 오류를 발생시킨다.
- 숫자 설정은 최소값을 적용해 음수 재시도나 0초 타임아웃을 방지한다.

`app/features/news/feature.py`에서는 직접 `TranslationService(...)`를 조립하지 않고 팩토리를 호출한다. `app.bot_data["translator"]` 키와 Semaphore는 그대로 유지한다.

`app/features/system_admin/feature.py`는 `TranslationService.set_num_gpu()`가 유지되므로 구조 변경 없이 동작해야 한다. Cloudflare가 기본이어도 GPU 토글은 폴백 Ollama 설정만 변경한다는 점을 시스템 상태 문구 또는 문서에 명시한다.

### 단계 5. 관찰 가능성 추가

요청마다 기사 본문을 기록하지 않고 다음 정보만 구조화해 로그에 남긴다.

- 공급자와 모델명
- 성공/실패/폴백 여부
- HTTP 상태 분류
- 소요시간(ms)
- 응답에 포함된 사용량이 있을 경우 입력·출력 토큰 수
- Cloudflare 회로 상태와 다음 재시도 가능 시각

예시:

```text
[TRANSLATE] provider=cloudflare model=@cf/qwen/qwen3-30b-a3b-fp8 result=success latency_ms=842 input_tokens=710 output_tokens=196
[TRANSLATE] provider=cloudflare result=quota_exhausted fallback=ollama circuit_open_until=2026-08-02T00:00:00Z
```

토큰 사용량이 응답에 없으면 비용을 임의로 확정하지 않고 `usage=unknown`으로 남긴다. Cloudflare 대시보드 사용량을 최종 기준으로 사용한다.

### 단계 6. 문서 갱신

다음 파일을 갱신한다.

- `.env.example`: 신규 환경변수와 비밀값 주의사항
- `README.md`: Cloudflare 또는 Ollama 선택 방법과 빠른 시작
- 배포 문서: 이후 `docs/deployment-lightsail-plan.md`로 대체됨

Cloudflare API 토큰에는 Workers AI 실행에 필요한 최소 권한만 부여한다. 토큰 발급 화면과 권한 이름은 Cloudflare 정책 변경 가능성이 있으므로 공식 문서 링크와 확인일을 함께 기록한다.

## 6. 테스트 계획

### 6.1 단위 테스트

새 파일 `tests/test_backends.py`에서 HTTP를 모킹해 다음을 검증한다.

- Cloudflare URL, 인증 헤더, 모델, 메시지, 타임아웃이 올바르게 구성된다.
- OpenAI 호환 정상 응답에서 콘텐츠를 추출한다.
- 빈 `choices`, 빈 `content`, 비 JSON 응답을 명확한 예외로 처리한다.
- 오류 로그와 예외 문자열에 API 토큰이 포함되지 않는다.
- 429·5xx·타임아웃은 재시도 대상이고 401·403·400은 즉시 분류된다.
- 일일 할당량 소진 시 다음 UTC 00시까지 회로가 열린다.
- 회로가 열린 동안 Cloudflare를 호출하지 않고 Ollama를 사용한다.
- 쿨다운 만료 후 Cloudflare를 다시 시도한다.
- 두 공급자가 모두 실패하면 `TranslationError`가 발생한다.

기존 `tests/test_sentiment.py`는 계속 통과해야 한다. 특히 다음 동작을 회귀 테스트로 유지한다.

- 180자 초과 결과 재작성
- 중국어 제목 재작성 및 한국어 본문 제목 폴백
- `mentioned_stocks`, `theme_candidates`, `sentiment`, `impact` 파싱
- 잘못된 JSON 또는 빈 본문 처리

### 6.2 통합 스모크 테스트

실제 Cloudflare 계정에서는 자동 테스트와 분리된 수동 스크립트 또는 opt-in pytest 마커로 아래 세 문장을 확인한다.

1. 중국어 제목과 본문
2. 종목코드·퍼센트·금액이 포함된 중국 금융 뉴스
3. 영어 또는 한국어 글로벌 뉴스

검증 항목:

- 응답이 단일 JSON 객체로 파싱되는가
- 제목과 본문이 한국어인가
- 숫자, 종목코드, 날짜가 보존되는가
- 본문이 완결된 문장이고 설정 길이 안에 들어오는가
- JSON Schema 모드 사용 가능 여부
- 응답의 `usage` 필드 제공 여부

실제 자격증명이 필요한 테스트는 기본 테스트 실행에서 제외한다.

```powershell
python -m pytest -q
$env:RUN_CLOUDFLARE_SMOKE='1'
python -m pytest -q -m cloudflare_smoke
```

## 7. 품질 검증과 승인 기준

기존 로컬 Qwen 결과와 Cloudflare Qwen3 결과를 동일한 기사 50~100건으로 비교한다. 운영 트래픽을 양쪽에 동시에 보내는 상시 섀도 호출은 무료 할당량을 이중 소비하므로 하지 않는다.

### 2026-08-01 예비 비교 (1건, 정식 표본 아님)

같은 기사(贵州茅台 반기 실적)를 양쪽에 한 번씩 돌린 결과다. 표본이 아니므로
승인 판정에는 쓰지 않지만, 방향은 참고할 만하다.

| | Cloudflare Qwen3-30B | 로컬 Ollama qwen3.5:4b |
|---|---|---|
| 지연시간 | 1.6초 | 26초 |
| 금액 보존 | 880.3억·430.2억 정확 | **8,803억·4,302억으로 10배 오류** |
| 한자 잔존 | 고유명사(贵州茅台) | 고유명사 + `归母净利润`·`上半` |

**로컬 모델의 금액 10배 오류가 더 위험하다.** 즉 이 건에서는 Cloudflare 전환이
품질 저하가 아니라 개선이다. 반면 **고유명사 한자 잔존은 양쪽 공통**이므로 공급자
문제가 아니라 프롬프트 문제다. `_looks_untranslated_chinese()`는 "한글이 하나라도
있으면 통과"라서 부분 잔존을 잡지 못한다는 점도 함께 확인됐다.

최소 승인 기준:

| 항목 | 기준 |
|---|---:|
| 필수 JSON 필드 파싱 성공률 | 99% 이상(재작성 포함) |
| 중국어만 남은 제목 비율 | 1% 미만 |
| 숫자·날짜·금액·명시 종목 보존 | 표본 기준 98% 이상 |
| 원문에 없는 중대한 사실 추가 | 표본 0건 |
| Cloudflare 단독 요청 성공률 | 95% 이상 |
| Ollama 폴백 포함 최종 성공률 | 99% 이상 |
| 비밀값 로그 노출 | 0건 |

품질 기준을 충족하지 못하면 다음 순서로 조정한다.

1. 시스템 프롬프트와 출력 예시 보강
2. `max_tokens`, `temperature` 조정
3. JSON Schema 모드 활성화
4. 대체 Cloudflare 다국어 모델 비교
5. 기준 미달 시 로컬 Ollama를 기본 공급자로 유지

## 8. 무료 할당량과 호출량 관리

2026-08-01 확인 기준 Workers AI 무료 할당량은 하루 10,000 Neurons이며 UTC 00시에 초기화된다. 한국시간으로는 매일 오전 9시다. Qwen3 모델 가격은 입력 100만 토큰당 4,625 Neurons, 출력 100만 토큰당 30,475 Neurons으로 안내되어 있다.

예상 사용량 계산식:

```text
예상 Neurons
= 입력 토큰 / 1,000,000 × 4,625
+ 출력 토큰 / 1,000,000 × 30,475
```

예를 들어 기사 한 건당 입력 1,000토큰, 출력 300토큰이면 약 13.8 Neurons이며, 동일한 크기의 요청만 있다고 가정할 때 무료 할당량은 약 720건이다. 실제 프롬프트 길이, 재작성 호출, 모델 토크나이저와 Cloudflare 과금값에 따라 달라지므로 첫 운영 주간에는 대시보드 실측값으로 보정한다.

### 2026-08-01 실측 (응답의 `usage.neurons` 기준)

Cloudflare 응답이 `usage.neurons`를 직접 돌려주므로 추정 대신 이 값을 쓴다.
`global_ko.txt` 프롬프트 + 중국어 기사 1건 기준:

| 구성 | 입력 | 출력 | Neurons/건 | 무료 할당량 환산 |
|---|---:|---:|---:|---:|
| `/no_think` 적용(현재 구현) | 735 | 154 | **7.8** | 약 1,280건/일 |
| thinking 방치 | 735 | 1,024(잘림) | 34.3 | 약 290건/일 |

**Qwen3의 thinking을 억제하지 않으면 비용이 4배가 되고 응답도 깨진다.** 추론이
`max_tokens`를 전부 소진해 `finish_reason=length`로 content가 잘리기 때문이다.
`CloudflareWorkersAIBackend`가 Qwen3 모델일 때 시스템 프롬프트 끝에 `/no_think`를
붙여 이를 막는다. `chat_template_kwargs`의 `enable_thinking=false`는 이 엔드포인트에서
content를 아예 비우므로 대안이 되지 못한다(실측 확인).

### 2026-08-01 적용 범위 확대 후 일일 예산 (번역 + 리서치 + 브리핑)

`RESEARCH_ANALYSIS_PROVIDER`·`BRIEFING_PROVIDER`가 기본적으로 `TRANSLATION_PROVIDER`를
따라가므로 세 용도가 모두 Cloudflare로 간다. 실측 단가와 운영 이력(`news_log.json`
기준 풀 가동일 165~177건)으로 계산한 일일 예산은 다음과 같다.

| 용도 | 1회 Neurons | 일일 횟수 | 소계 |
|---|---:|---:|---:|
| 뉴스 번역(본문 300자, 재작성 30% 가정) | 14.4 | 300 | 4,320 |
| 리서치 분석(`/research` 수동) | 107 | 5 | 535 |
| 브리핑 코멘트 | 18 | 2 | 36 |
| | | **합계** | **약 4,900 (무료 10,000의 49%)** |

- 번역 400건 + 리서치 10회 → 약 6,900 (69%)
- 번역 500건 + 리서치 20회 → 약 9,400 (94%) — 여기가 한계선
- **무료 한도는 월 합산이 아니라 일일 10,000이 UTC 00시에 리셋된다.** 매일 한도
  안에 들면 한 달 내내 무료다.
- 소진되면 회로가 다음 UTC 00시까지 열리고 자동으로 Ollama 폴백으로 돈다. 봇이
  멈추지는 않지만 로컬 4B 품질·속도로 떨어진다.
- 추정에 의존하지 않도록 `usage.neurons`를 `[TRANSLATE]` 로그에 그대로 남긴다.
  `journalctl -u china-chatbot | grep neurons=`로 실사용량을 합산할 수 있다.

할당량 절감 순서:

1. 중복 기사 필터링 후에만 번역한다.
2. 현재처럼 선택된 기사만 번역하고 리서치의 `RESEARCH_TRANSLATE_NEWS=false` 기본값을 유지한다.
3. 프롬프트의 중복 문장을 줄이되 출력 계약은 유지한다.
4. 긴 원문 입력 상한을 별도 설정으로 추가한다.
5. 무료 할당량 소진 시 같은 날은 자동으로 Ollama만 사용한다.

무료 플랜에서는 한도 초과 시 요청이 실패한다. 유료 Workers 플랜으로 전환하기 전에는 별도의 운영 승인과 월 비용 상한을 정한다.

## 9. 배포 순서

### 1차 배포: 구조 리팩터링

- Ollama 백엔드만 연결한 상태로 공급자 인터페이스를 분리한다.
- 전체 테스트를 실행해 기존 동작과 결과가 동일한지 확인한다.
- 운영 설정은 `TRANSLATION_PROVIDER=ollama`로 유지한다.

### 2차 배포: Cloudflare 비활성 코드 배포

- Cloudflare 백엔드, 오류 분류, 폴백, 회로 차단 테스트를 추가한다.
- 기본값은 계속 `ollama`로 둔다.
- 수동 스모크 테스트로 계정·토큰·응답 형식을 검증한다.

### 3차 배포: 제한적 Cloudflare 전환

- 비운영 또는 짧은 관찰 구간에 `TRANSLATION_PROVIDER=cloudflare`를 적용한다.
- 50~100건 품질 표본과 사용 Neurons를 측정한다.
- Cloudflare 오류를 강제로 모킹하거나 테스트 환경에서 차단해 Ollama 폴백을 검증한다.

### 4차 배포: 운영 전환

- 품질·비용 승인 기준을 통과하면 Cloudflare를 기본 공급자로 전환한다.
- 첫 24시간은 성공률, p95 지연시간, 폴백률, 무료 할당량을 집중 확인한다.
- 장애 또는 품질 저하 시 환경변수 한 줄로 Ollama 기본 구성으로 롤백한다.

## 10. 완료 조건

- [x] 공급자별 백엔드와 라우터가 구현되어 있다.
      (`app/llm/backends.py`, 조립은 `app/llm/translation_factory.py`)
- [x] Cloudflare Qwen3 정상 호출과 로컬 Ollama 폴백이 동작한다(모킹 기준).
- [x] 무료 할당량 소진 후 Cloudflare 반복 호출을 멈춘다(다음 UTC 00시까지).
- [x] 기존 번역 결과 계약과 뉴스·리서치 호출부가 유지된다.
      `TranslationService.translate_article()`·`TranslationResult`·`set_num_gpu()` 그대로.
- [x] 기존 테스트와 신규 단위 테스트가 모두 통과한다.
      (`tests/test_backends.py` 37건 추가)
- [x] 실제 Cloudflare 스모크 테스트를 통과한다(2026-08-01, 3건 전부 통과).
      `RUN_CLOUDFLARE_SMOKE=1` + `-m cloudflare_smoke`로 재현한다.
- [x] `.env.example`, `README.md`, 배포 문서가 갱신되어 있다.
- [x] API 토큰이 Git, 로그, 오류 메시지에 노출되지 않는다(마스킹 회귀 테스트 포함).
- [ ] 품질 표본과 첫 운영일 사용량을 기록했다. → 3차 배포에서 수행

## 11. 후속 검토 항목

- 순수 번역과 종목·감성 분석을 분리해 M2M100과 Qwen을 조합할 가치가 있는지 비용·품질 비교
- Cloudflare AI Gateway를 통한 요청 관찰, 캐시, 속도 제한 적용
- 번역 결과 캐시를 도입해 동일 기사 재처리 비용 제거
- Cloudflare가 반환하는 토큰 사용량을 일별 로컬 통계로 집계
- 번역뿐 아니라 `MarketViewAnalyzer`, `BriefingWriter`까지 공급자 인터페이스를 공통화할지 검토

## 12. 참고 문서

- [Cloudflare Workers AI 가격](https://developers.cloudflare.com/workers-ai/platform/pricing/)
- [Cloudflare Qwen3 30B A3B 모델](https://developers.cloudflare.com/workers-ai/models/qwen3-30b-a3b-fp8/)
- [OpenAI 호환 API 엔드포인트](https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/)
- [Cloudflare Workers AI JSON Mode](https://developers.cloudflare.com/workers-ai/features/json-mode/)
- [Cloudflare M2M100 번역 모델](https://developers.cloudflare.com/workers-ai/models/m2m100-1.2b/)
