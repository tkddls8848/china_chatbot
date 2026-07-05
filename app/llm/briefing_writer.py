"""브리핑 코멘트 작성기(Ollama).

정량 스냅샷·뉴스 헤드라인·시장뷰를 받아 짧은 한국어 코멘트를 생성한다.
실패하면 호출부가 데이터 전용 브리핑으로 대체하도록 예외를 던진다.
"""

import json
import logging
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)


class BriefingError(RuntimeError):
    """Raised when briefing comment generation fails."""


class BriefingWriter:
    def __init__(
        self,
        base_url: str,
        model: str,
        enabled: bool,
        timeout: int,
        prompt_file: Path,
        num_gpu: int = 0,
        num_predict: int = 512,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._enabled = enabled
        self._timeout = timeout
        self._num_gpu = num_gpu
        self._num_predict = num_predict
        self._prompt = prompt_file.read_text(encoding="utf-8")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_num_gpu(self, num_gpu: int) -> None:
        """런타임에 Ollama num_gpu를 변경한다(-1=자동, 0=CPU, N=레이어)."""
        self._num_gpu = max(-1, num_gpu)

    def write(self, payload: dict[str, Any]) -> str:
        """payload를 근거로 3~5문장 코멘트를 생성한다(블로킹)."""
        if not self._enabled:
            raise BriefingError("briefing LLM is disabled")
        try:
            response = requests.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": self._prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    "stream": False,
                    "think": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": self._num_predict,
                        "num_gpu": self._num_gpu,
                    },
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
            content = (data.get("message") or {}).get("content")
            if not isinstance(content, str) or not content.strip():
                raise BriefingError("empty Ollama response content")
            return content.strip()
        except BriefingError:
            raise
        except Exception as e:
            raise BriefingError(str(e)) from e
