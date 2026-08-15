import json
import logging
import math
from core.clock import now
from pathlib import Path
from typing import Any

from llm.backends import LLMBackend, LLMBackendError

logger = logging.getLogger(__name__)

SIGHT_KEY = "sight"
_ALLOWED_ACTIONS = frozenset({"add", "remove", "watch"})
_NEW_ACTIONS = frozenset({"add", "watch"})
# 마켓 뷰 반론 항목 상한. 프롬프트의 "최대 5개"와 같은 수를 유지한다.
_MAX_VIEW_CRITIQUE_ITEMS = 5


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
        except Exception as e:
            logger.warning("[MarketView] failed to load state, resetting: %s", e)
            self._data = self._default_data()
            self._persist()

    def _default_data(self) -> dict[str, Any]:
        return {SIGHT_KEY: None, "updated_at": None, "history": [], "last_result": None}

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
            # 주제가 바뀌면 이전 분석은 맥락이 다르다. 프롬프트에 넣지 않는 것과
            # 같은 이유로 `/research show`에도 남기지 않는다.
            self._data["history"] = []
            self._data["last_result"] = None
        self._data[SIGHT_KEY] = normalized
        self._data["updated_at"] = now().isoformat(timespec="seconds")
        self._persist()

    def clear_sight(self) -> None:
        self._data[SIGHT_KEY] = None
        self._data["updated_at"] = None
        self._data["history"] = []
        self._data["last_result"] = None
        self._persist()

    def get_last_result(self) -> dict[str, Any] | None:
        """마지막 분석의 **전체** 결과. `/research show`가 그대로 다시 그린다."""
        last = self._data.get("last_result")
        return last if isinstance(last, dict) else None

    def save_result(
        self,
        result: dict[str, Any],
        *,
        news_count: int = 0,
        candidate_count: int = 0,
    ) -> None:
        """압축본은 history에, 전체는 last_result에 따로 적는다.

        둘을 합치지 않는 이유는 쓰임이 달라서다. history는 다음 분석 프롬프트에
        맥락으로 들어가므로 짧아야 하고(입력 토큰이 부풀면 응답이 잘린다),
        `/research show`는 근거·리스크·반론까지 다시 보여 줘야 한다. 하나로
        묶으면 프롬프트가 비대해지거나 show가 얇아진다.

        전체는 **마지막 한 건만** 남긴다. 이력을 통째로 쌓을 이유가 없다.
        """
        history = self._data.get("history")
        if not isinstance(history, list):
            history = []
        history.append(self._summarize_result(result))
        self._data["history"] = history[-self._history_limit :]
        # 입력 규모는 결과에 없으므로 저장 시점에 함께 적는다. show가 헤더에
        # "분석 뉴스 N건 / 후보 M개"를 실행 때와 똑같이 그리기 위해서다.
        self._data["last_result"] = {
            **result,
            "news_count": news_count,
            "candidate_count": candidate_count,
        }
        self._persist()

    def get_history_summaries(self) -> list[dict[str, Any]]:
        """이전 분석의 압축 요약. 다음 분석 프롬프트에 맥락으로 주입한다."""
        history = self._data.get("history")
        if not isinstance(history, list):
            return []
        return history[-self._history_limit :]

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

class MarketViewAnalyzer:
    def __init__(
        self,
        backend: LLMBackend,
        timeout: int | None,
        num_predict: int,
        prompt_file: Path,
        max_new_actions: int = 4,
        remove_relevance_threshold: float = 0.35,
    ):
        self._backend = backend
        self._timeout = timeout
        self._num_predict = num_predict
        self._max_new_actions = max(0, max_new_actions)
        # 신규 제안 외에 편출(remove)이 들어갈 자리를 남긴다. 변경 없는 기존
        # 종목은 actions에 담기지 않으므로 이만큼이면 충분하다. 상한을 올릴
        # 때는 RESEARCH_ANALYSIS_NUM_PREDICT도 함께 올린다 — JSON 한 덩어리가
        # 출력 예약을 넘기면 문자열 중간에서 잘려 파싱이 실패한다.
        self._max_actions = max(4, self._max_new_actions + 4)
        self._remove_relevance_threshold = remove_relevance_threshold
        self._prompt = prompt_file.read_text(encoding="utf-8")

    def analyze(
        self,
        market_view: str,
        watchlist: dict[str, str],
        news_items: list[dict[str, Any]],
        candidate_universe: list[dict[str, Any]] | None = None,
        quant_context: dict[str, Any] | None = None,
        previous_analyses: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        candidates = candidate_universe or []
        payload = {
            "market_view": market_view,
            "current_watchlist": watchlist,
            "news_items": news_items,
            "candidate_universe": candidates,
            "remove_relevance_threshold": self._remove_relevance_threshold,
            "max_new_actions": self._max_new_actions,
            "max_actions": self._max_actions,
        }
        if quant_context:
            payload["quant_context"] = quant_context
        if previous_analyses:
            payload["previous_analyses"] = previous_analyses
        raw = self._request_analysis(payload)
        return self._parse_analysis(
            raw,
            watchlist=watchlist,
            candidate_universe=candidates,
        )

    def _request_analysis(
        self,
        payload: dict[str, Any],
    ) -> str:
        system_prompt = self._prompt
        payload_text = json.dumps(payload, ensure_ascii=False)
        article_count = len(
            payload.get("news_items")
            or payload.get("news_titles")
            or []
        )
        # 컨텍스트는 모델이 고정으로 갖고 있으므로 크기를 고르지 않는다. 대신
        # 입력이 얼마나 커졌는지는 남겨 둔다 — 후보·기사 수를 늘렸을 때 비용과
        # 잘림을 추적하는 유일한 단서다.
        logger.info(
            "[MarketView] 분석 입력: 기사=%d, 문자=%d, 입력≈%d토큰, 출력예약=%d",
            article_count,
            len(system_prompt) + len(payload_text),
            self._estimate_tokens(system_prompt) + self._estimate_tokens(payload_text),
            self._num_predict,
        )
        try:
            content = self._backend.generate(
                system_prompt=system_prompt,
                user_prompt=payload_text,
                max_tokens=self._num_predict,
                temperature=0.2,
                timeout=self._timeout,
            )
        except LLMBackendError as error:
            raise MarketViewError(str(error)) from error

        if not content.strip():
            raise MarketViewError("empty analysis response content")
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

    def _parse_analysis(
        self,
        raw: str,
        *,
        watchlist: dict[str, str] | None = None,
        candidate_universe: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise MarketViewError(f"invalid analysis JSON: {e}") from e

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

        candidate_codes = (
            [
                str(item.get("code") or "").strip()
                for item in candidate_universe
                if isinstance(item, dict) and str(item.get("code") or "").strip()
            ]
            if candidate_universe is not None
            else None
        )
        normalized_actions = self._normalize_actions(
            actions,
            watchlist_codes=list(watchlist) if watchlist is not None else None,
            candidate_codes=candidate_codes,
            max_new_actions=self._max_new_actions,
        )
        normalized_actions = normalized_actions[: self._max_actions]

        return {
            "generated_at": now().isoformat(timespec="seconds"),
            "summary": summary.strip(),
            "actions": normalized_actions,
            "risks": [str(r).strip() for r in risks if str(r).strip()],
            "view_critique": self._normalize_view_critique(data.get("view_critique")),
        }

    @staticmethod
    def _normalize_score(value: Any, field: str) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError) as e:
            raise MarketViewError(f"analysis action {field} must be numeric") from e
        if not math.isfinite(score):
            raise MarketViewError(f"analysis action {field} must be finite")
        return min(1.0, max(0.0, score))

    @staticmethod
    def _canonical_code_index(codes: list[str]) -> dict[str, str]:
        return {
            code.upper(): code
            for raw_code in codes
            if (code := str(raw_code or "").strip())
        }

    @classmethod
    def _normalize_actions(
        cls,
        actions: list[Any],
        *,
        watchlist_codes: list[str] | None = None,
        candidate_codes: list[str] | None = None,
        max_new_actions: int = 4,
    ) -> list[dict[str, Any]]:
        """Validate and normalize LLM actions against the supplied universes.

        Candidate scoping applies only to add/watch. Remove is resolved
        independently against the current watchlist so a removal cannot be lost
        merely because the candidate universe was truncated.
        """
        watchlist_index = (
            cls._canonical_code_index(watchlist_codes)
            if watchlist_codes is not None
            else None
        )
        candidate_index = (
            cls._canonical_code_index(candidate_codes)
            if candidate_codes is not None
            else None
        )
        watchlist_tokens = {
            str(code).strip().upper()
            for code in (watchlist_codes or [])
            if str(code).strip()
        }
        new_action_limit = max(0, int(max_new_actions))
        new_action_count = 0
        normalized: list[dict[str, Any]] = []
        seen_tickers: set[str] = set()

        for item in actions:
            if not isinstance(item, dict):
                raise MarketViewError("analysis JSON actions must contain objects")
            ticker = item.get("ticker")
            action = item.get("action")
            if not isinstance(ticker, str) or not isinstance(action, str):
                raise MarketViewError("analysis action requires ticker and action")

            action = action.strip().lower()
            if action not in _ALLOWED_ACTIONS:
                continue
            ticker = ticker.strip()
            token = ticker.upper()
            if not token:
                continue

            if action in _NEW_ACTIONS:
                if candidate_index is not None:
                    canonical = candidate_index.get(token)
                    if canonical is None:
                        continue
                    ticker = canonical
                if ticker.upper() in watchlist_tokens:
                    continue
                if new_action_count >= new_action_limit:
                    continue
            elif watchlist_index is not None:
                canonical = watchlist_index.get(token)
                if canonical is None:
                    continue
                ticker = canonical
            canonical_token = ticker.upper()
            if canonical_token in seen_tickers:
                continue

            confidence = cls._normalize_score(item.get("confidence", 0), "confidence")

            evidence = item.get("evidence", [])
            if not isinstance(evidence, list):
                raise MarketViewError("analysis action evidence must be a list")

            relevance = cls._normalize_score(item.get("relevance"), "relevance")

            normalized.append(
                {
                    "ticker": ticker,
                    "name": str(item.get("name") or "").strip(),
                    "action": action,
                    "confidence": confidence,
                    "relevance": relevance,
                    "reason": str(item.get("reason") or "").strip(),
                    "evidence": [e for e in evidence if isinstance(e, dict)],
                }
            )
            if action in _NEW_ACTIONS:
                new_action_count += 1
            seen_tickers.add(canonical_token)
        return normalized
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
            if len(normalized) >= _MAX_VIEW_CRITIQUE_ITEMS:
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
