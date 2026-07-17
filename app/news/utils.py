"""뉴스 처리 공용 헬퍼(상태 없음).

시간 포맷, 텔레그램 메시지 빌드, 비동기 번역 래퍼, 타임아웃 판별,
회전 배치 선택 등 뉴스 파이프라인과 리서치 수집이 공유하는 순수 함수.
"""

import asyncio
import html
import re
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from core.config import TELEGRAM_MESSAGE_LIMIT
from llm.translator import TranslationResult, TranslationService


def format_china_time_as_kst(
    published_at: Any,
    published_date: Any | None = None,
) -> str:
    raw_time = str(published_at or "").strip()
    raw_date = str(published_date or "").strip()
    raw = f"{raw_date} {raw_time}".strip() if raw_date else raw_time
    if not raw:
        return "KST"

    try:
        if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", raw):
            fmt = "%H:%M:%S" if raw.count(":") == 2 else "%H:%M"
            converted = datetime.strptime(raw, fmt) + timedelta(hours=1)
            return f"{converted.strftime(fmt)} KST"

        parsed = pd.to_datetime(raw, errors="coerce")
        if pd.isna(parsed):
            return f"{raw} KST"

        converted = parsed.to_pydatetime() + timedelta(hours=1)
        fmt = "%Y-%m-%d %H:%M:%S" if re.search(r":\d{2}:\d{2}", raw) else "%Y-%m-%d %H:%M"
        return f"{converted.strftime(fmt)} KST"
    except Exception:
        return f"{raw} KST"


def build_news_message(
    header: str,
    title: str,
    content: str,
    footer: str = "",
    mentioned_stocks: list[tuple[str, str]] | None = None,
) -> str:
    truncation = "..."
    safe_title = html.escape(title)
    raw_content = content

    if mentioned_stocks:
        items = ", ".join(f"{code}({html.escape(name)})" for code, name in mentioned_stocks)
        mentioned_line = f"\n\n관련종목: {items}"
    else:
        mentioned_line = ""

    while True:
        safe_content = html.escape(raw_content)
        title_part = f"<b>{safe_title}</b>\n\n" if safe_title else ""
        text = f"{header}{title_part}{safe_content}{mentioned_line}{footer}"
        if len(text) <= TELEGRAM_MESSAGE_LIMIT:
            return text

        overflow = len(text) - TELEGRAM_MESSAGE_LIMIT
        keep = max(0, len(raw_content) - overflow - len(truncation) - 20)
        next_content = raw_content[:keep].rstrip() + truncation
        if next_content == raw_content:
            safe_content = ""
            text = f"{header}{title_part}{mentioned_line}{footer}"
            return text[: TELEGRAM_MESSAGE_LIMIT - len(truncation)] + truncation
        raw_content = next_content


async def translate_article(
    translator: TranslationService,
    semaphore: asyncio.Semaphore,
    source: str,
    title: str,
    content: str,
) -> TranslationResult:
    async with semaphore:
        return await asyncio.to_thread(
            translator.translate_article,
            source,
            title,
            content,
        )


def is_timeout_error(error: Exception) -> bool:
    return "timed out" in str(error).lower() or "timeout" in str(error).lower()


def normalize_stock_code(raw: Any) -> str:
    """숫자 코드를 시장 규칙에 맞게 0패딩한다(HK 5자리, A주 6자리)."""
    code = str(raw or "").strip()
    digits = "".join(ch for ch in code if ch.isdigit())
    if not digits:
        return code
    return digits.zfill(5) if len(digits) <= 5 else digits.zfill(6)


_SIGNAL_CODE_RE = re.compile(r"\d{5,6}")
_GLOBAL_TICKER_RE = re.compile(r"[A-Za-z][A-Za-z0-9.-]{0,14}")


def signal_codes(raw_codes: list | None) -> list[str]:
    """신호 로그에 기록할 종목코드만 남긴다(정규화 후 5~6자리 숫자, 중복 제거).

    LLM이 추출한 mentioned_stocks에는 미국 티커(JNJ.N, NVDA 등)처럼
    A주·홍콩 코드 형식이 아닌 값이 섞일 수 있어 기록 전에 걸러낸다.
    """
    codes: list[str] = []
    for raw in raw_codes or []:
        code = normalize_stock_code(raw)
        if _SIGNAL_CODE_RE.fullmatch(code):
            candidate = code
        else:
            raw_text = str(raw or "").strip().upper()
            candidate = raw_text if _GLOBAL_TICKER_RE.fullmatch(raw_text) else ""
        if candidate and candidate not in codes:
            codes.append(candidate)
    return codes


def format_sentiment_line(sentiment: float | None, impact: str = "") -> str:
    """뉴스 메시지에 붙일 감성 한 줄. 감성 값이 없으면 빈 문자열."""
    from core.config import NEWS_SENTIMENT_ENABLED

    if not NEWS_SENTIMENT_ENABLED or sentiment is None:
        return ""
    if sentiment >= 0.15:
        marker = "🟢"
    elif sentiment <= -0.15:
        marker = "🔴"
    else:
        marker = "⚪"
    impact_labels = {"high": "높음", "medium": "중간", "low": "낮음"}
    impact_part = f" · 영향 {impact_labels[impact]}" if impact in impact_labels else ""
    return f"감성: {marker} {sentiment:+.2f}{impact_part}\n"


def select_rotating_batch(
    items: list,
    cursor: int,
    batch_size: int,
) -> tuple[list, int]:
    """커서를 기준으로 batch_size개를 선택하고 다음 커서를 반환한다.

    전체를 매 주기 일괄 처리하지 않고 여러 주기에 나눠 회전 처리하기 위한 공용 헬퍼.
    batch_size가 0 이하이면 전체를 한 번에 처리한다.
    """
    if not items:
        return [], 0
    size = batch_size if batch_size > 0 else len(items)
    if cursor >= len(items):
        cursor = 0
    selected = items[cursor : cursor + size]
    next_cursor = cursor + len(selected)
    if next_cursor >= len(items):
        next_cursor = 0
    return selected, next_cursor
