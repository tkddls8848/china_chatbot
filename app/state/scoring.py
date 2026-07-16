"""감성 신호를 실제 주가 방향과 대조해 채점하는 순수 로직.

scripts/score_predictions.py CLI와 /score 텔레그램 핸들러가 공유한다.

채점 프로토콜(docs/plan.md §5 4단계 통제 ①·② 적용):
- 같은 날 같은 종목의 신호는 감성 평균으로 합쳐 하루 1건으로 만든다.
- |평균 감성| < threshold 이면 중립으로 보고 채점에서 제외한다.
- 기준가는 신호일 이후 첫 거래일 종가, 비교가는 그로부터 N거래일 뒤 종가
  (뉴스 발행 이후 가격만 사용 — look-ahead 통제. 단, 장중 뉴스가 당일 종가에
  이미 일부 반영되는 잔여 누수는 v1 한계다).
- 적중률은 항상-상승 기준선(base rate)과 함께 표기한다. 적중률이
  max(base, 1-base)를 지속 상회해야 신호에 정보가 있다(plan.md §6).
"""

import json
import logging
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_HORIZONS = [1, 3, 5]
DEFAULT_THRESHOLD = 0.2


def load_signals(log_path: Path, threshold: float) -> tuple[list[dict], int]:
    """JSONL을 (종목, 일자)별 평균 감성으로 합쳐 방향 신호 목록을 만든다.

    반환: (신호 목록, 중립 제외 건수). 파일이 없으면 FileNotFoundError.
    """
    if not log_path.exists():
        raise FileNotFoundError(log_path)

    per_day: dict[tuple[str, date], list[float]] = defaultdict(list)
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            ts = datetime.fromisoformat(str(entry["ts"]))
            sentiment = float(entry["sentiment"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        for code in entry.get("codes") or []:
            code = str(code).strip()
            if code:
                per_day[(code, ts.date())].append(sentiment)

    signals: list[dict] = []
    neutral = 0
    for (code, day), values in sorted(per_day.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        avg = sum(values) / len(values)
        if abs(avg) < threshold:
            neutral += 1
            continue
        signals.append({"code": code, "date": day, "avg": avg, "up": avg > 0})
    return signals, neutral


def _closes_from_df(df, date_col: str, close_col: str) -> "pd.Series | None":
    if df is None or df.empty or date_col not in df.columns or close_col not in df.columns:
        return None
    closes = pd.Series(
        pd.to_numeric(df[close_col], errors="coerce").values,
        index=pd.to_datetime(df[date_col], errors="coerce"),
    ).dropna().sort_index()
    return closes if not closes.empty else None


def fetch_closes(code: str, start: date, end: date) -> "pd.Series | None":
    """AkShare 일봉 종가 시계열(날짜 오름차순). 실패하면 None.

    1차 동방재부(east) → 2차 신랑(sina) 순으로 페일오버한다(뉴스 소스 레지스트리와 같은 패턴).
    """
    start_s, end_s = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    if len(code) == 5:  # 홍콩
        attempts = [
            ("east", lambda: ak.stock_hk_hist(
                symbol=code, period="daily",
                start_date=start_s, end_date=end_s, adjust="",
            ), "日期", "收盘"),
            ("sina", lambda: ak.stock_hk_daily(symbol=code, adjust=""), "date", "close"),
        ]
    else:  # A주
        sina_symbol = ("sh" if code.startswith("6") else "sz") + code
        attempts = [
            ("east", lambda: ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=start_s, end_date=end_s, adjust="qfq",
            ), "日期", "收盘"),
            ("sina", lambda: ak.stock_zh_a_daily(
                symbol=sina_symbol, start_date=start_s, end_date=end_s, adjust="qfq",
            ), "date", "close"),
        ]

    last_error: Exception | None = None
    for source, fetch, date_col, close_col in attempts:
        try:
            closes = _closes_from_df(fetch(), date_col, close_col)
        except Exception as e:
            last_error = e
            continue
        if closes is not None:
            # sina 홍콩은 전체 이력을 반환하므로 필요한 구간만 남긴다.
            return closes.loc[pd.Timestamp(start):]
    logger.warning("[SCORE] %s 시세 조회 실패(east/sina 모두): %s", code, last_error)
    return None


def score_signals(signals: list[dict], horizons: list[int]) -> dict[int, dict]:
    """수평별 채점 결과: {수평: {n, hit, up_real, pending}}."""
    codes = sorted({s["code"] for s in signals})
    start = min(s["date"] for s in signals)
    end = date.today()

    logger.info("[SCORE] 시세 조회: %d종목 (%s ~ %s)", len(codes), start, end)
    closes_by_code = {code: fetch_closes(code, start, end) for code in codes}

    results = {h: {"n": 0, "hit": 0, "up_real": 0, "pending": 0} for h in horizons}
    for signal in signals:
        closes = closes_by_code.get(signal["code"])
        if closes is None:
            continue
        # 신호일 '이후' 첫 거래일 종가를 기준가로 삼는다(look-ahead 통제).
        base_pos = closes.index.searchsorted(pd.Timestamp(signal["date"]))
        if base_pos >= len(closes):
            for h in horizons:
                results[h]["pending"] += 1
            continue
        base = float(closes.iloc[base_pos])
        for h in horizons:
            result = results[h]
            exit_pos = base_pos + h
            if exit_pos >= len(closes):
                result["pending"] += 1  # 아직 N거래일이 지나지 않은 신호
                continue
            actual_up = float(closes.iloc[exit_pos]) > base
            result["n"] += 1
            result["up_real"] += int(actual_up)
            result["hit"] += int(actual_up == signal["up"])
    return results


def format_result_lines(results: dict[int, dict], horizons: list[int]) -> list[str]:
    """수평별 결과를 고정폭 표 행 목록으로 만든다(헤더 포함)."""
    lines = [f"{'수평':>4} {'채점':>4} {'적중률':>7} {'상승base':>8} {'미확정':>4}"]
    for h in horizons:
        r = results[h]
        if r["n"] == 0:
            lines.append(f"{h:>3}일 {0:>4} {'-':>7} {'-':>8} {r['pending']:>4}")
            continue
        acc = r["hit"] / r["n"]
        base = r["up_real"] / r["n"]
        lines.append(f"{h:>3}일 {r['n']:>4} {acc:>6.1%} {base:>7.1%} {r['pending']:>4}")
    return lines
