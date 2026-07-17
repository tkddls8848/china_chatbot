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
from urllib.parse import quote_plus, urlparse

import akshare as ak
import requests
import requests.exceptions
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.config import NEWS_SOURCE_ARTICLE_LIMIT


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


def fetch_rss_raw(url: str) -> bytes:
    host = urlparse(url).netloc.lower()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ChinaChatbotRSS/1.0)",
        "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
    }
    if host.endswith("mk.co.kr"):
        headers["Referer"] = "https://www.mk.co.kr/rss/"
    response = requests.get(url, headers=headers, timeout=(3, 5))
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
    return articles[::-1][:NEWS_SOURCE_ARTICLE_LIMIT]


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
    return articles[:NEWS_SOURCE_ARTICLE_LIMIT]


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
    return articles[:NEWS_SOURCE_ARTICLE_LIMIT]


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
    return articles[:NEWS_SOURCE_ARTICLE_LIMIT]


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
    return articles[:NEWS_SOURCE_ARTICLE_LIMIT]


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", text or "")).strip()


def fetch_rss_articles(
    url: str,
    label: str,
    max_articles: int | None = NEWS_SOURCE_ARTICLE_LIMIT,
) -> list[GlobalArticle]:
    import feedparser

    feed = feedparser.parse(fetch_rss_raw(url))
    articles = []
    for entry in feed.entries[:max_articles]:
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
    return fetch_rss_articles(url, f"history:{market}:{day.isoformat()}", max_articles=None)


_REGIONAL_MARKET_QUERIES = {
    "CN": "China stock market economy",
    "US": "US stock market economy",
    "EU": "European stock market economy",
    "RU": "Russia stock market economy",
    "KR": "Korea stock market economy",
    "JP": "Japan stock market economy",
    "TW": "Taiwan stock market economy",
}

def _interleave(groups: list[list[GlobalArticle]]) -> list[GlobalArticle]:
    result: list[GlobalArticle] = []
    highest = max((len(group) for group in groups), default=0)
    for index in range(highest):
        for group in groups:
            if index < len(group):
                result.append(group[index])
    return result


def _fetch_google_news_market(market: str) -> list[GlobalArticle]:
    query = _REGIONAL_MARKET_QUERIES[market]
    url = "https://news.google.com/rss/search?q=" + quote_plus(query) + "&hl=en-US&gl=US&ceid=US:en"
    per_market_limit = max(1, (NEWS_SOURCE_ARTICLE_LIMIT + 6) // 7)
    articles = fetch_rss_articles(url, f"gnews:{market}", max_articles=per_market_limit)
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
    """Public RSS source with market-specific queries."""
    markets = list(_REGIONAL_MARKET_QUERIES)
    with ThreadPoolExecutor(max_workers=len(markets)) as executor:
        futures = {market: executor.submit(_fetch_google_news_market, market) for market in markets}
        groups = []
        for market in markets:
            try:
                groups.append(futures[market].result())
            except Exception:
                groups.append([])
    return _interleave(groups)[:NEWS_SOURCE_ARTICLE_LIMIT]
