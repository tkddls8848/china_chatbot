import json
from dataclasses import dataclass
from pathlib import Path

from llm.backends import LLMBackend


_RAW_EXCERPT_CHARS = 200


class TranslationError(RuntimeError):
    """Raised when translation is required but unavailable."""


def _excerpt(raw: object) -> str:
    """실패한 응답의 앞부분. 줄바꿈을 접어 로그 한 줄에 들어가게 한다."""
    collapsed = " ".join(str(raw).split())
    if len(collapsed) <= _RAW_EXCERPT_CHARS:
        return collapsed
    return collapsed[:_RAW_EXCERPT_CHARS] + "…"


@dataclass(frozen=True)
class TranslationResult:
    title: str
    content: str
    mentioned_stocks: list[str]
    sentiment: float | None = None
    impact: str = ""


class TranslationService:
    def __init__(
        self,
        backend: LLMBackend,
        enabled: bool,
        prompt_dir: Path,
        num_predict: int = 512,
        temperature: float = 0.1,
    ):
        self._backend = backend
        self._enabled = enabled
        self._num_predict = num_predict
        self._temperature = temperature
        self._prompt = (prompt_dir / "global_ko.txt").read_text(encoding="utf-8")

    def translate_article(self, title: str, content: str) -> TranslationResult:
        if not self._enabled:
            return TranslationResult(title, content, [])

        # 호출 자체가 실패하면 남길 응답이 없다. except에서 이름이 비지 않게 둔다.
        raw = ""
        try:
            raw = self._backend.generate(
                system_prompt=self._prompt,
                user_prompt=f"title:\n{title}\n\ncontent:\n{content.strip() or title}",
                max_tokens=self._num_predict,
                temperature=self._temperature,
            )
            return self._parse_translation(raw)
        except Exception as exc:
            # 응답의 어느 부분이 계약을 벗어났는지 로그만 보고 알 수 있어야 한다.
            # 실패한 호출도 Neurons를 이미 썼으므로, 재현을 기다리지 않고 그
            # 자리에서 응답 앞부분을 남긴다. 백엔드 오류(HTTP 등)일 때는 raw가
            # 비어 있어 기존 메시지만 남는다.
            detail = f" | raw={_excerpt(raw)}" if raw else ""
            raise TranslationError(f"{exc}{detail}") from exc

    @staticmethod
    def _parse_translation(raw: str) -> TranslationResult:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("translation JSON must be an object")

        title = data.get("title")
        content = data.get("content")
        mentioned_stocks = data.get("mentioned_stocks")
        sentiment = data.get("sentiment")
        impact = data.get("impact")

        if not isinstance(title, str) or not title.strip():
            raise ValueError("translation JSON missing title")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("translation JSON missing content")
        if not isinstance(mentioned_stocks, list) or any(
            not isinstance(code, str) for code in mentioned_stocks
        ):
            raise ValueError("translation JSON mentioned_stocks must be strings")
        if not isinstance(sentiment, (int, float)) or not -1 <= sentiment <= 1:
            raise ValueError("translation JSON sentiment must be between -1 and 1")
        if impact not in ("high", "medium", "low"):
            raise ValueError("translation JSON impact must be high, medium, or low")

        return TranslationResult(
            title=title.strip(),
            content=content.strip(),
            mentioned_stocks=[code.strip() for code in mentioned_stocks if code.strip()],
            sentiment=float(sentiment),
            impact=impact,
        )
