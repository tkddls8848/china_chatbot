import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from stocks.quotes import QuoteService, parse_sina_moneyflow, parse_tencent_quotes, tencent_symbol


def test_tencent_symbol_maps_markets():
    assert tencent_symbol("600519") == "sh600519"
    assert tencent_symbol("000001") == "sz000001"
    assert tencent_symbol("300888") == "sz300888"
    assert tencent_symbol("430047") == "bj430047"
    assert tencent_symbol("00700") == "hk00700"
    assert tencent_symbol("AAPL") is None


def _fields(price: str, pct: str, amount: str) -> str:
    fields = ["0"] * 40
    fields[1] = "이름"
    fields[3] = price
    fields[32] = pct
    fields[37] = amount
    return "~".join(fields)


def test_parse_tencent_quotes_a_share_and_hk():
    text = (
        f'v_sh600519="{_fields("1253.00", "-0.48", "732273")}";\n'
        f'v_hk00700="{_fields("461.600", "-4.63", "16928705332.9")}";\n'
        'v_pv_none_match="1";'
    )
    quotes = parse_tencent_quotes(text)
    assert set(quotes) == {"600519", "00700"}
    assert quotes["600519"]["price"] == 1253.00
    assert quotes["600519"]["pct_change"] == -0.48
    assert quotes["600519"]["amount"] == 732273 * 1e4  # 만위안 → 위안
    assert quotes["00700"]["amount"] == 16928705332.9  # HK는 원 단위 그대로


def test_parse_tencent_quotes_treats_zero_price_as_missing():
    text = f'v_sz000001="{_fields("0.00", "0.00", "0")}";'
    assert parse_tencent_quotes(text)["000001"]["price"] is None


def test_parse_sina_moneyflow_computes_main_net_inflow():
    payload = {
        "r0_in": "300", "r0_out": "100",
        "r1_in": "200", "r1_out": "150",
        "r2_in": "50", "r2_out": "50",
        "r3_in": "25", "r3_out": "25",
    }
    flow = parse_sina_moneyflow(payload)
    assert flow["main_net_inflow"] == (300 + 200) - (100 + 150)
    assert flow["main_net_inflow_pct"] == 250 / 900 * 100


def test_parse_sina_moneyflow_rejects_incomplete_payload():
    assert parse_sina_moneyflow({"r0_in": "1"}) is None


def test_hot_rank_disabled_by_default_without_network():
    # 인기순위 API는 해외 IP 차단 → 기본 비활성으로 네트워크 호출 없이 빈 값
    assert QuoteService().get_hot_rank_hits(["600519"]) == []
