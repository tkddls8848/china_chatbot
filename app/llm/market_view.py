import json
import logging
import math
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
            if not isinstance(self._data, dict):
                raise ValueError("market view state must be an object")
            if self._normalize_loaded_data():
                self._persist()
        except Exception as e:
            logger.warning("[MarketView] failed to load state, resetting: %s", e)
            self._data = self._default_data()
            self._persist()

    def _default_data(self) -> dict[str, Any]:
        return {SIGHT_KEY: None, "updated_at": None, "history": []}

    def _persist(self) -> None:
        self._file_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_sight(self) -> str | None:
        sight = self._data.get(SIGHT_KEY)
        return sight if isinstance(sight, str) and sight.strip() else None

    def set_sight(self, text: str) -> None:
        normalized = text.strip()
        if normalized != self.get_sight():
            self._data["history"] = []
        self._data[SIGHT_KEY] = normalized
        self._data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._persist()

    def clear_sight(self) -> None:
        self._data[SIGHT_KEY] = None
        self._data["updated_at"] = None
        self._data["history"] = []
        self._persist()

    def get_last_result(self) -> dict[str, Any] | None:
        history = self.get_history_summaries()
        return history[-1] if history else None

    def save_result(self, result: dict[str, Any]) -> None:
        history = self._data.get("history")
        if not isinstance(history, list):
            history = []
        history.append(self._summarize_result(result))
        self._data["history"] = history[-self._history_limit :]
        self._persist()

    def get_history_summaries(self) -> list[dict[str, Any]]:
        """이전 분석의 압축 요약. 다음 분석 프롬프트에 맥락으로 주입한다."""
        history = self._data.get("history")
        if not isinstance(history, list):
            return []
        return [
            self._summarize_result(result)
            for result in history[-self._history_limit :]
            if isinstance(result, dict)
        ]

    @staticmethod
    def _summarize_result(result: dict[str, Any]) -> dict[str, Any]:
        actions = [
            {
                "ticker": str(item.get("ticker") or "").strip(),
                "action": item.get("action"),
            }
            for item in result.get("actions", [])
            if (
                isinstance(item, dict)
                and item.get("action") in ("add", "remove")
                and str(item.get("ticker") or "").strip()
            )
        ]
        return {
            "generated_at": result.get("generated_at"),
            "summary": str(result.get("summary") or "")[:300],
            "actions": actions,
        }

    def _normalize_loaded_data(self) -> bool:
        changed = False
        defaults = self._default_data()
        for key, value in defaults.items():
            if key not in self._data:
                self._data[key] = value
                changed = True

        raw_history = self._data.get("history")
        if not isinstance(raw_history, list):
            raw_history = []
            changed = True
        had_legacy_last_result = "last_result" in self._data
        legacy_last_result = self._data.pop("last_result", None)
        if isinstance(legacy_last_result, dict) and not raw_history:
            raw_history = [legacy_last_result]
        if had_legacy_last_result:
            changed = True
        compact_history = [
            self._summarize_result(result)
            for result in raw_history[-self._history_limit :]
            if isinstance(result, dict)
        ]
        if compact_history != self._data.get("history"):
            self._data["history"] = compact_history
            changed = True
        return changed


class MarketViewAnalyzer:
    def __init__(
        self,
        base_url: str,
        model: str,
        enabled: bool,
        timeout: int | None,
        num_predict: int,
        min_ctx: int,
        max_ctx: int,
        ctx_safety_ratio: float,
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
        self._min_ctx = max(4096, min_ctx)
        self._max_ctx = max(self._min_ctx, max_ctx)
        self._ctx_safety_ratio = max(1.0, ctx_safety_ratio)
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
        system_prompt = prompt or self._prompt
        payload_text = json.dumps(payload, ensure_ascii=False)
        num_ctx, estimated_input_tokens, required_tokens = self._select_context_size(
            system_prompt,
            payload_text,
        )
        article_count = len(
            payload.get("news_items")
            or payload.get("news_titles")
            or []
        )
        log = logger.warning if required_tokens > self._max_ctx else logger.info
        log(
            "[MarketView] 동적 컨텍스트: 기사=%d, 문자=%d, 입력≈%d토큰, "
            "출력예약=%d, 필요≈%d, num_ctx=%d",
            article_count,
            len(system_prompt) + len(payload_text),
            estimated_input_tokens,
            self._num_predict,
            required_tokens,
            num_ctx,
        )
        response = requests.post(
            f"{self._base_url}/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": payload_text},
                    {"role": "assistant", "content": "{"},
                ],
                "stream": False,
                "think": False,
                "format": "json",
                "options": {
                    "temperature": 0.2,
                    "num_predict": self._num_predict,
                    "num_ctx": num_ctx,
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

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Qwen 계열용 보수적 토큰 근사치.

        한중일 문자는 글자당 약 1.5토큰, 나머지는 약 3문자당
        1토큰으로 계산한다. 실제 토크나이저 오차는 안전 비율로 흡수한다.
        """
        cjk_chars = sum(
            1
            for char in text
            if (
                "\u1100" <= char <= "\u11ff"
                or "\u3040" <= char <= "\u30ff"
                or "\u3130" <= char <= "\u318f"
                or "\u3400" <= char <= "\u9fff"
                or "\uac00" <= char <= "\ud7af"
                or "\uf900" <= char <= "\ufaff"
            )
        )
        other_chars = len(text) - cjk_chars
        return max(1, math.ceil((cjk_chars * 1.5) + (other_chars / 3)))

    def _select_context_size(
        self,
        system_prompt: str,
        payload_text: str,
    ) -> tuple[int, int, int]:
        estimated_input = (
            self._estimate_tokens(system_prompt)
            + self._estimate_tokens(payload_text)
            + 64
        )
        required = math.ceil(
            estimated_input * self._ctx_safety_ratio
            + self._num_predict
            + 256
        )
        bucket = math.ceil(required / 8192) * 8192
        selected = min(self._max_ctx, max(self._min_ctx, bucket))
        return selected, estimated_input, required

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
            "view_critique": self._normalize_view_critique(data.get("view_critique")),
        }

    @staticmethod
    def _normalize_view_critique(raw: Any) -> list[dict[str, Any]]:
        """마켓 뷰 반론 항목을 정규화한다.

        보조 출력이므로 형식 오류는 예외 대신 항목 제외로 처리한다(fail-soft).
        소형 모델이 문자열 배열로 답하는 경우도 수용한다.
        """
        if not isinstance(raw, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in raw:
            if len(normalized) >= 3:
                break
            if isinstance(item, str):
                point = item.strip()
                if point:
                    normalized.append({"point": point, "severity": None, "evidence": None})
                continue
            if not isinstance(item, dict):
                continue
            point = str(item.get("point") or "").strip()
            if not point:
                continue
            severity = item.get("severity")
            try:
                severity = min(1.0, max(0.0, float(severity)))
            except (TypeError, ValueError):
                severity = None
            evidence = item.get("evidence")
            if not isinstance(evidence, dict):
                evidence = None
            normalized.append(
                {"point": point, "severity": severity, "evidence": evidence}
            )
        return normalized

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
            "view_critique": [],
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
