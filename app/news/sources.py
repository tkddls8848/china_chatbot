"""전역/개별 뉴스 원천 fetcher와 소스별 정규화 어댑터.

각 어댑터는 원천 DataFrame/RSS를 GlobalArticle 목록(최신순)으로 변환한다.
article_id는 기존 전송 이력(sent_ids.json)과의 호환을 위해 CLS/Futu는
레거시 포맷을 유지한다.
"""

import html
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import quote_plus

import akshare as ak
import requests
import requests.exceptions
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


def retry_on_network(func):
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(requests.exceptions.RequestException),
        reraise=True,
    )(func)


@dataclass(frozen=True)
class GlobalArticle:
    """소스와 무관한 전역 속보 1건."""

    article_id: str
    title: str
    content: str
    published_at: str
    published_date: str = ""
    url: str = ""
    extra: dict = field(default_factory=dict)


# ── 원천 fetcher ─────────────────────────────────────

@retry_on_network
def fetch_cls_raw():
    return ak.stock_info_global_cls()


@retry_on_network
def fetch_futu_raw():
    return ak.stock_info_global_futu()


@retry_on_network
def fetch_em_raw():
    return ak.stock_info_global_em()


@retry_on_network
def fetch_sina_raw():
    return ak.stock_info_global_sina()


@retry_on_network
def fetch_ths_raw():
    return ak.stock_info_global_ths()


@retry_on_network
def fetch_stock_news_raw(symbol: str):
    return ak.stock_news_em(symbol=symbol)


@retry_on_network
def fetch_rss_raw(url: str) -> bytes:
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    return response.content


# ── 정규화 어댑터(최신순 반환) ───────────────────────

def _cell(row, key: str) -> str:
    value = row.get(key)
    if value is None:
        return ""
    text = str(value)
    return "" if text.lower() in ("nan", "nat", "none") else text


def fetch_cls_articles() -> list[GlobalArticle]:
    df = fetch_cls_raw()
    articles = []
    for _, row in df.iterrows():
        title = _cell(row, "标题")
        content = _cell(row, "内容")
        date = _cell(row, "发布日期")
        time_ = _cell(row, "发布时间")
        if not (title or content):
            continue
        articles.append(
            GlobalArticle(
                # 레거시 ID 포맷 유지(sent_ids 호환)
                article_id=f"{date} {time_}{title}",
                title=title,
                content=content,
                published_at=time_,
                published_date=date,
            )
        )
    # CLS는 과거→최신 순이므로 뒤집어 최신순으로 맞춘다.
    return articles[::-1]


def fetch_futu_articles() -> list[GlobalArticle]:
    df = fetch_futu_raw()
    articles = []
    for _, row in df.iterrows():
        title = _cell(row, "标题")
        content = _cell(row, "内容")
        published_at = _cell(row, "发布时间")
        if not (title or content):
            continue
        articles.append(
            GlobalArticle(
                # 레거시 ID 포맷 유지(sent_ids 호환)
                article_id=f"{published_at}{content[:20]}",
                title=title,
                content=content,
                published_at=published_at,
                url=_cell(row, "链接"),
            )
        )
    return articles


def fetch_em_articles() -> list[GlobalArticle]:
    df = fetch_em_raw()
    articles = []
    for _, row in df.iterrows():
        title = _cell(row, "标题")
        content = _cell(row, "摘要") or _cell(row, "内容")
        published_at = _cell(row, "发布时间")
        if not (title or content):
            continue
        articles.append(
            GlobalArticle(
                article_id=f"em:{published_at}:{(title or content)[:20]}",
                title=title,
                content=content,
                published_at=published_at,
                url=_cell(row, "链接"),
            )
        )
    return articles


def fetch_sina_articles() -> list[GlobalArticle]:
    df = fetch_sina_raw()
    articles = []
    for _, row in df.iterrows():
        content = _cell(row, "内容")
        published_at = _cell(row, "时间")
        if not content:
            continue
        articles.append(
            GlobalArticle(
                article_id=f"sina:{published_at}:{content[:20]}",
                title="",
                content=content,
                published_at=published_at,
            )
        )
    return articles


def fetch_ths_articles() -> list[GlobalArticle]:
    df = fetch_ths_raw()
    articles = []
    for _, row in df.iterrows():
        title = _cell(row, "标题")
        content = _cell(row, "内容")
        published_at = _cell(row, "发布时间")
        if not (title or content):
            continue
        articles.append(
            GlobalArticle(
                article_id=f"ths:{published_at}:{(title or content)[:20]}",
                title=title,
                content=content,
                published_at=published_at,
                url=_cell(row, "链接"),
            )
        )
    return articles


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", text or "")).strip()


def fetch_rss_articles(url: str, label: str) -> list[GlobalArticle]:
    import feedparser

    feed = feedparser.parse(fetch_rss_raw(url))
    articles = []
    for entry in feed.entries:
        title = _strip_html(str(entry.get("title") or ""))
        content = _strip_html(str(entry.get("summary") or entry.get("description") or ""))
        published_at = str(entry.get("published") or entry.get("updated") or "")
        link = str(entry.get("link") or "")
        if not (title or content):
            continue
        unique = str(entry.get("id") or link or f"{published_at}:{title[:20]}")
        articles.append(
            GlobalArticle(
                article_id=f"rss:{label}:{unique}",
                title=title,
                content=content[:1500],
                published_at=published_at,
                url=link,
            )
        )
    return articles


def fetch_google_news_history(query: str, day: date, market: str) -> list[GlobalArticle]:
    """Fetch articles for one closed calendar day from Google News RSS.

    This is used only to complete a missing chart history.  The query is
    date-bounded so it cannot silently substitute today's headlines for a
    historical point.
    """
    next_day = date.fromordinal(day.toordinal() + 1)
    bounded_query = f"{query} after:{day.isoformat()} before:{next_day.isoformat()}"
    url = "https://news.google.com/rss/search?q=" + quote_plus(bounded_query) + "&hl=en-US&gl=US&ceid=US:en"
    return fetch_rss_articles(url, f"history:{market}:{day.isoformat()}")


_REGIONAL_MARKET_QUERIES = {
    "CN": "China stock market economy",
    "US": "US stock market economy",
    "EU": "European stock market economy",
    "RU": "Russia stock market economy",
    "KR": "Korea stock market economy",
    "JP": "Japan stock market economy",
    "TW": "Taiwan stock market economy",
}

_GDELT_SOURCE_FILTERS = {
    "CN": "china",
    "US": "unitedstates",
    "EU": "(sourcecountry:france OR sourcecountry:germany OR sourcecountry:unitedkingdom)",
    "RU": "russia",
    "KR": "southkorea",
    "JP": "japan",
    "TW": "taiwan",
}


def _interleave(groups: list[list[GlobalArticle]]) -> list[GlobalArticle]:
    result: list[GlobalArticle] = []
    highest = max((len(group) for group in groups), default=0)
    for index in range(highest):
        for group in groups:
            if index < len(group):
                result.append(group[index])
    return result


def _fetch_gdelt_market(market: str) -> list[GlobalArticle]:
    query = _REGIONAL_MARKET_QUERIES[market]
    country_filter = _GDELT_SOURCE_FILTERS[market]
    response = requests.get(
        "https://api.gdeltproject.org/api/v2/doc/doc",
        params={
            "query": f"({query}) {country_filter}",
            "mode": "artlist",
            "format": "json",
            "maxrecords": 8,
        },
        timeout=12,
    )
    response.raise_for_status()
    rows = response.json().get("articles") or []
    articles: list[GlobalArticle] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        if not title:
            continue
        published_at = str(row.get("seendate") or "")
        articles.append(
            GlobalArticle(
                article_id=f"gdelt:{market}:{url or published_at + title[:80]}",
                title=title,
                content=title,
                published_at=published_at,
                url=url,
                extra={"market": market, "provider": "gdelt"},
            )
        )
    return articles


def fetch_gdelt_global_articles() -> list[GlobalArticle]:
    """One keyless GDELT source covering China, US, Europe, Russia and Asia."""
    markets = list(_REGIONAL_MARKET_QUERIES)
    with ThreadPoolExecutor(max_workers=len(markets)) as executor:
        futures = {market: executor.submit(_fetch_gdelt_market, market) for market in markets}
        groups = []
        for market in markets:
            try:
                groups.append(futures[market].result())
            except Exception:
                # A regional endpoint failure must not discard the other regions.
                groups.append([])
    return _interleave(groups)


def _fetch_google_news_market(market: str) -> list[GlobalArticle]:
    query = _REGIONAL_MARKET_QUERIES[market]
    url = "https://news.google.com/rss/search?q=" + quote_plus(query) + "&hl=en-US&gl=US&ceid=US:en"
    articles = fetch_rss_articles(url, f"gnews:{market}")
    return [
        GlobalArticle(
            article_id=f"gnews:{market}:{article.article_id}",
            title=article.title,
            content=article.content,
            published_at=article.published_at,
            published_date=article.published_date,
            url=article.url,
            extra={"market": market, "provider": "google-news"},
        )
        for article in articles
    ]


def fetch_google_news_global_articles() -> list[GlobalArticle]:
    """Public RSS fallback with the same regional coverage as GDELT."""
    markets = list(_REGIONAL_MARKET_QUERIES)
    with ThreadPoolExecutor(max_workers=len(markets)) as executor:
        futures = {market: executor.submit(_fetch_google_news_market, market) for market in markets}
        groups = []
        for market in markets:
            try:
                groups.append(futures[market].result())
            except Exception:
                groups.append([])
    return _interleave(groups)
