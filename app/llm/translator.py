import json
import logging
import re
from pathlib import Path
from typing import Dict

import requests
from llm.client import OllamaJsonClient

logger = logging.getLogger(__name__)


class TranslationError(RuntimeError):
    """Raised when translation is required but unavailable."""


class TranslationService:
    """Translate Chinese financial news to Korean with Ollama."""

    _STOCK_NAME_PROMPT = (
        "중국 상장 기업의 중국어 종목명을 한국어 또는 영문으로 변환한다.\n"
        "규칙:\n"
        "- 국제적으로 통용되는 영문 약칭이 있으면 우선 사용한다 (예: CATL, BYD, Alibaba).\n"
        "- 영문 약칭이 없으면 한국어 음역으로 표기한다.\n"
        "- JSON만 출력: {\"name\": \"변환된 이름\"}"
    )

    _PROMPT_FILES = {
        "cls": "cls_ko.txt",
        "futu": "futu_ko.txt",
        "stock": "stock_ko.txt",
        "xinhua": "xinhua_ko.txt",
    }

    def __init__(
        self,
        base_url: str,
        model: str,
        enabled: bool,
        timeout: int,
        prompt_dir: Path,
        fallback_to_original: bool = False,
        num_gpu: int = 0,
        num_predict: int = 512,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._enabled = enabled
        self._timeout = timeout
        self._fallback_to_original = fallback_to_original
        self._num_gpu = num_gpu
        self._num_predict = num_predict
        self._prompts = self._load_prompts(prompt_dir)
        self._client = OllamaJsonClient(
            base_url=base_url,
            model=model,
            timeout=timeout,
            num_gpu=num_gpu,
        )

    def _load_prompts(self, prompt_dir: Path) -> Dict[str, str]:
        prompts: Dict[str, str] = {}
        for source, filename in self._PROMPT_FILES.items():
            path = prompt_dir / filename
            prompts[source] = path.read_text(encoding="utf-8")
        return prompts

    def translate_article(
        self, source: str, title: str, content: str
    ) -> tuple[str, str, list[str]]:
        if not self._enabled:
            return title, content, []

        prompt = self._prompts.get(source)
        if prompt is None:
            raise TranslationError(f"unknown source: {source}")

        try:
            translated = self._request_translation(prompt, title, content)
            try:
                return self._parse_translation(translated)
            except Exception as first_error:
                logger.info(
                    "[TRANSLATE] invalid JSON, retrying once: source=%s title=%s error=%s",
                    source,
                    title[:80],
                    first_error,
                )
                retry_prompt = (
                    f"{prompt}\n\n"
                    "이전 응답은 JSON 파싱에 실패했습니다. "
                    "반드시 유효한 JSON 객체 하나만 출력하세요. "
                    "문자열 안의 줄바꿈은 공백으로 바꾸고, 모든 필드 사이에 쉼표를 넣으세요. "
                    "title/content 문자열 안에 큰따옴표가 필요하면 작은따옴표로 바꾸거나 JSON 규칙에 맞게 이스케이프하세요."
                )
                translated = self._request_translation(retry_prompt, title, content)
                return self._parse_translation(translated)
        except Exception as e:
            if self._fallback_to_original:
                logger.warning("[TRANSLATE] failed, fallback to original: %s", e)
                return title, content, []
            raise TranslationError(str(e)) from e

    def _request_translation(self, prompt: str, title: str, content: str) -> str:
        system_prompt = (
            f"{prompt}\n\n"
            "JSON output hard rules:\n"
            "- Return exactly one JSON object with title, content, related.\n"
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

    def _parse_translation(self, translated: str) -> tuple[str, str, list[str]]:
        payload = self._extract_json_object(translated)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = self._parse_known_translation_shape(payload)
        title = data.get("title")
        content = data.get("content")
        related = data.get("related", [])

        if not isinstance(title, str) or not title.strip():
            raise ValueError("translation JSON missing title")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("translation JSON missing content")
        if not isinstance(related, list):
            related = []

        related_codes = [c for c in related if isinstance(c, str) and c.strip()]
        return title.strip(), content.strip(), related_codes

    def _extract_json_object(self, text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return stripped
        return stripped[start : end + 1]

    def _parse_known_translation_shape(self, text: str) -> dict:
        title = self._extract_field_before(text, "title", "content")
        content = self._extract_field_before(text, "content", "related")
        related = []

        related_match = re.search(r'"related"\s*:\s*(\[[\s\S]*?\])', text)
        if related_match:
            try:
                parsed_related = json.loads(related_match.group(1))
                if isinstance(parsed_related, list):
                    related = parsed_related
            except json.JSONDecodeError:
                related = re.findall(r'"([^"]+)"', related_match.group(1))

        if not title or not content:
            raise ValueError("translation JSON missing title/content")
        return {"title": title, "content": content, "related": related}

    def _extract_field_before(self, text: str, field: str, next_field: str) -> str:
        pattern = (
            rf'"{re.escape(field)}"\s*:\s*"'
            rf'([\s\S]*?)'
            rf'"\s*,\s*"{re.escape(next_field)}"\s*:'
        )
        match = re.search(pattern, text)
        if not match:
            return ""
        return self._clean_jsonish_string(match.group(1))

    def _clean_jsonish_string(self, value: str) -> str:
        value = value.replace("\r", " ").replace("\n", " ")
        try:
            return json.loads(f'"{value}"').strip()
        except json.JSONDecodeError:
            return value.replace('\\"', '"').strip()

    def translate_stock_name(self, cn_name: str) -> str:
        if not self._enabled or not cn_name.strip():
            return cn_name
        try:
            response = requests.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": self._STOCK_NAME_PROMPT},
                        {"role": "user", "content": cn_name},
                    ],
                    "stream": False,
                    "think": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 32,
                        "num_gpu": self._num_gpu,
                    },
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            content = (response.json().get("message") or {}).get("content", "")
            name = json.loads(content).get("name", "").strip()
            return name if name else cn_name
        except Exception as e:
            logger.warning("[TRANSLATE] stock name translation failed for %s: %s", cn_name, e)
            return cn_name
