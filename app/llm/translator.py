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

    _BRIEF_SOURCES = {"cls", "futu", "global", "stock"}
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
        brief_content_limit: int = 150,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._enabled = enabled
        self._timeout = timeout
        self._num_gpu = num_gpu
        self._num_predict = num_predict
        self._brief_content_limit = max(1, brief_content_limit)
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

        # gnews 등 RSS 소스는 본문이 비어 있는 기사가 흔하다. 빈 본문을
        # 그대로 보내면 모델이 content를 비워 응답하므로 제목으로 대체한다.
        content = (content or "").strip() or title

        try:
            content_limit = (
                self._brief_content_limit
                if source in self._BRIEF_SOURCES
                else None
            )
            tolerated_limit = (
                content_limit + max(10, round(content_limit * 0.1))
                if content_limit is not None
                else None
            )
            result: TranslationResult | None = None
            for attempt in range(2):
                try:
                    translated = self._request_translation(
                        prompt,
                        title,
                        content,
                        content_limit=content_limit,
                        retry_for_length=attempt > 0,
                    )
                    rewritten = self._parse_translation(
                        translated, title_fallback=attempt == 0
                    )
                except Exception as rewrite_error:
                    if attempt > 0 and result is not None:
                        logger.warning(
                            "[TRANSLATE] %s brief rewrite failed; "
                            "using the first valid result (%d chars): %s",
                            source,
                            len(result.content),
                            rewrite_error,
                        )
                        return result
                    raise

                result = rewritten
                if (
                    tolerated_limit is None
                    or len(result.content) <= tolerated_limit
                ):
                    return result
                if attempt == 0:
                    logger.warning(
                        "[TRANSLATE] %s brief too long (%d>%d tolerated); "
                        "requesting rewrite",
                        source,
                        len(result.content),
                        tolerated_limit,
                    )

            # 문장 중간을 기계적으로 자르지 않는다. 재작성 결과가 여전히 길면
            # 완결된 문장을 보존하고 경고를 남긴다.
            assert result is not None
            logger.warning(
                "[TRANSLATE] %s brief remains over limit after rewrite: %d chars",
                source,
                len(result.content),
            )
            return result
        except Exception as e:
            raise TranslationError(str(e)) from e

    def _request_translation(
        self,
        prompt: str,
        title: str,
        content: str,
        content_limit: int | None = None,
        retry_for_length: bool = False,
    ) -> str:
        brief_rules = ""
        if content_limit is not None:
            retry_rule = (
                "- Your previous brief was too long. Rewrite it more compactly.\n"
                if retry_for_length
                else ""
            )
            brief_rules = (
                f"\n- content must be a complete Korean news brief of at most "
                f"{content_limit} characters including spaces.\n"
                "- Summarize the meaning; never copy and cut the first characters.\n"
                "- End content as a complete phrase or sentence without an ellipsis.\n"
                f"{retry_rule}"
            )
        system_prompt = (
            f"{prompt}\n\n"
            "JSON output hard rules:\n"
            "- Return exactly one JSON object with title, content, mentioned_stocks, and any source-specific fields requested above.\n"
            "- Do not include unescaped double quotes inside string values.\n"
            "- If the translated text contains a quote, use single quotes instead of double quotes.\n"
            "- Keep title and content as single-line strings.\n"
            "- Do not omit content. If the body is short, translate that short body."
            f"{brief_rules}"
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

    def _parse_translation(
        self, translated: str, *, title_fallback: bool = False
    ) -> TranslationResult:
        data = json.loads(self._extract_json_object(translated))
        title = data.get("title")
        content = data.get("content")
        mentioned_stocks = data.get("mentioned_stocks")
        theme_candidates = data.get("theme_candidates", [])

        if not isinstance(title, str) or not title.strip():
            raise ValueError("translation JSON missing title")
        if not isinstance(content, str) or not content.strip():
            # 본문 없는 기사(gnews 등)에서 모델이 content를 비워 보내는 경우
            # 기사를 버리는 대신 제목을 단신으로 쓴다. 재작성 시도에서는
            # 첫 번째 유효 결과를 보존해야 하므로 실패로 처리한다.
            if not title_fallback:
                raise ValueError("translation JSON missing content")
            logger.warning(
                "[TRANSLATE] translation JSON missing content; using title as brief"
            )
            content = title
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
