"""하루치 헤드라인을 한 번에 분석해 시장 감성과 분류 건수를 산출한다."""

import json
import logging
import math
from pathlib import Path
from typing import Any

from llm.backends import LLMBackend

logger = logging.getLogger(__name__)


class MarketDigestError(RuntimeError):
    """Raised when a daily market digest cannot be produced."""


class MarketDigestAnalyzer:
    def __init__(
        self,
        backend: LLMBackend,
        enabled: bool,
        prompt_file: Path,
        num_predict: int = 256,
        count_tolerance_ratio: float = 0.1,
    ):
        self._backend = backend
        self._enabled = enabled
        self._num_predict = num_predict
        self._count_tolerance_ratio = max(0.0, float(count_tolerance_ratio))
        self._prompt = prompt_file.read_text(encoding="utf-8")

    def _count_tolerance(self, expected_count: int) -> int:
        """허용 오차. 최소 1건은 봐준다(세기 부정확은 정상 범위)."""
        return max(1, math.ceil(expected_count * self._count_tolerance_ratio))

    @property
    def enabled(self) -> bool:
        return self._enabled

    def analyze(
        self,
        market: str,
        day: str,
        headlines: list[str],
    ) -> dict[str, Any]:
        """헤드라인 목록에서 그날의 종합 감성을 만든다(블로킹)."""
        if not self._enabled:
            raise MarketDigestError("market digest LLM is disabled")
        if not headlines:
            raise MarketDigestError("no headlines to summarize")

        payload = {"market": market, "date": day, "headlines": headlines}
        try:
            raw = self._backend.generate(
                system_prompt=self._prompt,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                max_tokens=self._num_predict,
                temperature=0.2,
            )
        except Exception as exc:
            raise MarketDigestError(str(exc)) from exc

        if not raw.strip():
            raise MarketDigestError("empty digest response content")
        return self._parse(raw, expected_count=len(headlines))

    def _parse(self, raw: str, *, expected_count: int) -> dict[str, Any]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            # 원문은 남기지 않는다. 길이만으로도 잘림 여부는 판단할 수 있다.
            raise MarketDigestError(
                f"digest JSON parse failed ({exc}); raw_chars={len(raw)}"
            ) from exc
        if not isinstance(data, dict):
            raise MarketDigestError("digest JSON must be an object")

        sentiment = data.get("sentiment")
        if not isinstance(sentiment, (int, float)):
            raise MarketDigestError("digest sentiment must be a number")

        counts = {
            name: data.get(name)
            for name in ("positive", "negative", "neutral")
        }
        normalized_counts: dict[str, int | None] = {}
        for name, value in counts.items():
            normalized_counts[name] = int(value) if isinstance(value, int) else None

        total = sum(value for value in normalized_counts.values() if value is not None)
        complete = all(value is not None for value in normalized_counts.values())
        drift = abs(total - expected_count)
        tolerance = self._count_tolerance(expected_count)
        if not complete:
            raise MarketDigestError("digest counts are missing")
        if drift > tolerance:
            raise MarketDigestError(
                f"digest counts {total} != headlines {expected_count} "
                f"(drift {drift} > tolerance {tolerance})"
            )
        if complete and drift:
            logger.info(
                "[DIGEST] 건수 합 오차 %d (counts=%d headlines=%d, 허용 %d)",
                drift,
                total,
                expected_count,
                tolerance,
            )

        return {
            "sentiment": max(-1.0, min(1.0, float(sentiment))),
            "summary": str(data.get("summary") or "").strip(),
            **normalized_counts,
        }
