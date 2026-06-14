import html
from typing import Any

TELEGRAM_MESSAGE_LIMIT = 4096


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:+.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _rank(value: Any) -> str:
    try:
        return f"상위 {100 - float(value):.0f}%"
    except (TypeError, ValueError):
        return "n/a"


def _num(value: Any) -> str:
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "n/a"


def truncate_message(text: str) -> str:
    if len(text) <= TELEGRAM_MESSAGE_LIMIT:
        return text
    return text[: TELEGRAM_MESSAGE_LIMIT - 3] + "..."


def format_help() -> str:
    return (
        "<b>모멘텀 명령어</b>\n\n"
        "/momentum top - 최근 저장된 업종 모멘텀 상위 목록\n"
        "/momentum sector 업종명 - 특정 업종 상세\n"
        "/momentum refresh - 가격 갱신 및 수동 분석 실행\n"
        "/momentum refresh force - 쿨다운 무시 후 강제 갱신\n"
        "/momentum run - refresh와 동일\n\n"
        "v1은 장마감 기준 가격, 거래대금, 시장폭 신호만 사용합니다."
    )


def _sector_candidates(result: dict[str, Any], sector_id: str, limit: int = 3) -> list[dict[str, Any]]:
    candidates = [
        item for item in result.get("candidates", [])
        if str(item.get("sector_id") or "") == str(sector_id)
    ]
    if candidates:
        return candidates[:limit]
    return [
        item for item in result.get("stocks", [])
        if str(item.get("sector_id") or "") == str(sector_id)
    ][:limit]


def format_top(result: dict[str, Any], limit: int) -> str:
    sectors = result.get("sectors") or []
    generated_at = html.escape(str(result.get("generated_at") or ""))
    trade_date = html.escape(str(result.get("trade_date") or ""))
    if not sectors:
        errors = result.get("errors") or []
        error_text = "\n".join(f"- {html.escape(str(e))}" for e in errors[:5]) or "- 저장된 결과 없음"
        return f"<b>업종 모멘텀 결과 없음</b>\n생성시각: {generated_at}\n\n{error_text}"

    lines = [
        f"<b>중국 업종 모멘텀 Top {min(limit, len(sectors))}</b>",
        f"기준일: {trade_date or 'n/a'}",
        f"생성시각: {generated_at}",
        "",
    ]
    if result.get("errors"):
        lines.append("<b>데이터 상태</b>")
        lines.extend(f"- {html.escape(str(error))}" for error in result.get("errors", [])[:3])
        lines.append("")

    active_alerts = [a for a in result.get("alerts", []) if not a.get("suppressed")]
    suppressed_alerts = [a for a in result.get("alerts", []) if a.get("suppressed")]
    if active_alerts or suppressed_alerts:
        lines.append(f"신규 알림 {len(active_alerts)}개 / 중복 억제 {len(suppressed_alerts)}개")
        lines.append("")

    backtest = result.get("backtest") if isinstance(result.get("backtest"), dict) else {}
    summary = backtest.get("summary") if isinstance(backtest.get("summary"), dict) else {}
    if summary:
        lines.extend(
            [
                "<b>백테스트 요약</b>",
                f"신호 {backtest.get('signals', 0)}개 / 10일 평균 초과수익 {_pct(summary.get('avg_forward_excess_10d'))} / 20일 {_pct(summary.get('avg_forward_excess_20d'))}",
                "",
            ]
        )

    for idx, item in enumerate(sectors[:limit], 1):
        sector_id = str(item.get("sector_id") or "")
        candidates = _sector_candidates(result, sector_id, 3)
        stock_line = ", ".join(
            f"{html.escape(str(stock.get('name') or stock.get('code')))}({_pct(stock.get('return_20d') or stock.get('ret_20d'))})"
            for stock in candidates
        ) or "후보 없음"
        lines.extend(
            [
                f"{idx}. <b>{html.escape(str(item.get('sector_name') or sector_id))}</b> [{html.escape(str(item.get('alert_level') or item.get('grade') or ''))}]",
                f"   점수 {_num(item.get('total_score'))} / RS {_rank(item.get('rs_rank'))} / 20일 {_pct(item.get('eq_ret_20d'))}",
                f"   거래대금 {_num(item.get('turnover_ratio_5d_20d'))}배 / 20일선 위 {_pct(item.get('breadth_above_ma20'))} / 초과수익 {_pct(item.get('breadth_outperform_market_20d'))}",
                f"   후보: {stock_line}",
            ]
        )
    return truncate_message("\n".join(lines))


def format_sector(result: dict[str, Any], query: str, stock_limit: int = 8) -> str:
    query_lower = query.lower().strip()
    sectors = result.get("sectors") or []
    matched = None
    for item in sectors:
        if query_lower in str(item.get("sector_name") or "").lower() or query_lower in str(item.get("sector_id") or "").lower():
            matched = item
            break
    if matched is None:
        return f"업종을 찾지 못했습니다: {html.escape(query)}\n/momentum top 으로 업종명을 확인하세요."

    sector_id = str(matched.get("sector_id") or "")
    candidates = _sector_candidates(result, sector_id, stock_limit)
    stock_lines = []
    for stock in candidates:
        flags = []
        if stock.get("breakout_60d"):
            flags.append("60일 신고가")
        elif stock.get("breakout_20d"):
            flags.append("20일 신고가")
        if stock.get("overheat_flag"):
            flags.append("과열")
        suffix = f" / {', '.join(flags)}" if flags else ""
        stock_lines.append(
            f"- {html.escape(str(stock.get('name') or stock.get('code')))} ({html.escape(str(stock.get('code') or stock.get('symbol')))}): "
            f"20일 {_pct(stock.get('return_20d') or stock.get('ret_20d'))}, "
            f"거래대금 {_num(stock.get('amount_ratio_5d_to_20d') or stock.get('turnover_ratio_5d_20d'))}배{suffix}"
        )

    text = (
        f"<b>{html.escape(str(matched.get('sector_name') or sector_id))}</b>\n"
        f"등급: {html.escape(str(matched.get('alert_level') or matched.get('grade') or ''))}\n"
        f"총점: {_num(matched.get('total_score'))}\n"
        f"구성종목: {matched.get('tradable_member_count')}개 거래 가능 / {html.escape(str(matched.get('coverage') or ''))}\n\n"
        f"<b>수익률</b>\n"
        f"- 5일: {_pct(matched.get('eq_ret_5d'))}\n"
        f"- 20일: {_pct(matched.get('eq_ret_20d'))}\n"
        f"- 60일: {_pct(matched.get('eq_ret_60d'))}\n"
        f"- 업종 제외 RS 20일: {_pct(matched.get('ex_sector_rs_20d'))} ({_rank(matched.get('rs_rank'))})\n\n"
        f"<b>수급/시장폭</b>\n"
        f"- 거래대금: {_num(matched.get('turnover_ratio_5d_20d'))}배\n"
        f"- 20일선 위: {_pct(matched.get('breadth_above_ma20'))}\n"
        f"- 60일선 위: {_pct(matched.get('breadth_above_ma60'))}\n"
        f"- 시장 초과수익 종목: {_pct(matched.get('breadth_outperform_market_20d'))}\n"
        f"- 20일 신고가 종목 수: {matched.get('new_high_20d_count')}\n\n"
        f"<b>후보 종목</b>\n"
        f"{chr(10).join(stock_lines) if stock_lines else '- 없음'}"
    )
    return truncate_message(text)
