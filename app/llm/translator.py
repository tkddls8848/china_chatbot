import json
from dataclasses import dataclass
from pathlib import Path

from llm.backends import LLMBackend


class TranslationError(RuntimeError):
    """Raised when translation is required but unavailable."""


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

        try:
            raw = self._backend.generate(
                system_prompt=self._prompt,
                user_prompt=f"title:\n{title}\n\ncontent:\n{content.strip() or title}",
                max_tokens=self._num_predict,
                temperature=self._temperature,
            )
            return self._parse_translation(raw)
        except Exception as exc:
            raise TranslationError(str(exc)) from exc

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
