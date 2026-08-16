"""어떤 Polymarket 계약을 읽고 어느 방향으로 셀지 정하는 규칙.

두 가지를 한다.

1. **게이트** — active·closed·volume·liquidity·spread·만기·잔여기간·가격 극단.
   여기를 통과하지 못한 계약은 조용히 버리고 이유만 센다.
2. **theme allowlist와 polarity** — 질문 문구를 명시적 패턴에 맞춰
   `risk-on(+1)` / `risk-off(-1)` 로만 분류한다.

**방향을 LLM에게 묻지 않는다.** 확률 하나에 모델 호출을 붙이면 이 경로의
Neurons가 0/일이라는 전제가 무너지고, 무엇보다 같은 질문이 날마다 다른 방향으로
분류되면 일별 delta가 규칙이 아니라 모델 변덕을 그리게 된다.

allowlist이므로 **어떤 패턴에도 걸리지 않으면 제외**가 기본이다. 홍콩 상위
유동성이 당일 기온 마켓이었던 실측처럼, 거시 위험선호와 무관한 질문이 조용히
섞여 들어오는 쪽이 결측보다 나쁘다.

`_REGIME_DEPENDENT_PATTERNS`는 allowlist보다 우선한다. GDP 구간·금리 결정처럼
Yes의 의미가 국면에 따라 뒤집히는 질문은, allowlist 단어를 우연히 포함하더라도
집계에 넣지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from features.market_sentiment.polymarket import PolymarketContract

RISK_ON = 1
RISK_OFF = -1

# 만기가 코앞인 계약은 확률이 0/1로 수렴하는 기계적 움직임이 커서 하루 변화가
# 위험선호가 아니라 만기 효과를 그린다.
_MIN_HORIZON_DAYS = 2
# 사실상 결판난 계약(양 끝)도 같은 이유로 뺀다.
_EXTREME_PRICE_MARGIN = 0.02


def _patterns(*expressions: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(expression, re.IGNORECASE) for expression in expressions)


@dataclass(frozen=True)
class Theme:
    key: str
    polarity: int
    patterns: tuple[re.Pattern[str], ...]


# Yes가 무엇을 뜻하는지 문구만으로 단정할 수 있는 질문만 담는다. 애매하면
# 여기에 넣지 않는 쪽이 맞다 — 빠진 theme은 결측이지만, 잘못 넣은 theme은
# 반대 부호로 집계에 들어간다.
THEMES: tuple[Theme, ...] = (
    Theme(
        "military_conflict",
        RISK_OFF,
        _patterns(
            r"\binvade\b",
            r"\binvasion\b",
            r"\bmilitary (?:action|strike|conflict|intervention)\b",
            r"\b(?:air|missile|nuclear) strike\b",
            r"\bnuclear (?:test|weapon|detonation)\b",
            r"\bdeclare war\b",
            r"\bgo to war\b",
            r"\barmed conflict\b",
        ),
    ),
    Theme(
        "conflict_resolution",
        RISK_ON,
        _patterns(
            r"\bcease[- ]?fire\b",
            r"\bpeace (?:deal|agreement|plan|treaty)\b",
            r"\btruce\b",
        ),
    ),
    Theme(
        "trade_deal",
        RISK_ON,
        _patterns(
            r"\btrade (?:deal|agreement|truce|pact)\b",
            r"\btariff (?:deal|agreement|rollback)\b",
            r"\b(?:lift|remove|cut) tariffs\b",
        ),
    ),
    Theme(
        "trade_restriction",
        RISK_OFF,
        _patterns(
            r"\b(?:impose|raise|increase|announce) (?:new )?tariffs\b",
            r"\btariff (?:increase|hike)\b",
            r"\bexport (?:ban|controls)\b",
            r"\b(?:new|additional) sanctions\b",
            r"\bsanctions on\b",
        ),
    ),
    Theme(
        "equity_upside",
        RISK_ON,
        _patterns(
            r"\b(?:s&p ?500|nasdaq|dow(?: jones)?|russell 2000)\b[^?]*\b(?:above|over|reach|hit|exceed)\b",
            r"\b(?:all[- ]time|record) high\b",
        ),
    ),
    Theme(
        "equity_downside",
        RISK_OFF,
        _patterns(
            r"\b(?:s&p ?500|nasdaq|dow(?: jones)?|russell 2000)\b[^?]*\b(?:below|under|fall|drop)\b",
            r"\bbear market\b",
            r"\bmarket crash\b",
            r"\bstock market correction\b",
        ),
    ),
    Theme(
        "macro_stress",
        RISK_OFF,
        _patterns(
            r"\brecession\b",
            r"\bgovernment shutdown\b",
            r"\b(?:sovereign|debt) default\b",
            r"\bbank (?:failure|run)\b",
        ),
    ),
)

# allowlist보다 먼저 본다. Yes의 방향이 국면에 따라 뒤집히는 질문 형태다.
_REGIME_DEPENDENT_PATTERNS = _patterns(
    r"\bgdp\b",
    r"\bcpi\b",
    r"\binflation\b",
    r"\bunemployment\b",
    r"\bjobs report\b",
    r"\b(?:interest )?rate (?:cut|hike|decision|hold)\b",
    r"\brate[s]? (?:unchanged|steady)\b",
    r"\bbasis points\b",
    r"\bfomc\b",
    r"\bfederal reserve\b",
    r"\bbank of (?:korea|japan|england)\b",
    r"\becb\b",
    r"\bcentral bank\b",
    r"\bemergency (?:rate )?cut\b",
)


def classify_theme(question: str) -> tuple[str, int] | None:
    """질문을 (theme, polarity)로 분류한다. 분류할 수 없으면 None.

    부호가 다른 theme에 동시에 걸리면(예: 휴전 합의를 다룬 전쟁 질문) 방향을
    고를 근거가 없으므로 버린다.
    """
    text = str(question or "")
    if not text.strip():
        return None
    if any(pattern.search(text) for pattern in _REGIME_DEPENDENT_PATTERNS):
        return None

    matched = [
        theme
        for theme in THEMES
        if any(pattern.search(text) for pattern in theme.patterns)
    ]
    if not matched:
        return None
    if len({theme.polarity for theme in matched}) > 1:
        return None
    return matched[0].key, matched[0].polarity


@dataclass(frozen=True)
class SelectedContract:
    """게이트와 분류를 통과한 계약. 스냅숏에 그대로 저장된다."""

    contract: PolymarketContract
    theme: str
    polarity: int


def static_rejection(
    contract: PolymarketContract,
    *,
    min_volume: float,
    min_liquidity: float,
    max_spread: float,
) -> str:
    """시점과 무관한 수량·호가 게이트. 통과하면 빈 문자열.

    **여기 쓰이는 값은 언제나 "지금"의 값이다.** Gamma는 과거 시점의 유동성·
    호가를 주지 않으므로, 백필은 이 게이트를 과거 각 날짜가 아니라 조회 시점의
    값으로 한 번만 적용한다(`polymarket_history.py`가 그 한계를 적어 둔다).
    """
    if contract.volume < min_volume:
        return "volume"
    if contract.liquidity < min_liquidity:
        return "liquidity"
    if contract.spread > max_spread:
        return "spread"
    return ""


def moment_rejection(
    contract: PolymarketContract,
    price: float,
    moment: datetime,
    *,
    max_horizon_days: int,
) -> str:
    """그 시점에만 뜻이 있는 게이트(잔여 지평·가격 극단). 통과하면 빈 문자열.

    백필은 과거 날짜마다 이 함수를 다시 부른다. 만기 이틀 전부터는 확률이 0/1로
    수렴하는 기계적 움직임이 커서, 같은 계약이라도 어제는 되고 오늘은 안 된다.
    """
    horizon_reason = _horizon_reason(contract, moment)
    if horizon_reason:
        return horizon_reason
    if (contract.end_date - moment).days > max_horizon_days:
        return "horizon_too_far"
    if not (_EXTREME_PRICE_MARGIN <= price <= 1 - _EXTREME_PRICE_MARGIN):
        return "price_extreme"
    return ""


def _horizon_reason(contract: PolymarketContract, moment: datetime) -> str:
    if contract.end_date is None:
        return "no_end_date"
    remaining = (contract.end_date - moment).total_seconds() / 86400
    if remaining < 0:
        # closed=false인데 만기가 지난 계약. 사유를 구분해 둬야 커버리지가 줄었을
        # 때 게이트 탓인지 응답이 이상한 탓인지 알 수 있다.
        return "expired"
    if remaining < _MIN_HORIZON_DAYS:
        return "horizon_too_near"
    return ""


def select_contracts(
    contracts: list[PolymarketContract],
    *,
    min_volume: float,
    min_liquidity: float,
    max_spread: float,
    max_horizon_days: int,
    moment: datetime,
) -> tuple[list[SelectedContract], dict[str, int]]:
    """게이트와 allowlist를 통과한 계약과, 탈락 사유별 건수를 함께 돌려준다.

    사유 집계는 로그로만 쓴다. 커버리지가 왜 줄었는지(게이트가 셌는지, 마켓
    자체가 사라졌는지) 30일 파일럿 중에 구분할 수 있어야 하기 때문이다.
    """
    selected: list[SelectedContract] = []
    rejected: dict[str, int] = {}

    def reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    for contract in contracts:
        if contract.closed:
            reject("closed")
            continue
        if not contract.active:
            reject("inactive")
            continue
        static_reason = static_rejection(
            contract,
            min_volume=min_volume,
            min_liquidity=min_liquidity,
            max_spread=max_spread,
        )
        if static_reason:
            reject(static_reason)
            continue
        moment_reason = moment_rejection(
            contract,
            contract.yes_price,
            moment,
            max_horizon_days=max_horizon_days,
        )
        if moment_reason:
            reject(moment_reason)
            continue
        classified = classify_theme(contract.question)
        if classified is None:
            reject("no_theme")
            continue
        theme, polarity = classified
        selected.append(SelectedContract(contract, theme, polarity))

    return selected, rejected
