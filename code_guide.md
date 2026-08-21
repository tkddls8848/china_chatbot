# Role

너는 현재 이 저장소를 지속적으로 유지보수하고 개발할 **Senior Software Architect + Refactoring Engineer**다.

이번 작업의 목적은 단순히 코드 스타일을 정리하거나 추상화를 늘리는 것이 아니다.

**향후 Codex/LLM을 이용한 바이브코딩의 개발 속도, 정확도, 컨텍스트 효율, 수정 안정성을 극대화하도록 현재 코드베이스를 재구성하라.**

즉 다음 질문을 기준으로 리팩터링한다.

> "앞으로 LLM이 이 코드베이스에서 기능 추가, 버그 수정, 리팩터링을 수행할 때 최소한의 파일과 최소한의 컨텍스트만 읽고도 안전하게 작업할 수 있는가?"

---

# Primary Objectives

다음 우선순위를 따른다.

1. **LLM Context Efficiency**
2. **코드 이해 가능성**
3. **변경 범위의 국소화(Locality of Change)**
4. **모듈 간 결합도 감소**
5. **명확한 책임 분리**
6. **테스트 가능성**
7. **회귀(regression) 위험 감소**
8. **사람 개발자에게도 자연스러운 유지보수성**
9. 성능
10. 코드 축약

코드 길이를 줄이는 것 자체가 목표가 아니다.

---

# Step 1 — Repository Analysis

먼저 코드를 수정하지 말고 저장소 전체를 분석하라.

다음을 파악한다.

- 프로젝트 구조
- 애플리케이션 entry point
- 핵심 domain
- 주요 feature
- data flow
- API flow
- state management
- persistence/database layer
- external service integration
- configuration/environment handling
- shared utilities
- test structure
- build/deploy structure
- dependency graph
- 순환 dependency
- 지나치게 큰 파일
- 지나치게 큰 function/class/component
- 여러 책임을 가진 module
- 중복 구현
- 암묵적 dependency
- global state
- magic constants
- side effect가 섞인 코드
- 이름만 보고 역할을 추론하기 어려운 코드
- LLM이 여러 파일을 동시에 읽어야만 이해할 수 있는 구조

분석 후 현재 architecture를 간략하게 설명하라.

---

# Step 2 — Identify LLM-Unfriendly Code

특히 다음 패턴을 찾아라.

## A. Large Context Requirement

한 기능을 이해하기 위해 너무 많은 파일을 읽어야 하는 구조.

예:

- business logic이 여러 layer에 흩어짐
- 핵심 동작이 helper chain을 지나야 이해됨
- 지나친 abstraction
- 한 feature가 여러 unrelated directory에 분산됨

가능하면 관련 코드를 **feature/domain 단위로 가까이 배치**한다.

---

## B. God Files / God Objects

다음에 해당하는 파일을 찾아라.

- 너무 많은 책임을 가진 파일
- 변경 이유가 여러 개인 파일
- 여러 domain을 동시에 다루는 service
- 거대한 controller
- 거대한 React/Vue component
- 지나치게 긴 utility 파일

논리적 책임 단위로 분리한다.

단, 파일을 지나치게 잘게 쪼개서 오히려 LLM이 더 많은 파일을 읽게 만들지 않는다.

---

## C. Excessive Abstraction

LLM과 사람 모두 이해하기 어려운 abstraction을 제거한다.

특히:

- 한 번만 사용되는 wrapper
- 의미 없는 interface layer
- 불필요한 factory
- 불필요한 adapter
- trivial helper
- 지나친 inheritance
- 추상화를 위한 추상화

다음 원칙을 따른다.

> Explicit &gt; Clever

> Local clarity &gt; theoretical abstraction purity

---

## D. Hidden Behavior

코드를 읽었을 때 실행 결과를 예측하기 어려운 구조를 개선한다.

예:

- 암묵적 global mutation
- hidden side effect
- decorator에 숨겨진 주요 동작
- 지나친 middleware chain
- magic dependency injection
- runtime monkey patch
- implicit initialization

가능하면 중요한 흐름은 코드상에서 명확히 드러나도록 한다.

---

# Step 3 — Optimize Module Boundaries

각 module은 다음 질문에 명확히 답할 수 있어야 한다.

> "이 파일은 무엇을 담당하는가?"

가능하면 **하나의 명확한 이유로만 변경되는 구조**를 만든다.

특히 다음 boundary를 명확하게 하라.

- UI
- application/use-case
- domain/business logic
- infrastructure
- persistence
- external API
- configuration
- shared primitives

프로젝트 규모에 맞지 않는 과도한 Clean Architecture/DDD 구조를 강제하지 않는다.

**현재 프로젝트에서 실제로 필요한 수준까지만 분리한다.**

---

# Step 4 — Optimize for Locality of Change

향후 기능 하나를 수정할 때 가능한 한 관련 코드가 가까운 위치에 있도록 한다.

목표:

> 대부분의 일반적인 기능 변경이 1~3개의 핵심 파일 안에서 해결 가능해야 한다.

단순한 기능 하나를 수정하기 위해 8~10개 파일을 수정해야 하는 구조는 개선 대상으로 본다.

---

# Step 5 — Naming

LLM이 코드 검색만으로 역할을 추론할 수 있도록 이름을 개선한다.

피해야 할 이름:

- utils
- helper
- common
- misc
- manager
- processor
- handler

단, 역할이 실제로 명확한 경우는 허용한다.

보다 구체적인 이름을 사용한다.

예:

`utils.ts`

보다

`formatOrderPrice.ts`

또는

`orderFormatting.ts`

처럼 검색 가능한 domain vocabulary를 선호한다.

function / class / variable 이름은 구현 방식보다 **의도(intent)** 를 표현한다.

---

# Step 6 — Functions

가능하면 function은 다음 특성을 갖게 한다.

- 하나의 명확한 역할
- 명확한 input/output
- hidden side effect 최소화
- 적당한 크기
- 의미 있는 이름
- 독립적 테스트 가능

다만 모든 function을 무조건 작게 만들지 않는다.

여러 개의 trivial helper로 쪼개어 실행 흐름을 따라가기 어렵게 만드는 리팩터링은 피한다.

---

# Step 7 — Types / Contracts

가능한 경우 module 사이의 contract를 명확하게 만든다.

예:

- TypeScript type/interface
- Python dataclass / TypedDict / Pydantic
- API schema
- DTO
- validation schema

`any`, untyped dictionary, dynamic object 등으로 인해 데이터 구조를 추론해야 하는 부분을 줄인다.

LLM이 type 정의만 읽어도 data shape를 이해할 수 있도록 한다.

---

# Step 8 — Error Handling

에러 처리 방식을 일관성 있게 만든다.

다음을 제거하거나 개선한다.

- silent failure
- 광범위한 try/catch
- 의미 없는 generic exception
- swallowed exception
- console.log만 남기는 오류 처리

error boundary를 명확히 한다.

---

# Step 9 — Configuration

다음을 중앙화하고 명확하게 한다.

- environment variable
- feature flag
- API endpoint
- timeout
- retry
- model name
- external service option
- magic number

다만 거대한 global config 파일 하나에 모든 것을 넣지는 않는다.

---

# Step 10 — Tests as LLM Safety Rails

리팩터링 전후 behavior가 유지되는지 검증할 수 있도록 테스트를 활용하라.

특히 다음 부분에 테스트가 부족하다면 우선적으로 추가한다.

- 핵심 business logic
- critical data transformation
- authentication/authorization
- payment
- persistence
- 외부 API integration boundary
- 복잡한 condition
- 과거 bug가 발생하기 쉬운 부분

테스트는 implementation detail보다 **observable behavior**를 검증해야 한다.

리팩터링 과정에서 기존 테스트를 깨뜨리지 않는다.

---

# Step 11 — Repository Documentation for Future LLMs

향후 Codex가 저장소를 처음 읽었을 때 빠르게 구조를 이해할 수 있도록 필요한 경우 documentation을 개선한다.

가능하면 root 또는 적절한 위치에 다음 내용을 간결하게 문서화한다.

## Architecture

- 프로젝트가 무엇을 하는지
- 주요 architecture
- 주요 directory 역할
- 핵심 data flow

## Development

- 실행 방법
- 테스트 방법
- lint/typecheck
- build 방법

## Modification Guide

다음과 같은 내용을 포함할 수 있다.

- 새 API 추가 위치
- 새 feature 추가 위치
- database schema 변경 위치
- 외부 integration 추가 위치
- UI component 추가 위치
- business rule 수정 위치

문서는 장황한 설명보다 **LLM이 작업 위치를 빠르게 찾는 navigation map** 역할을 해야 한다.

---

# Step 12 — [AGENTS.md](http://AGENTS.md) Optimization

현재 저장소에 [`AGENTS.md`](http://AGENTS.md) 또는 Codex용 instruction 파일이 존재한다면 검토하라.

없고 실제로 도움이 된다면 생성할 수 있다.

내용은 짧고 actionable하게 유지한다.

예:

- project architecture
- directory conventions
- commands
- testing requirements
- coding conventions
- 수정 금지 영역
- generated files
- validation commands

코드 자체에서 알 수 있는 내용을 문서에 반복하지 않는다.

---

# Step 13 — Delete Dead Weight

확실하게 사용되지 않는다면 다음을 제거한다.

- dead code
- unused exports
- unused dependency
- legacy compatibility layer
- stale comments
- duplicate helpers
- obsolete TODO
- abandoned feature code

단, 사용 여부가 불확실하면 임의로 삭제하지 말고 먼저 reference를 조사한다.

---

# Refactoring Constraints

다음 규칙을 반드시 지킨다.

## Preserve Behavior

사용자가 요청하지 않은 product behavior 변경은 하지 않는다.

리팩터링 전후 외부 동작은 동일해야 한다.

---

## Avoid Rewrite

기존 코드가 충분히 작동한다면 전체 rewrite를 하지 않는다.

incremental refactoring을 선호한다.

---

## Avoid Architecture Astronautics

다음을 이유 없이 도입하지 않는다.

- 새로운 framework
- 새로운 state management library
- 새로운 dependency injection framework
- 새로운 ORM
- 새로운 architecture pattern
- event bus
- CQRS
- microservice
- repository pattern

실제 문제를 해결하는 경우에만 사용한다.

---

## Dependency Discipline

새 dependency 추가보다 기존 언어/프레임워크 기능을 우선한다.

새 dependency가 필요하다면 반드시 이유를 설명한다.

---

# LLM Optimization Heuristics

리팩터링 판단 시 다음 heuristic을 적극 활용한다.

### 좋은 구조

LLM이 다음 순서만으로 기능을 이해할 수 있다.

1. feature 파일 검색
2. 해당 module 읽기
3. type/interface 확인
4. test 확인
5. 수정

### 나쁜 구조

LLM이 하나의 기능을 이해하려고

- 15개 파일 검색
- inheritance hierarchy 탐색
- dependency injection 추적
- global state 추론
- generic helper 해석

등을 해야 한다.

후자라면 구조 개선을 검토한다.

---

# Context Budget Principle

각 리팩터링에 대해 다음 질문을 던져라.

> "이 변경으로 향후 LLM이 같은 기능을 수정할 때 읽어야 하는 토큰 수가 감소하는가?"

가능하면 **Context Surface Area**를 줄인다.

다만 코드 duplication이 심각하게 증가하면 안 된다.

---

# Searchability Principle

LLM은 repository search를 적극 사용하므로 검색 친화성을 높인다.

- domain term을 이름에 사용
- generic naming 최소화
- 관련 코드의 위치 예측 가능
- 파일 이름만 보고 역할 추론 가능
- 동일 개념에 동일한 용어 사용

예:

`customer`, `client`, `user`를 동일 개념에 혼용하지 않는다.

---

# Change Predictability Principle

한 module을 변경했을 때 어떤 영역에 영향을 주는지 쉽게 예측할 수 있어야 한다.

unexpected coupling을 제거한다.

---

# Execution Strategy

전체 리팩터링을 한 번에 수행하지 않는다.

먼저 분석 후 **우선순위가 높은 리팩터링 후보를 선정**한다.

각 후보에 대해 아래 형식으로 평가한다.


| 항목       | 설명                       |
| -------- | ------------------------ |
| Problem  | 현재 구조의 문제                |
| LLM Cost | LLM 작업 시 발생하는 컨텍스트/추론 비용 |
| Refactor | 제안하는 변경                  |
| Benefit  | 기대 효과                    |
| Risk     | 회귀 위험                    |
| Priority | High / Medium / Low      |


이후 **High priority + Low/Medium risk** 항목부터 작업한다.

---

# Implementation Loop

각 리팩터링 단위마다 다음 순서를 따른다.

1. 관련 코드 탐색
2. 현재 behavior 파악
3. 관련 테스트 확인
4. 필요 시 regression test 추가
5. 최소 범위로 리팩터링
6. test 실행
7. lint 실행
8. typecheck 실행
9. build 실행
10. diff 검토

프로젝트에 존재하는 명령만 사용한다.

---

# Self Review

작업 후 스스로 다음 항목을 점검한다.

- 기존 behavior가 변경되지 않았는가?
- 불필요한 abstraction이 추가되지 않았는가?
- 파일 수만 늘어난 것은 아닌가?
- LLM이 읽어야 할 context가 실제로 감소했는가?
- 이름만 보고 역할을 이해할 수 있는가?
- 관련 코드가 가까이 위치하는가?
- 테스트가 변경을 보호하는가?
- 새로운 developer/LLM이 구조를 빠르게 이해할 수 있는가?
- 새 dependency가 정말 필요한가?
- 삭제 가능한 legacy code가 남아 있지 않은가?

---

# Final Deliverable

작업 완료 후 다음 형식으로 보고한다.

## 1. Initial Assessment

기존 코드베이스에서 LLM 기반 개발 효율을 낮추고 있던 핵심 문제.

## 2. Refactoring Performed

실제로 변경한 architecture/module/file 구조.

## 3. Why This Helps LLM Coding

각 변경이 Codex/LLM 작업에 어떤 이점을 주는지 설명.

특히:

- context 감소
- 검색성 향상
- 변경 범위 감소
- dependency 추론 감소
- regression 위험 감소

를 구분해서 설명한다.

## 4. Validation

실행한:

- tests
- lint
- typecheck
- build

결과.

## 5. Remaining Issues

이번 작업에서 의도적으로 건드리지 않은 기술 부채.

## 6. Recommended Next Refactors

ROI 기준으로 다음 리팩터링 후보를 최대 5개 제안한다.

---

# Final Principle

이번 리팩터링의 최종 목적은 "더 아름다운 코드"가 아니다.

목표는 다음 상태다.

> **사람과 LLM 모두가 코드의 위치와 역할을 빠르게 예측할 수 있고, 하나의 기능 변경을 위해 읽고 수정해야 하는 범위가 작으며, 테스트를 통해 안전하게 반복 수정할 수 있는 코드베이스.**

복잡한 설계보다 명시적인 설계를 선호하라.

추상화보다 탐색 가능성을 우선하라.

코드 축약보다 변경 안정성을 우선하라.

그리고 무엇보다:

> **Optimize the repository not only for runtime execution, but also for future LLM reasoning and modification.**

이제 현재 저장소를 분석하고, 위 기준에 따라 가장 ROI가 높은 리팩터링부터 실제로 수행하라.