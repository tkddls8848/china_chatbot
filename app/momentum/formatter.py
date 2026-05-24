import html
from typing import Any

TELEGRAM_MESSAGE_LIMIT = 4096


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:+.1f}%"
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
        "제외: /momentum config, /momentum alerts"
    )


def format_top(result: dict[str, Any], limit: int) -> str:
    sectors = result.get("sectors") or []
    stocks = result.get("stocks") or []
    generated_at = html.escape(str(result.get("generated_at") or ""))
    if not sectors:
        errors = result.get("errors") or []
        error_text = "\n".join(f"- {html.escape(str(e))}" for e in errors[:5]) or "- 저장된 결과 없음"
        return f"<b>업종 모멘텀 결과 없음</b>\n생성시각: {generated_at}\n\n{error_text}"

    lines = [f"<b>중국 업종 모멘텀 Top {min(limit, len(sectors))}</b>", f"생성시각: {generated_at}", ""]
    if result.get("errors"):
        lines.append("<b>데이터 상태</b>")
        lines.extend(f"- {html.escape(str(error))}" for error in result.get("errors", [])[:3])
        lines.append("")

    for idx, item in enumerate(sectors[:limit], 1):
        sector_id = item.get("sector_id")
        sector_stocks = [
            stock for stock in stocks
            if stock.get("sector_id") == sector_id
        ][:3]
        stock_line = ", ".join(
            f"{html.escape(str(stock.get('name') or stock.get('code')))} "
            f"({_pct(stock.get('return_20d'))})"
            for stock in sector_stocks
        ) or "종목 데이터 없음"
        grade = str(item.get("grade") or "")
        if grade == "No Data":
            lines.append(
                f"{idx}. <b>{html.escape(str(item.get('sector_name') or item.get('sector_id')))}</b> "
                f"[가격데이터 없음] 정책점수 {_num(item.get('policy_score'))}"
            )
        else:
            lines.append(
                "\n".join(
                    [
                        f"{idx}. <b>{html.escape(str(item.get('sector_name') or item.get('sector_id')))}</b> "
                        f"[{html.escape(grade)}]",
                        f"   점수 {_num(item.get('total_score'))} / RS {_pct(item.get('ex_sector_relative_strength_20d'))} / "
                        f"20일 {_pct(item.get('sector_return_20d'))}",
                        f"   시장폭 20일선 위 {_pct(item.get('above_ma20_ratio'))} / "
                        f"초과수익 {_pct(item.get('outperform_market_ratio'))} / "
                        f"거래대금 {_num(item.get('amount_ratio_5d_to_20d'))}배",
                        f"   종목: {stock_line}",
                    ]
                )
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

    sector_id = matched.get("sector_id")
    stocks = [
        stock for stock in result.get("stocks", [])
        if stock.get("sector_id") == sector_id
    ][:stock_limit]
    stock_lines = []
    for stock in stocks:
        stock_lines.append(
            f"- {html.escape(str(stock.get('name') or stock.get('code')))} ({html.escape(str(stock.get('code')))}): "
            f"20일 {_pct(stock.get('return_20d'))}, 거래대금 {_num(stock.get('amount_ratio_5d_to_20d'))}배"
        )

    text = (
        f"<b>{html.escape(str(matched.get('sector_name') or sector_id))}</b>\n"
        f"등급: {html.escape(str(matched.get('grade') or ''))}\n"
        f"총점: {_num(matched.get('total_score'))}\n"
        f"구성종목: {matched.get('stock_count')}개 / {html.escape(str(matched.get('coverage') or ''))}\n\n"
        f"<b>수익률</b>\n"
        f"- 5일: {_pct(matched.get('sector_return_5d'))}\n"
        f"- 20일: {_pct(matched.get('sector_return_20d'))}\n"
        f"- 60일: {_pct(matched.get('sector_return_60d'))}\n"
        f"- 업종 제외 RS 20일: {_pct(matched.get('ex_sector_relative_strength_20d'))}\n\n"
        f"<b>시장폭</b>\n"
        f"- 20일선 위: {_pct(matched.get('above_ma20_ratio'))}\n"
        f"- 60일선 위: {_pct(matched.get('above_ma60_ratio'))}\n"
        f"- 시장 초과수익 종목: {_pct(matched.get('outperform_market_ratio'))}\n\n"
        f"<b>강한 종목</b>\n"
        f"{chr(10).join(stock_lines) if stock_lines else '- 없음'}"
    )
    return truncate_message(text)
