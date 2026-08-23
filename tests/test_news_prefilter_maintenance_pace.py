"""보정 페이스의 충전/지출 이틀 주기(CLAUDE.md 변경 원칙, 2026-08-23)."""

from datetime import date

from core.config import (
    NEWS_PREFILTER_MAINTENANCE_RECHARGE_SLICE_SECONDS,
    NEWS_PREFILTER_MAINTENANCE_SLICE_SECONDS,
)
from features.news_prefilter import feature as prefilter_feature


def test_day_parity_alternates_recharge_and_spend(monkeypatch):
    monkeypatch.setattr(prefilter_feature, "today", lambda: date(2026, 8, 23))
    even_day = prefilter_feature._is_recharge_day()

    monkeypatch.setattr(prefilter_feature, "today", lambda: date(2026, 8, 24))
    odd_day = prefilter_feature._is_recharge_day()

    assert even_day != odd_day


def test_recharge_day_uses_the_lower_slice(monkeypatch):
    monkeypatch.setattr(prefilter_feature, "_is_recharge_day", lambda: True)

    assert (
        prefilter_feature._maintenance_slice_seconds()
        == NEWS_PREFILTER_MAINTENANCE_RECHARGE_SLICE_SECONDS
    )


def test_spend_day_uses_the_full_slice(monkeypatch):
    monkeypatch.setattr(prefilter_feature, "_is_recharge_day", lambda: False)

    assert (
        prefilter_feature._maintenance_slice_seconds()
        == NEWS_PREFILTER_MAINTENANCE_SLICE_SECONDS
    )


def test_recharge_slice_is_meaningfully_below_spend_slice():
    """충전일이 지출일보다 확실히 낮아야 순 충전이 된다."""
    assert (
        NEWS_PREFILTER_MAINTENANCE_RECHARGE_SLICE_SECONDS
        < NEWS_PREFILTER_MAINTENANCE_SLICE_SECONDS
    )
