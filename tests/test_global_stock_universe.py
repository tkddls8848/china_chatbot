"""미국·한국 종목 유니버스와 시장 선택 입력의 회귀 테스트."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

from stocks.universe import parse_nasdaq_directory, stock_key
from watchlist.handlers import normalize_selected_stock_code


def test_parse_nasdaq_directory_keeps_common_stock_and_exchange():
    rows = parse_nasdaq_directory(
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
        "NVDA|NVIDIA Corporation Common Stock|Q|N|N|100|N|N\n"
        "QQQ|Invesco QQQ Trust|Q|N|N|100|Y|N\n"
        "File Creation Time: 20260717\n",
        "NASDAQ",
    )

    assert rows == [
        {
            "key": "US:NASDAQ:NVDA",
            "code": "NVDA",
            "display_name": "NVIDIA Corporation Common Stock",
            "market": "US",
            "exchange": "NASDAQ",
            "yahoo_ticker": "NVDA",
        }
    ]


def test_stock_key_prevents_same_numeric_code_collisions():
    assert stock_key("KR", "KOSPI", "005930") == "KR:KOSPI:005930"
    assert stock_key("US", "NYSE", "BRK.B") == "US:NYSE:BRK.B"


def test_selected_market_normalizes_only_its_expected_input():
    assert normalize_selected_stock_code("KR:KOSPI", "5930") == "KR:KOSPI:005930"
    assert normalize_selected_stock_code("US:NASDAQ", "nvda") == "US:NASDAQ:NVDA"
    assert normalize_selected_stock_code("US:NASDAQ", "005930") is None
