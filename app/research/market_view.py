import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

SIGHT_KEY = "sight"


class MarketViewError(RuntimeError):
    """Raised when market view analysis cannot be completed."""


class MarketViewManager:
    def __init__(self, file_path: Path):
        self._file_path = file_path
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self._file_path.exists():
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            self._data = self._default_data()
            self._persist()
            return

        try:
            self._data = json.loads(self._file_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("[MarketView] failed to load state, resetting: %s", e)
            self._data = self._default_data()
            self._persist()

    def _default_data(self) -> dict[str, Any]:
        return {SIGHT_KEY: None, "updated_at": None, "last_result": None}

    def _persist(self) -> None:
        self._file_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_sight(self) -> str | None:
        sight = self._data.get(SIGHT_KEY)
        return sight if isinstance(sight, str) and sight.strip() else None

    def set_sight(self, text: str) -> None:
        self._data[SIGHT_KEY] = text.strip()
        self._data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._persist()

    def clear_sight(self) -> None:
        self._data[SIGHT_KEY] = None
        self._data["updated_at"] = None
        self._data["last_result"] = None
        self._persist()

    def get_last_result(self) -> dict[str, Any] | None:
        result = self._data.get("last_result")
        return result if isinstance(result, dict) else None

    def save_result(self, result: dict[str, Any]) -> None:
        self._data["last_result"] = result
        self._persist()


class MarketViewAnalyzer:
    def __init__(
        self,
        base_url: str,
        model: str,
        enabled: bool,
        timeout: int,
        num_predict: int,
        prompt_file: Path,
        num_gpu: int = 0,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._enabled = enabled
        self._timeout = timeout
        self._num_predict = num_predict
        self._num_gpu = num_gpu
        self._prompt = prompt_file.read_text(encoding="utf-8")

    def analyze(
        self,
        market_view: str,
        watchlist: dict[str, str],
        news_items: list[dict[str, Any]],
        candidate_universe: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not self._enabled:
            raise MarketViewError("market view analysis is disabled")

        payload = {
            "market_view": market_view,
            "current_watchlist": watchlist,
            "news_items": news_items,
            "candidate_universe": candidate_universe or [],
        }
        raw = self._request_analysis(payload)
        return self._parse_analysis(raw)

    def _request_analysis(self, payload: dict[str, Any]) -> str:
        response = requests.post(
            f"{self._base_url}/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": self._prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    {"role": "assistant", "content": "{"},
                ],
                "stream": False,
                "think": False,
                "format": "json",
                "options": {
                    "temperature": 0.2,
                    "num_predict": self._num_predict,
                    "num_gpu": self._num_gpu,
                },
            },
            timeout=self._timeout,
        )
        response.raise_for_status()

        data = response.json()
        message = data.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise MarketViewError("empty Ollama response content")
        if not content.lstrip().startswith("{"):
            content = "{" + content
        return content

    def _parse_analysis(self, raw: str) -> dict[str, Any]:
        payload = self._extract_json_object(raw)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            logger.error("[ANALYZE] JSON parse failed: %s | raw=%r", e, raw[:300])
            raise MarketViewError(f"invalid JSON response: {e}") from e

        if not isinstance(data, dict):
            raise MarketViewError("analysis JSON must be an object")

        summary = data.get("summary")
        actions = data.get("actions", [])
        risks = data.get("risks", [])

        if not isinstance(summary, str):
            raise MarketViewError("analysis JSON summary must be a string")
        if not isinstance(actions, list):
            raise MarketViewError("analysis JSON actions must be a list")
        if not isinstance(risks, list):
            raise MarketViewError("analysis JSON risks must be a list")

        normalized_actions: list[dict[str, Any]] = []
        for item in actions:
            if not isinstance(item, dict):
                raise MarketViewError("analysis JSON actions must contain objects")
            ticker = item.get("ticker") or item.get("code")
            action = item.get("action")
            if not isinstance(ticker, str) or not isinstance(action, str):
                raise MarketViewError("analysis action requires ticker and action")

            confidence = item.get("confidence", 0)
            try:
                confidence = float(confidence)
            except (TypeError, ValueError) as e:
                raise MarketViewError("analysis action confidence must be numeric") from e

            evidence = item.get("evidence", [])
            if not isinstance(evidence, list):
                raise MarketViewError("analysis action evidence must be a list")

            normalized_actions.append(
                {
                    "ticker": ticker.strip(),
                    "name": str(item.get("name") or "").strip(),
                    "action": action,
                    "confidence": confidence,
                    "reason": str(item.get("reason") or "").strip(),
                    "evidence": [e for e in evidence if isinstance(e, dict)],
                }
            )

        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "summary": summary.strip(),
            "actions": normalized_actions,
            "risks": [str(r).strip() for r in risks if str(r).strip()],
        }

    def _extract_json_object(self, text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return stripped
        return stripped[start : end + 1]
