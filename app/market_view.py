import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)


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
            self._data = {"view": None, "updated_at": None, "last_result": None}
            self._persist()
            return

        try:
            self._data = json.loads(self._file_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("[MarketView] failed to load state, resetting: %s", e)
            self._data = {"view": None, "updated_at": None, "last_result": None}
            self._persist()

    def _persist(self) -> None:
        self._file_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_view(self) -> str | None:
        view = self._data.get("view")
        return view if isinstance(view, str) and view.strip() else None

    def set_view(self, text: str) -> None:
        self._data["view"] = text.strip()
        self._data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._persist()

    def clear_view(self) -> None:
        self._data["view"] = None
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
        try:
            return self._parse_analysis(raw)
        except MarketViewError as first_error:
            logger.info("[ANALYZE] JSON 파싱 실패, 재시도: %s", first_error)
            retry_prompt = (
                f"{self._prompt}\n\n"
                "이전 응답은 JSON 파싱에 실패했습니다. "
                "반드시 유효한 JSON 객체 하나만 출력하세요. "
                "모든 객체 필드와 배열 항목 사이에는 쉼표를 넣으세요. "
                "설명, 마크다운, 코드블록, trailing comma는 출력하지 마세요."
            )
            raw = self._request_analysis(payload, retry_prompt, temperature=0.1)
            return self._parse_analysis(raw)

    def _request_analysis(
        self,
        payload: dict[str, Any],
        prompt: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        response = requests.post(
            f"{self._base_url}/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": prompt or self._prompt},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                    {"role": "assistant", "content": "{"},
                ],
                "stream": False,
                "think": False,
                "format": "json",
                "options": {
                    "temperature": temperature,
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
        # assistant prefill로 "{" 를 주입했으므로 응답 앞에 다시 붙인다
        if not content.lstrip().startswith("{"):
            content = "{" + content
        return content

    def _parse_analysis(self, raw: str) -> dict[str, Any]:
        payload = self._extract_json_object(raw)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            repaired = self._repair_common_json_errors(payload)
            if repaired != payload:
                try:
                    data = json.loads(repaired)
                    logger.warning("[ANALYZE] JSON repaired after parse failure: %s", e)
                except json.JSONDecodeError:
                    logger.error("[ANALYZE] JSON 파싱 실패: %s | raw=%r", e, raw[:300])
                    raise MarketViewError(f"invalid JSON response: {e}") from e
            else:
                logger.error("[ANALYZE] JSON 파싱 실패: %s | raw=%r", e, raw[:300])
                raise MarketViewError(f"invalid JSON response: {e}") from e

        if not isinstance(data, dict):
            raise MarketViewError("analysis JSON must be an object")

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
                    "evidence": [
                        e for e in evidence
                        if isinstance(e, dict)
                    ],
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

    def _repair_common_json_errors(self, payload: str) -> str:
        repaired = payload
        repaired = re.sub(
            r'(?<=[}\]"0-9])(\s*\n\s*)(?="[^"\n]+"\s*:)',
            r",\1",
            repaired,
        )
        repaired = re.sub(r"(?<=})(\s*\n\s*)(?=\{)", r",\1", repaired)
        repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
        return repaired
