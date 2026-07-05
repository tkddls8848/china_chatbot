import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import requests

logger = logging.getLogger(__name__)


class TranslationError(RuntimeError):
    """Raised when translation is required but unavailable."""


@dataclass(frozen=True)
class TranslationResult:
    title: str
    content: str
    mentioned_stocks: list[str]
    theme_candidates: list[dict[str, Any]]
    sentiment: float | None = None
    impact: str = ""


class TranslationService:
    """Translate Chinese financial news to Korean with Ollama."""

    _PROMPT_FILES = {
        "cls": "cls_ko.txt",
        "futu": "futu_ko.txt",
        "stock": "stock_ko.txt",
        "global": "global_ko.txt",
    }

    def __init__(
        self,
        base_url: str,
        model: str,
        enabled: bool,
        timeout: int,
        prompt_dir: Path,
        num_gpu: int = 0,
        num_predict: int = 512,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._enabled = enabled
        self._timeout = timeout
        self._num_gpu = num_gpu
        self._num_predict = num_predict
        self._prompts = self._load_prompts(prompt_dir)

    def set_num_gpu(self, num_gpu: int) -> None:
        """런타임에 Ollama num_gpu를 변경한다(-1=자동, 0=CPU, N=레이어). 다음 요청부터 반영."""
        self._num_gpu = max(-1, num_gpu)

    def _load_prompts(self, prompt_dir: Path) -> Dict[str, str]:
        prompts: Dict[str, str] = {}
        for source, filename in self._PROMPT_FILES.items():
            path = prompt_dir / filename
            prompts[source] = path.read_text(encoding="utf-8")
        return prompts

    def translate_article(
        self, source: str, title: str, content: str
    ) -> TranslationResult:
        if not self._enabled:
            return TranslationResult(title, content, [], [])

        prompt = self._prompts.get(source)
        if prompt is None:
            raise TranslationError(f"unknown source: {source}")

        try:
            translated = self._request_translation(prompt, title, content)
            return self._parse_translation(translated)
        except Exception as e:
            raise TranslationError(str(e)) from e

    def _request_translation(self, prompt: str, title: str, content: str) -> str:
        system_prompt = (
            f"{prompt}\n\n"
            "JSON output hard rules:\n"
            "- Return exactly one JSON object with title, content, mentioned_stocks, and any source-specific fields requested above.\n"
            "- Do not include unescaped double quotes inside string values.\n"
            "- If the translated text contains a quote, use single quotes instead of double quotes.\n"
            "- Keep title and content as single-line strings.\n"
            "- Do not omit content. If the body is short, translate that short body."
        )
        response = requests.post(
            f"{self._base_url}/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"title:\n{title}\n\ncontent:\n{content}"},
                ],
                "stream": False,
                "think": False,
                "format": "json",
                "options": {
                    "temperature": 0.1,
                    "num_predict": self._num_predict,
                    "num_gpu": self._num_gpu,
                },
            },
            timeout=self._timeout,
        )
        response.raise_for_status()

        data = response.json()
        message = data.get("message") or {}
        translated = message.get("content")
        if not isinstance(translated, str) or not translated.strip():
            logger.error(
                "[TRANSLATE] empty content; thinking_present=%s; response=%s",
                bool(message.get("thinking")),
                json.dumps(data, ensure_ascii=False)[:500],
            )
            raise ValueError("empty Ollama response content")
        return translated

    @staticmethod
    def _parse_sentiment(value: Any) -> float | None:
        """감성 점수(-1~1)를 관대하게 파싱한다. 실패하면 None(미표기)."""
        if value is None:
            return None
        try:
            return min(1.0, max(-1.0, float(value)))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_impact(value: Any) -> str:
        impact = str(value or "").strip().lower()
        return impact if impact in ("high", "medium", "low") else ""

    def _parse_translation(self, translated: str) -> TranslationResult:
        data = json.loads(self._extract_json_object(translated))
        title = data.get("title")
        content = data.get("content")
        mentioned_stocks = data.get("mentioned_stocks")
        theme_candidates = data.get("theme_candidates", [])

        if not isinstance(title, str) or not title.strip():
            raise ValueError("translation JSON missing title")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("translation JSON missing content")
        if not isinstance(mentioned_stocks, list):
            raise ValueError("translation JSON mentioned_stocks must be a list")
        if not isinstance(theme_candidates, list):
            raise ValueError("translation JSON theme_candidates must be a list")
        if any(not isinstance(item, dict) for item in theme_candidates):
            raise ValueError("translation JSON theme_candidates must contain objects")

        return TranslationResult(
            title.strip(),
            content.strip(),
            [str(code).strip() for code in mentioned_stocks if str(code).strip()],
            theme_candidates,
            sentiment=self._parse_sentiment(data.get("sentiment")),
            impact=self._parse_impact(data.get("impact")),
        )

    def _extract_json_object(self, text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return stripped
        return stripped[start : end + 1]
