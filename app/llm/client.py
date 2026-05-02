import json
from typing import Any

import requests


class OllamaJsonClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: int,
        num_gpu: int = 0,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._num_gpu = num_gpu

    def chat_json(
        self,
        system_prompt: str,
        user_payload: str | dict[str, Any],
        temperature: float,
        num_predict: int,
    ) -> str:
        if not isinstance(user_payload, str):
            user_payload = json.dumps(user_payload, ensure_ascii=False)

        response = requests.post(
            f"{self._base_url}/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload},
                ],
                "stream": False,
                "think": False,
                "format": "json",
                "options": {
                    "temperature": temperature,
                    "num_predict": num_predict,
                    "num_gpu": self._num_gpu,
                },
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        message = (response.json().get("message") or {})
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty Ollama response content")
        return content
