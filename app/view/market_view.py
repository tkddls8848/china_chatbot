import asyncio
import html
import uuid
from datetime import datetime, timedelta
from typing import Any

from data.models import NewsItem, StockRef, normalize_stock_code, is_matchable_stock_name
from data.store import WatchlistManager, MarketViewManager
from data.stock_db import StockDatabase
from llm.analyzer import MarketViewAnalyzer
from llm.translator import TranslationService
from news.collector import NewsCollector
from settings import Settings


# ── ViewPendingStore ──────────────────────────────────────────────────────────

class ViewPendingStore:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._items: dict[str, dict[str, Any]] = {}

    def prune(self) -> None:
        expired = [uid for uid, item in self._items.items() if self._is_expired(item)]
        for uid in expired:
            self._items.pop(uid, None)

    def put(self, uid: str, item: dict[str, Any]) -> None:
        self.prune()
        self._items[uid] = item

    def pop(self, uid: str) -> dict[str, Any] | None:
        item = self._items.pop(uid, None)
        if not item or self._is_expired(item):
            return None
        return item

    def clear(self) -> None:
        self._items.clear()

    def _is_expired(self, item: dict[str, Any]) -> bool:
        try:
            created = datetime.fromisoformat(str(item.get("created_at", "")))
        except ValueError:
            return True
        return datetime.now() - created > timedelta(
            minutes=self._settings.view_pending_ttl_minutes
        )


# ── CandidateService ──────────────────────────────────────────────────────────

class CandidateService:
    def __init__(self, settings: Settings, stock_db: StockDatabase):
        self._settings = settings
        self._stock_db = stock_db

    def build_universe(
        self,
        watchlist: dict[str, str],
        news_items: list[NewsItem],
    ) -> list[StockRef]:
        candidates: dict[str, StockRef] = {}
        haystacks = [f"{item.title}\n{item.content}" for item in news_items]

        for code, name in watchlist.items():
            candidates[code] = StockRef(code=code, name=name, in_watchlist=True)

        for entry in self._stock_db.get_candidate_universe():
            code = str(entry.get("code") or "")
            name = str(entry.get("name") or "").strip()
            if not code or not name or not is_matchable_stock_name(name):
                continue

            matched_news: list[dict[str, Any]] = []
            for item, haystack in zip(news_items, haystacks):
                if name in haystack:
                    matched_news.append(
                        {
                            "title": item.title,
                            "source": item.source,
                            "published_at": item.published_at,
                            "url": item.url,
                        }
                    )

            if not matched_news:
                continue

            candidates[code] = StockRef(
                code=code,
                name=name,
                market=str(entry.get("market") or ""),
                in_watchlist=code in watchlist,
                matched_news=matched_news[:3],
            )
            if len(candidates) >= self._settings.view_max_candidates:
                break

        return list(candidates.values())[: self._settings.view_max_candidates]


# ── ViewActionPolicy ──────────────────────────────────────────────────────────

class ViewActionPolicy:
    def __init__(self, settings: Settings, stock_db: StockDatabase):
        self._settings = settings
        self._stock_db = stock_db

    def validate(
        self,
        result: dict[str, Any],
        watchlist: dict[str, str],
        candidate_universe: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        add_items: list[dict[str, Any]] = []
        remove_items: list[dict[str, Any]] = []
        seen_add: set[str] = set()
        seen_remove: set[str] = set()
        allowed_add_codes = {
            str(item.get("code") or "")
            for item in candidate_universe
            if not item.get("in_watchlist")
        }

        for item in result.get("actions", []):
            if not isinstance(item, dict):
                continue
            action = item.get("action")
            if action not in {"add", "remove"}:
                continue

            try:
                confidence = float(item.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0.0

            code = normalize_stock_code(str(item.get("ticker") or ""))
            if not code:
                continue

            evidence = item.get("evidence") or []
            if action == "add":
                if confidence < 0.5:
                    continue
                if code not in allowed_add_codes:
                    continue
                if code in watchlist or code in seen_add:
                    continue
                if len(add_items) >= self._settings.view_max_add:
                    continue
                db_name = self._stock_db.get_cn_name(code)
                if not db_name:
                    continue
                add_items.append(
                    {
                        "code": code,
                        "name": db_name,
                        "reason": str(item.get("reason") or "").strip(),
                        "confidence": confidence,
                    }
                )
                seen_add.add(code)
            else:
                if not evidence or confidence < 0.5:
                    continue
                if code not in watchlist or code in seen_remove:
                    continue
                if len(remove_items) >= self._settings.view_max_remove:
                    continue
                remove_items.append(
                    {
                        "code": code,
                        "name": watchlist[code],
                        "reason": str(item.get("reason") or "").strip(),
                        "confidence": confidence,
                    }
                )
                seen_remove.add(code)

            if len(add_items) + len(remove_items) >= self._settings.view_max_changes:
                break

        return {"add": add_items, "remove": remove_items}


# ── MarketViewFormatter ───────────────────────────────────────────────────────

class MarketViewFormatter:
    def __init__(self, settings: Settings):
        self._settings = settings

    def format_action_lines(self, items: list[dict[str, Any]]) -> str:
        lines = []
        for item in items:
            reason = html.escape(str(item.get("reason") or ""))
            code = html.escape(str(item["code"]))
            name = html.escape(str(item["name"]))
            confidence = float(item.get("confidence") or 0)
            suffix = f" - {reason}" if reason else ""
            lines.append(f"- {name} ({code}) [{confidence:.0%}]{suffix}")
        return "\n".join(lines) if lines else "- 없음"

    def format_result(
        self,
        result: dict[str, Any],
        pending: dict[str, list[dict[str, Any]]],
        news_count: int,
        candidate_count: int,
        temporary: bool = False,
    ) -> str:
        title = "시장 뷰 분석 결과"
        if temporary:
            title += " (임시 뷰)"

        summary = html.escape(result.get("summary") or "요약 없음")
        add_lines = self.format_action_lines(pending["add"])
        remove_lines = self.format_action_lines(pending["remove"])

        watch_lines = []
        keep_lines = []
        for item in result.get("actions", []):
            if not isinstance(item, dict):
                continue
            action = item.get("action")
            if action not in {"watch", "keep"}:
                continue
            code = html.escape(normalize_stock_code(str(item.get("ticker") or "")))
            name = html.escape(str(item.get("name") or code))
            reason = html.escape(str(item.get("reason") or ""))
            line = f"- {name} ({code})"
            if reason:
                line += f" - {reason}"
            if action == "watch":
                watch_lines.append(line)
            else:
                keep_lines.append(line)

        risks = result.get("risks") or []
        risk_lines = "\n".join(f"- {html.escape(str(r))}" for r in risks[:5]) or "- 없음"
        text = (
            f"<b>{html.escape(title)}</b>\n"
            f"분석 뉴스: {news_count}건 / 후보 universe: {candidate_count}개\n\n"
            f"<b>요약</b>\n{summary}\n\n"
            f"<b>추가 후보</b>\n{add_lines}\n\n"
            f"<b>제외 후보</b>\n{remove_lines}\n\n"
            f"<b>주목 종목</b>\n{chr(10).join(watch_lines[:5]) or '- 없음'}\n\n"
            f"<b>유지</b>\n{chr(10).join(keep_lines[:5]) or '- 없음'}\n\n"
            f"<b>리스크</b>\n{risk_lines}"
        )
        if len(text) > self._settings.telegram_message_limit:
            text = text[: self._settings.telegram_message_limit - 3] + "..."
        return text


# ── ViewActionService ─────────────────────────────────────────────────────────

class ViewActionService:
    def __init__(
        self,
        watchlist: WatchlistManager,
        stock_db: StockDatabase,
        translator: TranslationService,
        pending_store: ViewPendingStore,
    ):
        self._watchlist = watchlist
        self._stock_db = stock_db
        self._translator = translator
        self._pending_store = pending_store

    async def apply(self, uid: str) -> str:
        pending = self._pending_store.pop(uid)
        if not pending:
            return "만료된 요청입니다. /view run을 다시 실행하세요."

        watchlist = await self._watchlist.get_all()
        added: list[str] = []
        removed: list[str] = []
        skipped: list[str] = []

        for item in pending.get("remove", []):
            code = str(item.get("code") or "")
            if code in watchlist:
                name = await self._watchlist.remove(code)
                removed.append(f"{name or item.get('name') or code} ({code})")
                watchlist.pop(code, None)
            else:
                skipped.append(f"{item.get('name') or code} ({code})")

        for item in pending.get("add", []):
            code = str(item.get("code") or "")
            if code in watchlist:
                skipped.append(f"{watchlist[code]} ({code})")
                continue
            db_name = self._stock_db.get_cn_name(code)
            if not db_name:
                skipped.append(f"{item.get('name') or code} ({code})")
                continue
            name = await asyncio.to_thread(self._translator.translate_stock_name, db_name)
            await self._watchlist.add(code, name)
            added.append(f"{name} ({code})")
            watchlist[code] = name

        text = (
            "<b>시장 뷰 변경 적용 완료</b>\n\n"
            f"<b>추가</b>\n{chr(10).join('- ' + html.escape(x) for x in added) or '- 없음'}\n\n"
            f"<b>삭제</b>\n{chr(10).join('- ' + html.escape(x) for x in removed) or '- 없음'}"
        )
        if skipped:
            text += f"\n\n<b>건너뜀</b>\n{chr(10).join('- ' + html.escape(x) for x in skipped)}"
        return text

    def cancel(self, uid: str) -> str:
        self._pending_store.pop(uid)
        return "시장 뷰 변경 적용을 취소했습니다."


# ── MarketViewAnalysisService ─────────────────────────────────────────────────

class MarketViewRunResult:
    def __init__(self, text: str, uid: str | None, has_changes: bool):
        self.text = text
        self.uid = uid
        self.has_changes = has_changes


class MarketViewAnalysisService:
    def __init__(
        self,
        watchlist: WatchlistManager,
        market_view_store: MarketViewManager,
        analyzer: MarketViewAnalyzer,
        news_collector: NewsCollector,
        candidate_service: CandidateService,
        action_policy: ViewActionPolicy,
        pending_store: ViewPendingStore,
        formatter: MarketViewFormatter,
    ):
        self._watchlist = watchlist
        self._market_view_store = market_view_store
        self._analyzer = analyzer
        self._news_collector = news_collector
        self._candidate_service = candidate_service
        self._action_policy = action_policy
        self._pending_store = pending_store
        self._formatter = formatter

    async def run(
        self,
        market_view: str,
        temporary: bool = False,
    ) -> MarketViewRunResult:
        self._pending_store.prune()
        watchlist = await self._watchlist.get_all()
        news_items = await self._news_collector.collect_global_market_news()
        if not news_items:
            return MarketViewRunResult(
                "최근 전체 시장 뉴스가 없어 분석을 실행하지 못했습니다.",
                None,
                False,
            )

        candidates = self._candidate_service.build_universe(watchlist, news_items)
        news_payload = [item.to_dict() for item in news_items]
        candidate_payload = [item.to_dict() for item in candidates]
        result = await asyncio.to_thread(
            self._analyzer.analyze,
            market_view,
            watchlist,
            news_payload,
            candidate_payload,
        )
        pending = self._action_policy.validate(result, watchlist, candidate_payload)
        if not temporary:
            await asyncio.to_thread(self._market_view_store.save_result, result)

        text = self._formatter.format_result(
            result,
            pending,
            len(news_items),
            len(candidates),
            temporary,
        )
        has_changes = bool(pending["add"] or pending["remove"])
        if not has_changes:
            return MarketViewRunResult(
                text + "\n\n변경 적용 후보가 없습니다.",
                None,
                False,
            )

        uid = uuid.uuid4().hex[:8]
        self._pending_store.put(
            uid,
            {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "market_view": market_view,
                "add": pending["add"],
                "remove": pending["remove"],
                "summary": result.get("summary") or "",
            },
        )
        return MarketViewRunResult(text, uid, True)
