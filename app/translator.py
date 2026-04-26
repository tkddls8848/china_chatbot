import json
import logging
from pathlib import Path
from typing import Dict

import requests

logger = logging.getLogger(__name__)


class TranslationError(RuntimeError):
    """Raised when translation is required but unavailable."""


class TranslationService:
    """Translate Chinese financial news to Korean with Ollama."""

    _PROMPT_FILES = {
        "cls": "cls_ko.txt",
        "futu": "futu_ko.txt",
        "stock": "stock_ko.txt",
    }

    def __init__(
        self,
        base_url: str,
        model: str,
        enabled: bool,
        timeout: int,
        prompt_dir: Path,
        fallback_to_original: bool = False,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._enabled = enabled
        self._timeout = timeout
        self._fallback_to_original = fallback_to_original
        self._prompts = self._load_prompts(prompt_dir)

    def _load_prompts(self, prompt_dir: Path) -> Dict[str, str]:
        prompts: Dict[str, str] = {}
        for source, filename in self._PROMPT_FILES.items():
            path = prompt_dir / filename
            prompts[source] = path.read_text(encoding="utf-8")
        return prompts

    def translate_article(self, source: str, title: str, content: str) -> tuple[str, str]:
        if not self._enabled:
            return title, content

        prompt = self._prompts.get(source)
        if prompt is None:
            raise TranslationError(f"unknown source: {source}")

        try:
            translated = self._request_translation(prompt, title, content)
            return self._parse_translation(translated)
        except Exception as e:
            if self._fallback_to_original:
                logger.warning("[TRANSLATE] failed, fallback to original: %s", e)
                return title, content
            raise TranslationError(str(e)) from e

    def _request_translation(self, prompt: str, title: str, content: str) -> str:
        response = requests.post(
            f"{self._base_url}/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": f"제목:\n{title}\n\n본문:\n{content}",
                    },
                ],
                "stream": False,
                "think": False,
                "format": "json",
                "options": {
                    "temperature": 0.1,
                    "num_predict": 512,
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

    def _parse_translation(self, translated: str) -> tuple[str, str]:
        data = json.loads(translated)
        title = data.get("title")
        content = data.get("content")

        if not isinstance(title, str) or not title.strip():
            raise ValueError("translation JSON missing title")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("translation JSON missing content")

        return title.strip(), content.strip()
