"""data/signal_scoring/prediction_log.jsonl의 감성 신호를 실제 주가 방향과 대조해 채점한다.

봇 런타임과 완전히 분리된 오프라인 스크립트(docs/plan.md §5 1단계 C).
채점 로직은 app/state/scoring.py를 사용한다(/score 텔레그램 명령과 동일).

사용법(venv에서):
    python scripts/score_predictions.py
    python scripts/score_predictions.py --horizons 1,3,5 --threshold 0.2
    python scripts/score_predictions.py --log data/another_prediction_log.jsonl
"""

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

DEFAULT_LOG = ROOT / "data" / "signal_scoring" / "prediction_log.jsonl"

# Windows 콘솔(cp949)에서 한글 출력이 깨지지 않도록.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from state.scoring import (  # noqa: E402
    DEFAULT_THRESHOLD,
    format_result_lines,
    load_signals,
    score_signals,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="감성 신호의 N거래일 방향 적중률 채점")
    parser.add_argument("--log", default=str(DEFAULT_LOG), help="prediction_log.jsonl 경로")
    parser.add_argument("--horizons", default="1,3,5", help="채점 수평(거래일, 쉼표 구분)")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="중립 제외 감성 임계값")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    horizons = sorted({int(x) for x in args.horizons.split(",") if x.strip()})
    try:
        signals, neutral = load_signals(Path(args.log), args.threshold)
    except FileNotFoundError as e:
        sys.exit(f"신호 파일이 없습니다: {e}")

    print(f"채점 대상 신호 {len(signals)}건 (중립 제외 {neutral}건, threshold={args.threshold})")
    if not signals:
        print("채점할 신호가 없습니다. 봇을 며칠 운영해 신호를 쌓은 뒤 다시 실행하세요.")
        return

    up_count = sum(1 for s in signals if s["up"])
    print(f"신호 방향 분포: 상승 {up_count} / 하락 {len(signals) - up_count}")
    print()

    results = score_signals(signals, horizons)
    print()
    for line in format_result_lines(results, horizons):
        print(line)
    print()
    print("해석: 적중률이 max(base, 1-base)를 지속 상회해야 신호에 정보가 있다 (docs/plan.md §6).")


if __name__ == "__main__":
    main()
