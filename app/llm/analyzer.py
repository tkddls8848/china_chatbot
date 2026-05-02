import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from llm.client import OllamaJsonClient

logger = logging.getLogger(__name__)


class MarketViewError(RuntimeError):
    """Raised when market view analysis cannot be completed."""


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
        self._client = OllamaJsonClient(
            base_url=base_url,
            model=model,
            timeout=timeout,
            num_gpu=num_gpu,
        )

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
        raw = self._client.chat_json(
            system_prompt=self._prompt,
            user_payload=payload,
            temperature=0.2,
            num_predict=self._num_predict,
        )
        return self._parse_analysis(raw)

    def _parse_analysis(self, raw: str) -> dict[str, Any]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise MarketViewError(f"invalid JSON response: {e}") from e

        summary = data.get("summary")
        actions = data.get("actions", [])
        risks = data.get("risks", [])

        if not isinstance(summary, str):
            summary = ""
        if not isinstance(actions, list):
            actions = []
        if not isinstance(risks, list):
            risks = []

        normalized_actions: list[dict[str, Any]] = []
        for item in actions:
            if not isinstance(item, dict):
                continue
            ticker = item.get("ticker") or item.get("code")
            action = item.get("action")
            if not isinstance(ticker, str) or not isinstance(action, str):
                continue
            if action not in {"add", "keep", "remove", "watch"}:
                continue

            confidence = item.get("confidence", 0)
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = 0.0

            evidence = item.get("evidence", [])
            if not isinstance(evidence, list):
                evidence = []

            normalized_actions.append(
                {
                    "ticker": ticker.strip(),
                    "name": str(item.get("name") or "").strip(),
                    "action": action,
                    "confidence": max(0.0, min(1.0, confidence)),
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
