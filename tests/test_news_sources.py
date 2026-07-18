import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from news import sources


def test_empty_stock_search_is_returned_as_empty_dataframe(monkeypatch):
    def missing_search_result(*, symbol):
        assert symbol == "09518"
        raise KeyError("code")

    monkeypatch.setattr(sources.ak, "stock_news_em", missing_search_result)

    result = sources.fetch_stock_news_raw("09518")

    assert result.empty
    assert list(result.columns) == [
        "关键词",
        "新闻标题",
        "新闻内容",
        "发布时间",
        "文章来源",
        "新闻链接",
    ]


def test_unexpected_stock_news_key_error_is_not_hidden(monkeypatch):
    def broken_response(*, symbol):
        raise KeyError("result")

    monkeypatch.setattr(sources.ak, "stock_news_em", broken_response)

    with pytest.raises(KeyError, match="result"):
        sources.fetch_stock_news_raw("09518")


def test_stock_news_dataframe_passes_through(monkeypatch):
    expected = pd.DataFrame([{"新闻标题": "뉴스"}])
    monkeypatch.setattr(
        sources.ak,
        "stock_news_em",
        lambda *, symbol: expected,
    )

    assert sources.fetch_stock_news_raw("600519") is expected


def test_periodic_us_market_source_interleaves_queries(monkeypatch):
    def fake_query(query, query_index, limit):
        assert "when:1d" in query
        assert limit == 4
        rows = [
            sources.GlobalArticle(
                article_id=f"us:{query_index}:{row}",
                title=f"US headline {query_index}-{row}",
                content="Market news",
                published_at="2026-07-18 10:00:00",
                url=f"https://example.com/{query_index}/{row}",
                extra={"market": "US"},
            )
            for row in range(4)
        ]
        if query_index == 2:
            rows[0] = sources.GlobalArticle(
                article_id="duplicate",
                title="Duplicate headline",
                content="Market news",
                published_at="2026-07-18 10:00:00",
                url="https://example.com/0/0",
                extra={"market": "US"},
            )
        return rows

    monkeypatch.setattr(sources, "_fetch_google_news_us_query", fake_query)

    articles = sources.fetch_google_news_us_stock_articles()

    assert len(articles) == 10
    assert [article.title for article in articles[:6]] == [
        "US headline 0-0",
        "US headline 1-0",
        "US headline 0-1",
        "US headline 1-1",
        "US headline 2-1",
        "US headline 0-2",
    ]
    assert sum(article.url == "https://example.com/0/0" for article in articles) == 1
    assert all(article.extra["market"] == "US" for article in articles)
