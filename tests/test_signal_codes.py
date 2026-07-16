"""신호 로그 코드 검증 테스트.

LLM이 추출한 mentioned_stocks에 미국 티커(JNJ.N, NVDA 등)가 섞여
prediction_log에 기록되고 /score에서 시세 조회 실패를 일으키는 회귀 방지.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

from news.utils import signal_codes
from state.scoring import load_signals


def test_signal_codes_drops_non_china_hk_tickers():
    raw = ["JNJ.N", "NVDA", "NVDA.O", "GOOGL", "600519", "09988"]
    assert signal_codes(raw) == ["600519", "09988"]


def test_signal_codes_normalizes_and_dedupes():
    # 정규화(0패딩) 후 중복은 한 번만
    assert signal_codes(["9988", "09988", "600519"]) == ["09988", "600519"]
    assert signal_codes([]) == []
    assert signal_codes(None) == []


def test_load_signals_skips_non_numeric_codes(tmp_path):
    # 이미 로그에 기록된 과거 미국 티커 줄도 채점에서 제외되어야 한다.
    log = tmp_path / "prediction_log.jsonl"
    log.write_text(
        '{"ts": "2026-07-16T19:33:26", "sentiment": 0.4, "codes": ["JNJ.N"]}\n'
        '{"ts": "2026-07-16T19:38:06", "sentiment": 0.6, "codes": ["NVDA"]}\n'
        '{"ts": "2026-07-16T19:40:00", "sentiment": 0.9, "codes": ["600519", "GOOGL"]}\n',
        encoding="utf-8",
    )
    signals, neutral = load_signals(log, threshold=0.2)
    assert [s["code"] for s in signals] == ["600519"]
    assert neutral == 0
