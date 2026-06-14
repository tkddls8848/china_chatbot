import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from momentum.store import MomentumStore


def _base_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _store() -> MomentumStore:
    data_dir = Path(os.environ.get("MOMENTUM_DATA_DIR", "data/momentum"))
    if not data_dir.is_absolute():
        data_dir = _base_dir() / data_dir
    return MomentumStore(data_dir)


def _frame(items: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(items) if items else pd.DataFrame()


def main() -> None:
    st.set_page_config(page_title="중국 섹터 모멘텀", layout="wide")
    st.title("중국 섹터 모멘텀")

    state = _store().load_state()
    result = state.get("last_result")
    if not isinstance(result, dict):
        st.info("저장된 결과가 없습니다. Telegram에서 /momentum refresh를 먼저 실행하세요.")
        return

    st.caption(f"기준일: {result.get('trade_date', 'n/a')} / 생성시각: {result.get('generated_at', 'n/a')}")
    errors = result.get("errors") or []
    if errors:
        st.warning("\n".join(str(error) for error in errors))

    sectors = _frame(result.get("sectors") or [])
    candidates = _frame(result.get("candidates") or [])
    alerts = _frame(result.get("alerts") or [])

    tab_rank, tab_candidates, tab_alerts, tab_backtest = st.tabs(["업종 랭킹", "후보 종목", "알림", "백테스트"])

    with tab_rank:
        if sectors.empty:
            st.info("업종 결과가 없습니다.")
        else:
            columns = [
                "sector_name",
                "alert_level",
                "total_score",
                "eq_ret_20d",
                "ex_sector_rs_20d",
                "rs_rank",
                "turnover_ratio_5d_20d",
                "breadth_above_ma20",
                "breadth_outperform_market_20d",
                "tradable_member_count",
            ]
            st.dataframe(
                sectors[[col for col in columns if col in sectors.columns]],
                use_container_width=True,
                hide_index=True,
            )

    with tab_candidates:
        if candidates.empty:
            st.info("후보 종목이 없습니다.")
        else:
            columns = [
                "sector_name",
                "name",
                "code",
                "ret_20d",
                "excess_ret_20d",
                "turnover_ratio_5d_20d",
                "breakout_20d",
                "breakout_60d",
                "overheat_flag",
                "candidate_score",
            ]
            st.dataframe(
                candidates[[col for col in columns if col in candidates.columns]],
                use_container_width=True,
                hide_index=True,
            )

    with tab_alerts:
        if alerts.empty:
            st.info("알림이 없습니다.")
        else:
            st.dataframe(alerts, use_container_width=True, hide_index=True)

    with tab_backtest:
        backtest = result.get("backtest") if isinstance(result.get("backtest"), dict) else {}
        if not backtest:
            st.info("백테스트 스냅샷이 없습니다.")
        else:
            st.metric("신호 수", backtest.get("signals", 0))
            summary = backtest.get("summary") or {}
            if summary:
                st.dataframe(pd.DataFrame([summary]), use_container_width=True, hide_index=True)
            recent = _frame(backtest.get("recent_signals") or [])
            if not recent.empty:
                st.subheader("최근 백테스트 신호")
                st.dataframe(recent, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
