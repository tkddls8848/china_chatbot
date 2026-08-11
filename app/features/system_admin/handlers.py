"""시작·도움말·시스템 제어 명령 구현."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from core.config import POLYMARKET_PANEL_ENABLED
from handlers.navigation import main_menu, persistent_menu

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    registry = context.bot_data["feature_registry"]
    await update.message.reply_text(
        registry.help_text(),
        parse_mode="HTML",
        reply_markup=persistent_menu(registry),
    )
    await update.message.reply_text(
        "원하는 기능을 선택하세요.",
        reply_markup=main_menu(registry),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


def _format_system_status(source_lines: list[str] | None = None) -> str:
    sources_part = ""
    if source_lines:
        sources_part = "\n\n<b>전역 뉴스 소스</b>\n" + "\n".join(
            f"  {line}" for line in source_lines
        )
    return (
        "<b>시스템 상태</b>\n\n"
        "추론: <b>Cloudflare Workers AI</b> (원격)"
        f"{sources_part}\n\n"
        "제어:\n"
        "  /system features — 기능 카탈로그\n"
        "  /system polymarket — 컨센서스 섀도 파일럿 상태"
    )


# 리포트 항목별 한국어 라벨과 단위. 게이트 자체는 state 모듈이 계산한다.
_POLYMARKET_CRITERIA_LABELS = {
    "snapshot_days": ("성공 스냅숏", "일"),
    "delta_days": ("유효 일별 변화", "일"),
    "dense_day_ratio": ("공통 이벤트 3개 이상 비율", ""),
    "theme_count": ("독립 theme", "개"),
    "top_theme_contribution": ("최대 theme 기여도", ""),
    "median_spread": ("median spread", ""),
}


def _format_polymarket_report(report: dict, panel_enabled: bool) -> str:
    lines = [
        "<b>Polymarket 컨센서스 섀도 파일럿</b>",
        f"평가 창: 최근 {report['window_days']}일",
        f"패널 표시: {'켜짐' if panel_enabled else '꺼짐(수집만)'}",
        "",
        "<b>승격 게이트</b>",
    ]
    for key, item in report["criteria"].items():
        label, unit = _POLYMARKET_CRITERIA_LABELS.get(key, (key, ""))
        mark = "✅" if item["passed"] else "❌"
        lines.append(
            f"  {mark} {label}: {item['value']}{unit} (기준 {item['threshold']}{unit})"
        )
    lines.extend(
        [
            "",
            (
                "모든 항목을 만족합니다. POLYMARKET_PANEL_ENABLED=true로 승격할 수 있습니다."
                if report["passed"]
                else "미달 항목이 있어 승격하지 않습니다. 실패로 끝나면 수집을 끕니다."
            ),
        ]
    )
    return "\n".join(lines)


async def cmd_system(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    args = context.args or []
    command = args[0].lower() if args else ""
    feature_registry = context.bot_data.get("feature_registry")

    if command == "features":
        lines = (
            feature_registry.catalog_lines()
            if feature_registry is not None
            else ["기능 레지스트리가 준비되지 않았습니다."]
        )
        await message.reply_text(
            "<b>기능 카탈로그</b>\n" + "\n".join(f"  {line}" for line in lines),
            parse_mode="HTML",
        )
        return

    if command == "polymarket":
        store = context.bot_data.get("polymarket_store")
        if store is None:
            await message.reply_text(
                "Polymarket 컨센서스 수집이 꺼져 있습니다(POLYMARKET_ENABLED).",
            )
            return
        report = await store.promotion_report()
        await message.reply_text(
            _format_polymarket_report(report, POLYMARKET_PANEL_ENABLED),
            parse_mode="HTML",
        )
        return

    if command:
        await message.reply_text(
            "알 수 없는 항목입니다. 사용법: /system [features|polymarket]",
            parse_mode="HTML",
        )
        return

    registry = context.bot_data.get("news_registry")
    source_lines = registry.status_lines() if registry is not None else None
    await message.reply_text(
        _format_system_status(source_lines), parse_mode="HTML"
    )
