import akshare as ak
import requests.exceptions
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


def retry_on_network(func):
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(requests.exceptions.RequestException),
        reraise=True,
    )(func)


@retry_on_network
def fetch_cls_raw():
    return ak.stock_info_global_cls()


@retry_on_network
def fetch_futu_raw():
    return ak.stock_info_global_futu()


@retry_on_network
def fetch_stock_news_raw(symbol: str):
    return ak.stock_news_em(symbol=symbol)
