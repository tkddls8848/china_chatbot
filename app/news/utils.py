"""뉴스 처리 공용 헬퍼(상태 없음).

시간 포맷, 텔레그램 메시지 빌드, 비동기 번역 래퍼, 타임아웃 판별,
회전 배치 선택 등 뉴스 파이프라인과 리서치 수집이 공유하는 순수 함수.
"""

import asyncio
import html
import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, TypeVar

import pandas as pd

from core.clock import KST as _KST
from llm.translator import TranslationResult, TranslationService

T = TypeVar("T")
# 기사 시각의 소스 타임존. 중국 뉴스·시세 제공처는 현지 시각(CST)을 준다.
# 여기서 KST로 변환하며, 앱의 "지금"은 core/clock.py가 따로 담당한다.
_CHINA_TZ = timezone(timedelta(hours=8))


def parse_news_datetime(
    published_at: Any,
    published_date: Any | None = None,
) -> datetime | None:
    """Parse a source publication timestamp and normalize it to KST.

    RFC/RSS timestamps keep their declared timezone. Timestamps without a
    timezone are treated as China Standard Time because the stock and Chinese
    news providers return local China time.
    """
    raw_time = str(published_at or "").strip()
    raw_date = str(published_date or "").strip()
    raw = f"{raw_date} {raw_time}".strip() if raw_date else raw_time
    if not raw or (not raw_date and re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", raw)):
        return None

    if isinstance(published_at, datetime) and not raw_date:
        parsed_datetime = published_at
    else:
        try:
            parsed_datetime = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            parsed = pd.to_datetime(raw, errors="coerce")
            if pd.isna(parsed):
                return None
            parsed_datetime = parsed.to_pydatetime()

    if parsed_datetime.tzinfo is None:
        parsed_datetime = parsed_datetime.replace(tzinfo=_CHINA_TZ)
    return parsed_datetime.astimezone(_KST)


def publication_time_naive(
    published_at: Any,
    published_date: Any | None = None,
) -> datetime | None:
    """Return a KST publication timestamp in the log's naive ISO format."""
    parsed = parse_news_datetime(published_at, published_date)
    return parsed.replace(tzinfo=None) if parsed is not None else None


def recent_publication_time(
    published_at: Any,
    published_date: Any | None = None,
    max_age_hours: int = 48,
    now: datetime | None = None,
) -> datetime | None:
    """Return the KST publication time only when it is inside the live window."""
    published = parse_news_datetime(published_at, published_date)
    if published is None:
        return None
    current = now or datetime.now(_KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_KST)
    else:
        current = current.astimezone(_KST)
    cutoff = current - timedelta(hours=max(1, max_age_hours))
    if cutoff <= published <= current + timedelta(hours=1):
        return published
    return None


def filter_recent_articles(
    articles: list[T],
    max_age_hours: int,
    now: datetime | None = None,
) -> list[T]:
    """Keep articles inside one shared live-news window, newest first."""
    dated: list[tuple[datetime, T]] = []
    for article in articles:
        published = recent_publication_time(
            getattr(article, "published_at", None),
            getattr(article, "published_date", None),
            max_age_hours,
            now,
        )
        if published is not None:
            dated.append((published, article))
    dated.sort(key=lambda item: item[0], reverse=True)
    return [article for _, article in dated]


def filter_articles_for_kst_day(
    articles: list[T],
    target_day: date,
) -> list[T]:
    """Keep only articles whose actual publication date is the requested KST day."""
    dated: list[tuple[datetime, T]] = []
    for article in articles:
        published = parse_news_datetime(
            getattr(article, "published_at", None),
            getattr(article, "published_date", None),
        )
        if published is not None and published.date() == target_day:
            dated.append((published, article))
    dated.sort(key=lambda item: item[0], reverse=True)
    return [article for _, article in dated]


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
            # 날짜 없이 시각만 온 경우다. 붙일 날짜가 없으니 tzinfo를 달아도
            # 의미가 없고, CST→KST는 고정 +1시간(양쪽 다 서머타임이 없다)이라
            # 시간 산술이 정확하다. 그래서 naive strptime을 의도적으로 쓴다.
            fmt = "%H:%M:%S" if raw.count(":") == 2 else "%H:%M"
            converted = datetime.strptime(raw, fmt) + timedelta(hours=1)  # noqa: DTZ007
            return f"{converted.strftime(fmt)} KST"

        converted = parse_news_datetime(published_at, published_date)
        if converted is None:
            return f"{raw} KST"
        fmt = (
            "%Y-%m-%d %H:%M:%S" if re.search(r":\d{2}:\d{2}", raw) else "%Y-%m-%d %H:%M"
        )
        return f"{converted.strftime(fmt)} KST"
    except Exception:
        return f"{raw} KST"


def compact_kst_time(formatted_time: str) -> str:
    """날짜가 포함된 KST 문자열에서 기사 표시용 시간만 남긴다."""
    match = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?\s+KST)$", formatted_time)
    return match.group(1) if match else formatted_time


def format_digest_article(
    title: str,
    content: str,
    published_time: str,
    sentiment_line: str = "",
    alert: str = "",
    url: str = "",
) -> str:
    """요청한 기사 3줄 형식으로 텔레그램 HTML을 만든다."""
    safe_title = html.escape(truncate_text(title, 120))
    if url:
        safe_title = f'<a href="{html.escape(url)}">{safe_title}</a>'

    text = (
        f"• {alert}{safe_title} ({html.escape(published_time)})\n"
        f"- {html.escape(content)}"
    )
    if sentiment_line:
        text += f"\n{sentiment_line}"
    return text


def truncate_text(text: str, max_chars: int) -> str:
    """텍스트를 문자 수 상한 안에 두고, 잘린 경우 말줄임표를 붙인다."""
    normalized = str(text or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    if max_chars <= 3:
        return normalized[:max_chars]
    return normalized[: max_chars - 3].rstrip() + "..."


def chunk_message_items(
    items: list[T],
    text_getter: Callable[[T], str],
    max_body_length: int,
    separator: str,
) -> list[list[T]]:
    """기사 내부를 자르지 않고 지정된 본문 길이 이하의 묶음으로 나눈다."""
    chunks: list[list[T]] = []
    current: list[T] = []
    current_length = 0

    for item in items:
        item_length = len(text_getter(item))
        added_length = item_length + (len(separator) if current else 0)
        if current and current_length + added_length > max_body_length:
            chunks.append(current)
            current = [item]
            current_length = item_length
        else:
            current.append(item)
            current_length += added_length

    if current:
        chunks.append(current)
    return chunks


async def translate_article(
    translator: TranslationService,
    semaphore: asyncio.Semaphore,
    title: str,
    content: str,
) -> TranslationResult:
    async with semaphore:
        return await asyncio.to_thread(
            translator.translate_article,
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
