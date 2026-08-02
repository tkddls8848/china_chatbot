import json
import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from llm.backends import LLMBackend

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
    """Translate financial news to Korean through a pluggable LLM backend.

    프롬프트 구성·재작성·JSON 검증만 담당하고, 공급자별 HTTP 호출은
    `llm.backends`의 백엔드가 맡는다.
    """

    _PROMPT_FILES = {
        "cls": "cls_ko.txt",
        "futu": "futu_ko.txt",
        "global": "global_ko.txt",
    }

    def __init__(
        self,
        backend: LLMBackend,
        enabled: bool,
        prompt_dir: Path,
        num_predict: int = 512,
        brief_content_limit: int = 180,
        temperature: float = 0.1,
    ):
        self._backend = backend
        self._enabled = enabled
        self._num_predict = num_predict
        self._temperature = temperature
        self._brief_content_limit = max(1, brief_content_limit)
        self._prompts = self._load_prompts(prompt_dir)

    def _load_prompts(self, prompt_dir: Path) -> dict[str, str]:
        prompts: dict[str, str] = {}
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
            content_limit = self._brief_content_limit
            tolerated_limit = content_limit + max(10, round(content_limit * 0.1))
            result: TranslationResult | None = None
            result_has_untranslated_title = False
            retry_for_length = False
            retry_for_translation = False
            for attempt in range(2):
                try:
                    translated = self._request_translation(
                        prompt,
                        title,
                        content,
                        content_limit=content_limit,
                        retry_for_length=retry_for_length,
                        retry_for_translation=retry_for_translation,
                    )
                    rewritten = self._parse_translation(
                        translated, title_fallback=attempt == 0
                    )
                except Exception as rewrite_error:
                    content_title_result = (
                        self._use_korean_content_as_title(result)
                        if attempt > 0 and result is not None
                        else None
                    )
                    if content_title_result is not None:
                        logger.warning(
                            "[TRANSLATE] %s title rewrite failed; "
                            "using the Korean brief as title: %s",
                            source,
                            content_title_result.title[:80],
                        )
                        return content_title_result
                    if (
                        attempt > 0
                        and result is not None
                        and not result_has_untranslated_title
                    ):
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
                retry_for_length = len(result.content) > tolerated_limit
                retry_for_translation = self._looks_untranslated_chinese(
                    result.title
                )
                result_has_untranslated_title = retry_for_translation
                if not retry_for_length and not retry_for_translation:
                    return result
                if attempt == 0:
                    if retry_for_length:
                        logger.warning(
                            "[TRANSLATE] %s brief too long (%d>%d tolerated); "
                            "requesting rewrite",
                            source,
                            len(result.content),
                            tolerated_limit,
                        )
                    if retry_for_translation:
                        logger.warning(
                            "[TRANSLATE] %s title remains Chinese; "
                            "requesting Korean rewrite: %s",
                            source,
                            result.title[:80],
                        )

            assert result is not None
            if result_has_untranslated_title:
                content_title_result = self._use_korean_content_as_title(result)
                if content_title_result is None:
                    raise ValueError(
                        "title remains untranslated Chinese after rewrite"
                    )
                logger.warning(
                    "[TRANSLATE] %s title remains Chinese after rewrite; "
                    "using the Korean brief as title: %s",
                    source,
                    content_title_result.title[:80],
                )
                return content_title_result
            # 문장 중간을 기계적으로 자르지 않는다. 재작성 결과가 여전히 길면
            # 완결된 문장을 보존하고 경고를 남긴다.
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
        retry_for_translation: bool = False,
    ) -> str:
        brief_rules = ""
        if content_limit is not None:
            retry_rule = (
                "- Your previous brief was too long. Rewrite it more compactly.\n"
                if retry_for_length
                else ""
            )
            translation_retry_rule = (
                "- Your previous title remained in Chinese. Rewrite the entire "
                "title in natural Korean; preserve only proper nouns and tickers "
                "when necessary.\n"
                if retry_for_translation
                else ""
            )
            # 상한만 주므로 모델은 상한보다 훨씬 짧게 쓴다(실측: 상한 500자에서
            # 77~105자). 분량을 실제로 늘리려면 목표 구간("about X to Y")과 무엇을
            # 담을지를 함께 지시해야 한다 — 출력 토큰이 늘어 비용도 함께 오르므로
            # 의도적으로 상한만 두고 있다.
            brief_rules = (
                f"\n- content must be a complete Korean news brief of at most "
                f"{content_limit} characters including spaces.\n"
                "- Summarize the meaning; never copy and cut the first characters.\n"
                "- End content as a complete phrase or sentence without an ellipsis.\n"
                f"{retry_rule}{translation_retry_rule}"
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
        return self._backend.generate(
            system_prompt=system_prompt,
            user_prompt=f"title:\n{title}\n\ncontent:\n{content}",
            max_tokens=self._num_predict,
            temperature=self._temperature,
        )

    @staticmethod
    def _looks_untranslated_chinese(text: str) -> bool:
        """한글 없이 중국 한자로만 남은 제목을 미번역 결과로 판정한다."""
        cjk_count = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))
        has_hangul = bool(re.search(r"[가-힣]", text))
        return cjk_count >= 4 and not has_hangul

    @classmethod
    def _use_korean_content_as_title(
        cls,
        result: TranslationResult,
    ) -> TranslationResult | None:
        content = re.sub(r"\s+", " ", result.content).strip()
        if (
            len(re.findall(r"[가-힣]", content)) < 2
            or cls._looks_untranslated_chinese(content)
        ):
            return None
        first_sentence = re.split(r"(?<=[.!?])\s+", content, maxsplit=1)[0]
        title = first_sentence.rstrip(".!? ").strip()
        if not title:
            return None
        return replace(result, title=title)

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
