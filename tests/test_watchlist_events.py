import asyncio

from watchlist.events import WatchlistEventLog, build_scorecard_lines


def test_event_log_record_and_snapshot(tmp_path):
    log = WatchlistEventLog(tmp_path / "events.json")

    async def run():
        await log.record("add", "600519", "귀주모태주", 1700.0, "리서치 적용")
        await log.record("remove", "09988", "알리바바", 80.0, "수동 삭제")
        return await log.snapshot(lookback_days=7)

    events = asyncio.run(run())
    assert len(events) == 2
    assert events[0]["event"] == "add"
    assert events[1]["price"] == 80.0

    # 파일에서 다시 읽어도 유지된다.
    reloaded = WatchlistEventLog(tmp_path / "events.json")
    events = asyncio.run(reloaded.snapshot(lookback_days=7))
    assert len(events) == 2


def test_scorecard_lines_for_add_and_remove():
    events = [
        {"ts": "2026-06-20T09:00:00", "event": "add", "code": "600519", "name": "귀주모태주", "price": 100.0},
        {"ts": "2026-06-21T09:00:00", "event": "remove", "code": "09988", "name": "알리바바", "price": 80.0},
    ]
    watchlist = {"600519": "귀주모태주"}
    prices = {"600519": 110.0, "09988": 72.0}

    lines = build_scorecard_lines(events, watchlist, prices)
    assert len(lines["added"]) == 1
    assert "+10.0%" in lines["added"][0]
    assert len(lines["removed"]) == 1
    assert "-10.0%" in lines["removed"][0]


def test_scorecard_uses_latest_event_per_code():
    events = [
        {"ts": "2026-06-01T09:00:00", "event": "add", "code": "600519", "name": "귀주모태주", "price": 100.0},
        {"ts": "2026-06-10T09:00:00", "event": "remove", "code": "600519", "name": "귀주모태주", "price": 120.0},
    ]
    lines = build_scorecard_lines(events, {}, {"600519": 90.0})
    assert lines["added"] == []
    assert len(lines["removed"]) == 1
    assert "-25.0%" in lines["removed"][0]


def test_scorecard_handles_missing_price():
    events = [
        {"ts": "2026-06-20T09:00:00", "event": "add", "code": "600519", "name": "귀주모태주", "price": None},
    ]
    lines = build_scorecard_lines(events, {"600519": "귀주모태주"}, {"600519": 110.0})
    assert "가격 데이터 없음" in lines["added"][0]


def test_scorecard_escapes_custom_names_for_telegram_html():
    events = [
        {
            "ts": "2026-06-20T09:00:00",
            "event": "add",
            "code": "US:NASDAQ:AAPL",
            "name": "<b>A&B</b>",
            "price": 100.0,
        }
    ]
    watchlist = {"US:NASDAQ:AAPL": "<b>A&B</b>"}

    lines = build_scorecard_lines(
        events,
        watchlist,
        {"US:NASDAQ:AAPL": 110.0},
    )

    assert "&lt;b&gt;A&amp;B&lt;/b&gt;" in lines["added"][0]
