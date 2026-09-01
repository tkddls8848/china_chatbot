"""예측시장 한 분야의 집계와 상위 베팅을 줄글 한 단락으로 정리한다.

호출 수는 베팅 수가 아니라 **분야 수**에 비례한다. 베팅 하나하나를 부르지
않으므로, 대상이 1,000건을 넘어도 주기당 호출은 분야 수 그대로다.

모델에게 방향을 묻지 않는다. 확률과 집계는 코드가 계산해 넘기고 모델은 그것을
서술만 한다. 방향을 모델이 지어내면 그 문장은 검증할 수 없다.
"""

import json
import logging
from pathlib import Path
from typing import Any

from llm.backends import LLMBackend

logger = logging.getLogger(__name__)

# 프롬프트가 350~450자를 지시한다. 그보다 크게 벗어난 응답은 지시를 무시한
# 것이므로 표시하지 않는다. 상한은 넉넉히 두되 무한정 받지는 않는다.
MAX_PARAGRAPH_CHARS = 1200
MIN_PARAGRAPH_CHARS = 60


class PolymarketBriefError(RuntimeError):
    """분야 하나의 줄글을 만들지 못했을 때."""


class PolymarketBriefAnalyzer:
    def __init__(self, backend: LLMBackend, prompt_file: Path, num_predict: int):
        self._backend = backend
        self._num_predict = num_predict
        self._prompt = prompt_file.read_text(encoding="utf-8")

    def analyze(
        self,
        group_label: str,
        totals: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> str:
        """분야 하나의 단락을 만든다(블로킹). 실패는 예외로 올린다."""
        if not events:
            raise PolymarketBriefError("no events to analyze")

        payload = {"group": group_label, "totals": totals, "events": events}
        try:
            raw = self._backend.generate(
                system_prompt=self._prompt,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                max_tokens=self._num_predict,
                temperature=0.2,
            )
        except Exception as exc:
            raise PolymarketBriefError(str(exc)) from exc

        return self._parse(raw, events)

    def _parse(self, raw: str, events: list[dict[str, Any]]) -> str:
        if not raw.strip():
            raise PolymarketBriefError("empty brief response content")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            # 원문은 남기지 않는다. 길이만으로도 잘림 여부는 판단할 수 있다.
            raise PolymarketBriefError(
                f"brief JSON parse failed ({exc}); raw_chars={len(raw)}"
            ) from exc
        if not isinstance(data, dict):
            raise PolymarketBriefError("brief JSON must be an object")

        paragraph = data.get("paragraph")
        if not isinstance(paragraph, str):
            raise PolymarketBriefError("brief paragraph must be a string")
        paragraph = " ".join(paragraph.split())

        if len(paragraph) < MIN_PARAGRAPH_CHARS:
            raise PolymarketBriefError(f"brief paragraph too short: {len(paragraph)}")
        if len(paragraph) > MAX_PARAGRAPH_CHARS:
            raise PolymarketBriefError(f"brief paragraph too long: {len(paragraph)}")
        # 제목을 그대로 되돌려준 응답은 요약이 아니라 반향이다. 상위 베팅의
        # 제목이 통째로 들어 있으면 나열한 것으로 본다.
        for event in events[:5]:
            title = str(event.get("title") or "").strip()
            if len(title) >= 20 and title in paragraph:
                raise PolymarketBriefError("brief paragraph echoes an event title")
        return paragraph
