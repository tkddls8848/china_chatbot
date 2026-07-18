import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

SIGHT_KEY = "sight"


class MarketViewError(RuntimeError):
    """Raised when market view analysis cannot be completed."""


class MarketViewManager:
    def __init__(self, file_path: Path, history_limit: int = 5):
        self._file_path = file_path
        self._history_limit = max(1, history_limit)
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
        return {SIGHT_KEY: None, "updated_at": None, "last_result": None, "history": []}

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
        history = self._data.get("history")
        if not isinstance(history, list):
            history = []
        history.append(result)
        self._data["history"] = history[-self._history_limit :]
        self._persist()

    def get_history_summaries(self) -> list[dict[str, Any]]:
        """이전 분석의 압축 요약. 다음 분석 프롬프트에 맥락으로 주입한다."""
        history = self._data.get("history")
        if not isinstance(history, list):
            return []
        summaries: list[dict[str, Any]] = []
        for result in history:
            if not isinstance(result, dict):
                continue
            actions = [
                {"ticker": item.get("ticker"), "action": item.get("action")}
                for item in result.get("actions", [])
                if isinstance(item, dict) and item.get("action") in ("add", "remove")
            ]
            summaries.append(
                {
                    "generated_at": result.get("generated_at"),
                    "summary": str(result.get("summary") or "")[:300],
                    "actions": actions,
                }
            )
        return summaries


class MarketViewAnalyzer:
    def __init__(
        self,
        base_url: str,
        model: str,
        enabled: bool,
        timeout: int | None,
        num_predict: int,
        num_ctx: int,
        num_thread: int,
        prompt_file: Path,
        num_gpu: int = 0,
        max_new_actions: int = 4,
        remove_relevance_threshold: float = 0.35,
        verification_enabled: bool = False,
        verification_prompt_file: Path | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._enabled = enabled
        self._timeout = timeout
        self._num_predict = num_predict
        self._num_ctx = max(4096, num_ctx)
        self._num_thread = max(1, num_thread)
        self._num_gpu = num_gpu
        self._max_new_actions = max(0, max_new_actions)
        self._remove_relevance_threshold = remove_relevance_threshold
        self._prompt = prompt_file.read_text(encoding="utf-8")
        self._verification_prompt = ""
        if verification_prompt_file is not None and verification_prompt_file.exists():
            self._verification_prompt = verification_prompt_file.read_text(encoding="utf-8")
        self._verification_enabled = verification_enabled and bool(self._verification_prompt)

    def set_num_gpu(self, num_gpu: int) -> None:
        """런타임에 Ollama num_gpu를 변경한다(-1=자동, 0=CPU, N=레이어). 다음 요청부터 반영."""
        self._num_gpu = max(-1, num_gpu)

    def analyze(
        self,
        market_view: str,
        watchlist: dict[str, str],
        news_items: list[dict[str, Any]],
        candidate_universe: list[dict[str, Any]] | None = None,
        quant_context: dict[str, Any] | None = None,
        previous_analyses: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not self._enabled:
            raise MarketViewError("market view analysis is disabled")

        deadline = (
            time.monotonic() + self._timeout
            if self._timeout is not None
            else None
        )
        payload = {
            "market_view": market_view,
            "current_watchlist": watchlist,
            "news_items": news_items,
            "candidate_universe": candidate_universe or [],
            "remove_relevance_threshold": self._remove_relevance_threshold,
            "max_new_actions": self._max_new_actions,
        }
        if quant_context:
            payload["quant_context"] = quant_context
        if previous_analyses:
            payload["previous_analyses"] = previous_analyses
        raw = self._request_analysis(
            payload,
            timeout=self._remaining_timeout(deadline),
        )
        result = self._parse_analysis(raw)
        if self._verification_enabled:
            result = self._verify_actions(
                market_view,
                result,
                news_items,
                quant_context,
                deadline,
            )
        return result

    def _verify_actions(
        self,
        market_view: str,
        result: dict[str, Any],
        news_items: list[dict[str, Any]],
        quant_context: dict[str, Any] | None,
        deadline: float | None,
    ) -> dict[str, Any]:
        """추가/삭제 후보에 bull/bear 근거를 붙이고 기각(drop) 후보를 걸러낸다.

        검증 호출이 실패하면 1차 결과를 그대로 반환한다(fail-open).
        """
        targets = [
            item for item in result.get("actions", [])
            if item.get("action") in ("add", "remove")
        ]
        if not targets:
            return result

        payload: dict[str, Any] = {
            "market_view": market_view,
            "proposals": [
                {
                    "ticker": item.get("ticker"),
                    "name": item.get("name"),
                    "action": item.get("action"),
                    "reason": item.get("reason"),
                }
                for item in targets
            ],
            "news_titles": [
                str(item.get("title") or "")[:120] for item in news_items
            ],
        }
        if quant_context:
            payload["quant_context"] = quant_context

        try:
            raw = self._request_analysis(
                payload,
                prompt=self._verification_prompt,
                timeout=self._remaining_timeout(deadline),
            )
            data = json.loads(self._extract_json_object(raw))
            verdicts = data.get("verdicts")
            if not isinstance(verdicts, list):
                raise MarketViewError("verification JSON verdicts must be a list")
        except Exception as e:
            logger.warning("[VERIFY] 검증 패스 실패, 1차 결과 유지: %s", e)
            return result

        verdict_by_ticker: dict[str, dict[str, Any]] = {}
        for verdict in verdicts:
            if isinstance(verdict, dict) and isinstance(verdict.get("ticker"), str):
                verdict_by_ticker[verdict["ticker"].strip()] = verdict

        kept_actions: list[dict[str, Any]] = []
        dropped: list[dict[str, Any]] = []
        for item in result.get("actions", []):
            if item.get("action") not in ("add", "remove"):
                kept_actions.append(item)
                continue
            verdict = verdict_by_ticker.get(str(item.get("ticker") or "").strip())
            if verdict is None:
                kept_actions.append(item)
                continue
            item["bull_case"] = str(verdict.get("bull_case") or "").strip()
            item["bear_case"] = str(verdict.get("bear_case") or "").strip()
            try:
                item["verification_confidence"] = min(
                    1.0, max(0.0, float(verdict.get("confidence")))
                )
            except (TypeError, ValueError):
                pass
            if str(verdict.get("verdict") or "").strip().lower() == "drop":
                dropped.append(
                    {
                        "ticker": item.get("ticker"),
                        "name": item.get("name"),
                        "action": item.get("action"),
                        "reason": str(verdict.get("bear_case") or verdict.get("reason") or "").strip(),
                    }
                )
                continue
            kept_actions.append(item)

        result["actions"] = kept_actions
        if dropped:
            result["verification_dropped"] = dropped
        result["verified"] = True
        return result

    def _remaining_timeout(self, deadline: float | None) -> float | None:
        if deadline is None:
            return self._timeout
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MarketViewError("research analysis timed out")
        return remaining

    def _request_analysis(
        self,
        payload: dict[str, Any],
        prompt: str | None = None,
        timeout: float | None = None,
    ) -> str:
        response = requests.post(
            f"{self._base_url}/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": prompt or self._prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    {"role": "assistant", "content": "{"},
                ],
                "stream": False,
                "think": False,
                "format": "json",
                "options": {
                    "temperature": 0.2,
                    "num_predict": self._num_predict,
                    "num_ctx": self._num_ctx,
                    "num_thread": self._num_thread,
                    "num_gpu": self._num_gpu,
                },
            },
            timeout=timeout,
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
            return self._fallback_partial_analysis(raw, e)

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
            ticker = item.get("ticker")
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

            relevance = item.get("relevance")
            if relevance is not None:
                try:
                    relevance = min(1.0, max(0.0, float(relevance)))
                except (TypeError, ValueError) as e:
                    raise MarketViewError(
                        "analysis action relevance must be numeric"
                    ) from e

            normalized_actions.append(
                {
                    "ticker": ticker.strip(),
                    "name": str(item.get("name") or "").strip(),
                    "action": action,
                    "confidence": confidence,
                    "relevance": relevance,
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

    def _fallback_partial_analysis(
        self,
        raw: str,
        error: json.JSONDecodeError,
    ) -> dict[str, Any]:
        summary = self._extract_string_field(raw, "summary")
        if not summary:
            raise MarketViewError(f"invalid JSON response: {error}") from error
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "summary": summary.strip(),
            "actions": [],
            "risks": [
                "LLM 응답 JSON이 중간에 잘려 요약만 복구했습니다. "
                "후보 수나 출력 항목 수를 더 줄여야 합니다."
            ],
        }

    @staticmethod
    def _extract_string_field(raw: str, field: str) -> str:
        pattern = rf'"{re.escape(field)}"\s*:\s*"'
        match = re.search(pattern, raw)
        if not match:
            return ""
        chars: list[str] = []
        escaped = False
        for ch in raw[match.end() :]:
            if escaped:
                chars.append(ch)
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                break
            chars.append(ch)
        return "".join(chars)

    def _extract_json_object(self, text: str) -> str:
        stripped = text.strip()
        start = stripped.find("{")
        if start == -1:
            return stripped
        depth = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(stripped[start:], start):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return stripped[start : i + 1]
        return stripped[start:]
