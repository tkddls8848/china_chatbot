import logging

import akshare as ak
import feedparser
import requests.exceptions
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


def _retry_on_network(func):
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(requests.exceptions.RequestException),
        reraise=True,
    )(func)


class AkshareClient:
    @_retry_on_network
    def fetch_cls_raw(self):
        return ak.stock_info_global_cls()

    @_retry_on_network
    def fetch_futu_raw(self):
        return ak.stock_info_global_futu()

    @_retry_on_network
    def fetch_stock_news_raw(self, symbol: str):
        return ak.stock_news_em(symbol=symbol)

    def resolve_stock_name(self, code: str) -> str:
        if len(code) <= 5:
            df = ak.stock_individual_basic_info_hk_xq(symbol=code)
            name = df[df["item"] == "comcnname"]["value"].values[0]
        elif code.startswith(("00", "30")):
            df = ak.stock_individual_basic_info_xq(symbol=f"SZ{code}")
            name = df[df["item"] == "org_short_name_cn"]["value"].values[0]
        elif code.startswith(("60", "68")):
            df = ak.stock_individual_basic_info_xq(symbol=f"SH{code}")
            name = df[df["item"] == "org_short_name_cn"]["value"].values[0]
        else:
            raise ValueError(f"unknown stock code format: {code}")
        return str(name)


class XinhuaClient:
    def __init__(self, feeds: list[str]):
        self._feeds = feeds

    def fetch_entries(self) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for feed_url in self._feeds:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries:
                    title = entry.get("title", "").strip()
                    content = entry.get("summary", entry.get("description", "")).strip()
                    link = entry.get("link", "")
                    published = entry.get("published", "")
                    if title:
                        entries.append(
                            {
                                "title": title,
                                "content": content,
                                "link": link,
                                "published": published,
                            }
                        )
            except Exception as e:
                logger.error("[XINHUA] RSS fetch failed (%s): %s", feed_url, e)
        return entries
