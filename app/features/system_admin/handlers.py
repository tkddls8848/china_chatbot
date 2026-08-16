"""시작·도움말·시스템 제어 명령 구현."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from core.config import (
    POLYMARKET_BACKFILL_FILE,
    POLYMARKET_PANEL_ENABLED,
    POLYMARKET_RETENTION_DAYS,
)
from features.market_sentiment.polymarket_history import BACKFILL_CAVEATS
from features.news_prefilter.service import SHADOW_CAVEATS
from handlers.navigation import main_menu, persistent_menu, system_menu
from state import PolymarketConsensusStore

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
        "  /system polymarket — 컨센서스 섀도 파일럿 상태\n"
        "  /system prefilter — 뉴스 사전선별 섀도 비교"
    )


def _format_prefilter_report(report: dict) -> str:
    """두 정책의 불일치와 판별력, CPU 예산을 한 화면에 그린다."""
    mode = report["mode"]
    cpu = report["cpu"]
    used_hours = float(cpu["used_seconds"]) / 3600
    budget_hours = float(cpu["budget_seconds"]) / 3600
    lines = [
        "<b>뉴스 사전선별 (로컬 사건 메모리)</b>",
        f"모드: <b>{mode}</b>"
        + ("  — 점수만 기록하고 번역 순서는 최신순 그대로" if mode == "shadow" else ""),
        "",
        "<b>수집</b>",
        f"  주기 {report['cycles']}회 · 후보 {report['candidates_seen']:,}건"
        f" · 관측 기록 {report['logged']:,}건",
        f"  사건 메모리 {report['events']:,}건"
        + (
            f" · 신규 사건 비율 {report['new_event_ratio']:.0%}"
            if report["new_event_ratio"] is not None
            else ""
        ),
        "",
        "<b>두 정책의 불일치</b>",
        f"  둘 다 선택 {report['agree']}건 · 최신순만 {report['latest_only']}건"
        f" · 사전선별만 {report['prefilter_only']}건",
    ]
    if not report["latest_only"] and not report["prefilter_only"]:
        lines.append("  두 정책이 같은 기사를 고르고 있어 바꿀 이유가 아직 없습니다.")

    lines.extend(["", "<b>판별력</b>"])
    auc = report["auc"]
    if auc is None:
        lines.append(
            f"  라벨 {report['labeled']}건(양성 {report['positives']}건)"
            " — 양쪽 라벨이 모두 모이기 전에는 계산하지 않습니다."
        )
    else:
        lines.append(
            f"  라벨 {report['labeled']}건 중 양성 {report['positives']}건 · "
            f"점수 AUC <b>{auc:.3f}</b> (0.5 = 무작위)"
        )
    if report["model_trained_at"]:
        lines.append(
            f"  모델 학습 {report['model_trained_at']} · "
            f"검증 AP {report['model_validation_ap']} "
            f"(기저 {report['model_prevalence']}) · 라벨 {report['model_label_count']}건"
        )
    else:
        lines.append("  ⏸ 아직 학습된 모델이 없습니다(라벨 120건·5일이 모이면 시작).")

    lines.extend(
        [
            "",
            "<b>CPU 예산</b>",
            f"  {used_hours:.2f}h / {budget_hours:.2f}h 사용"
            f" (UTC {cpu['utc_day']}, 예비 {float(cpu['reserve_ratio']):.0%})",
            "",
            "<b>섀도가 답하지 못하는 것</b>",
        ]
    )
    lines.extend(f"  • {caveat}" for caveat in SHADOW_CAVEATS)
    return "\n".join(lines)


# 리포트 항목별 한국어 라벨과 단위. 게이트 자체는 state 모듈이 계산한다.
_POLYMARKET_CRITERIA_LABELS = {
    "snapshot_days": ("성공 스냅숏", "일"),
    "delta_days": ("유효 일별 변화", "일"),
    "dense_day_ratio": ("공통 이벤트 3개 이상 비율", ""),
    "theme_count": ("독립 theme", "개"),
    "top_theme_contribution": ("최대 theme 기여도", ""),
    "median_spread": ("median spread", ""),
}


def _backfill_store() -> PolymarketConsensusStore | None:
    """백필 결과 파일을 그때그때 읽는다. 없으면 None.

    기동 시점에 붙잡아 두지 않는 이유는 백필이 봇과 무관하게, 봇이 도는 중에
    돌기 때문이다. 파일도 라이브 스냅숏과 따로다 — 섞으면 라이브 판정의 근거가
    오염된다. 보존 기간은 같으므로 오래된 백필은 저절로 얇아져 게이트를
    통과하지 못한다.
    """
    if not POLYMARKET_BACKFILL_FILE.exists():
        return None
    return PolymarketConsensusStore(
        POLYMARKET_BACKFILL_FILE,
        retention_days=POLYMARKET_RETENTION_DAYS,
    )


def _format_polymarket_report(
    uptime: dict | None,
    backfill: dict | None,
    panel_enabled: bool,
) -> str:
    """가동률(라이브)과 승격 게이트(백필)를 한 화면에 나란히 그린다.

    둘은 서로를 대신하지 못한다. 백필은 게이트의 실질을 하루 만에 판정하지만
    job이 매일 도는지는 모르고, 라이브는 그 반대다. 그래서 승격 조건도 둘 다
    통과다.
    """
    lines = [
        "<b>Polymarket 컨센서스 섀도 파일럿</b>",
        f"패널 표시: {'켜짐' if panel_enabled else '꺼짐(수집만)'}",
        "",
        "<b>라이브 수집 — 가동률</b>",
    ]
    if uptime is None:
        lines.append("  ⏸ 수집이 꺼져 있습니다(POLYMARKET_ENABLED).")
    else:
        mark = "✅" if uptime["passed"] else "❌"
        lines.append(
            f"  {mark} 최근 {uptime['window_days']}일 스냅숏: "
            f"{uptime['value']}일 (기준 {uptime['threshold']}일)"
        )
        lines.append(f"  마지막 스냅숏: {uptime['last_date'] or '없음'}")

    lines.extend(["", "<b>백필 판정 — 승격 게이트</b>"])
    if backfill is None:
        lines.append("  ⏸ 백필을 아직 돌리지 않았습니다(app/polymarket_backfill.py).")
    else:
        lines.append(f"  평가 창: 최근 {backfill['window_days']}일")
        for key, item in backfill["criteria"].items():
            label, unit = _POLYMARKET_CRITERIA_LABELS.get(key, (key, ""))
            mark = "✅" if item["passed"] else "❌"
            line = (
                f"  {mark} {label}: {item['value']}{unit} "
                f"(기준 {item['threshold']}{unit})"
            )
            caveat = BACKFILL_CAVEATS.get(key)
            lines.append(f"{line}\n      ※ {caveat}" if caveat else line)

    ready = bool(uptime and uptime["passed"] and backfill and backfill["passed"])
    lines.extend(
        [
            "",
            (
                "두 축을 모두 만족합니다. POLYMARKET_PANEL_ENABLED=true로 승격할 수 있습니다."
                if ready
                else "아직 승격하지 않습니다. 백필이 미달이면 기다리지 말고 수집을 끕니다."
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
        backfill_store = _backfill_store()
        if store is None and backfill_store is None:
            await message.reply_text(
                "Polymarket 수집이 꺼져 있고(POLYMARKET_ENABLED) 백필 결과도 없습니다.",
            )
            return
        await message.reply_text(
            _format_polymarket_report(
                await store.uptime() if store is not None else None,
                await backfill_store.promotion_report()
                if backfill_store is not None
                else None,
                POLYMARKET_PANEL_ENABLED,
            ),
            parse_mode="HTML",
        )
        return

    if command == "prefilter":
        prefilter = context.bot_data.get("news_prefilter")
        if prefilter is None:
            await message.reply_text(
                "뉴스 사전선별이 꺼져 있습니다(FEATURES_ENABLED의 news_prefilter).",
            )
            return
        await message.reply_text(
            _format_prefilter_report(await prefilter.report()),
            parse_mode="HTML",
        )
        return

    if command:
        await message.reply_text(
            "알 수 없는 항목입니다. 사용법: /system [features|polymarket|prefilter]",
            parse_mode="HTML",
        )
        return

    registry = context.bot_data.get("news_registry")
    source_lines = registry.status_lines() if registry is not None else None
    await message.reply_text(
        _format_system_status(source_lines),
        parse_mode="HTML",
        reply_markup=system_menu(),
    )
