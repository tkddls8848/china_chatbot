"""3시간 동안 모은 기사 제목을 시장상황 보고서로 추론한다.

기사별 번역과 달리 한 시장의 공통 테마와 상충 신호를 한 호출로 분석한다.
호출 수는 기사 수가 아니라 보고서에 포함된 시장 수에 비례한다.
"""

import json
import logging
from pathlib import Path
from typing import Any

from llm.backends import LLMBackend

logger = logging.getLogger(__name__)


class NewsReportError(RuntimeError):
    """Raised when a market report cannot be produced for a market."""


class NewsReportAnalyzer:
    def __init__(
        self,
        backend: LLMBackend,
        prompt_file: Path,
        num_predict: int,
        max_highlights: int,
    ):
        self._backend = backend
        self._num_predict = num_predict
        self._max_highlights = max(1, max_highlights)
        # 프롬프트에 JSON 예시가 들어 있어 str.format을 쓰면 중괄호가 깨진다.
        self._prompt = prompt_file.read_text(encoding="utf-8").replace(
            "{max_highlights}", str(self._max_highlights)
        )

    def analyze(
        self,
        market: str,
        window: str,
        headlines: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """헤드라인 목록에서 시장상황과 근거 기사를 만든다(블로킹)."""
        if not headlines:
            raise NewsReportError("no headlines to analyze")

        payload = {"market": market, "window": window, "articles": headlines}
        try:
            raw = self._backend.generate(
                system_prompt=self._prompt,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                max_tokens=self._num_predict,
                temperature=0.2,
            )
        except Exception as exc:
            raise NewsReportError(str(exc)) from exc

        if not raw.strip():
            raise NewsReportError("empty news report response content")
        return self._parse(raw, valid_indexes={item["index"] for item in headlines})

    def _parse(self, raw: str, *, valid_indexes: set[int]) -> dict[str, Any]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            # 원문은 남기지 않는다. 길이만으로도 잘림 여부는 판단할 수 있다.
            raise NewsReportError(
                f"news report JSON parse failed ({exc}); raw_chars={len(raw)}"
            ) from exc
        if not isinstance(data, dict):
            raise NewsReportError("news report JSON must be an object")

        analysis = data.get("analysis")
        highlights = data.get("highlights")
        if not isinstance(analysis, str):
            raise NewsReportError("news report analysis must be a string")
        if not isinstance(highlights, list):
            raise NewsReportError("news report highlights must be a list")

        parsed: list[dict[str, Any]] = []
        seen: set[int] = set()
        for row in highlights[: self._max_highlights]:
            parsed.append(self._parse_highlight(row, valid_indexes, seen))
        return {"analysis": analysis.strip(), "highlights": parsed}

    @staticmethod
    def _parse_highlight(
        row: Any,
        valid_indexes: set[int],
        seen: set[int],
    ) -> dict[str, Any]:
        if not isinstance(row, dict):
            raise NewsReportError("news report highlight must be an object")
        index = row.get("index")
        if not isinstance(index, int) or index not in valid_indexes:
            raise NewsReportError(f"news report highlight index is unknown: {index!r}")
        if index in seen:
            raise NewsReportError(f"news report highlight index repeats: {index}")
        seen.add(index)

        title = row.get("title")
        if not isinstance(title, str) or not title.strip():
            raise NewsReportError("news report highlight missing title")
        sentiment = row.get("sentiment")
        if not isinstance(sentiment, (int, float)) or not -1 <= sentiment <= 1:
            raise NewsReportError("news report highlight sentiment must be between -1 and 1")
        impact = row.get("impact")
        if impact not in ("high", "medium", "low"):
            raise NewsReportError("news report highlight impact must be high, medium, or low")
        codes = row.get("mentioned_stocks")
        if not isinstance(codes, list) or any(not isinstance(code, str) for code in codes):
            raise NewsReportError("news report highlight mentioned_stocks must be strings")

        return {
            "index": index,
            "title": title.strip(),
            "sentiment": float(sentiment),
            "impact": impact,
            "mentioned_stocks": [code.strip() for code in codes if code.strip()],
        }
