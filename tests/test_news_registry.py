import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

from news.registry import NewsSourceRegistry, build_source_specs


def _registry(**kwargs) -> NewsSourceRegistry:
    specs = build_source_specs(["futu", "em"], [])
    return NewsSourceRegistry(specs, **kwargs)


def test_build_source_specs_ignores_unknown_and_duplicates():
    specs = build_source_specs(["futu", "unknown", "futu", "sina"], [("내RSS", "http://x/feed")])
    keys = [spec.key for spec in specs]
    assert keys == ["futu", "sina", "rss:내RSS"]
    assert specs[2].prompt_key == "global"


def test_build_source_specs_supports_google_news_provider():
    specs = build_source_specs(["gnews", "gnews_us"], [])

    assert [spec.key for spec in specs] == ["gnews", "gnews_us"]
    assert all(spec.prompt_key == "global" for spec in specs)


def test_source_cooldown_after_consecutive_failures():
    registry = _registry(failure_threshold=3, cooldown_minutes=60)
    assert [s.key for s in registry.active_specs()] == ["futu", "em"]

    registry.record_failure("futu", "boom")
    registry.record_failure("futu", "boom")
    assert [s.key for s in registry.active_specs()] == ["futu", "em"]

    registry.record_failure("futu", "boom")
    assert [s.key for s in registry.active_specs()] == ["em"]


def test_cooldown_expires_and_source_returns():
    registry = _registry(failure_threshold=1, cooldown_minutes=60)
    registry.record_failure("em", "boom")
    assert [s.key for s in registry.active_specs()] == ["futu"]

    # 쿨다운 만료를 시뮬레이션
    registry._health["em"].cooldown_until = datetime.now() - timedelta(seconds=1)
    assert [s.key for s in registry.active_specs()] == ["futu", "em"]


def test_success_resets_failure_streak():
    registry = _registry(failure_threshold=3, cooldown_minutes=60)
    registry.record_failure("futu", "boom")
    registry.record_failure("futu", "boom")
    registry.record_success("futu")
    registry.record_failure("futu", "boom")
    registry.record_failure("futu", "boom")
    assert [s.key for s in registry.active_specs()] == ["futu", "em"]


def test_status_lines_report_states():
    registry = _registry(failure_threshold=1, cooldown_minutes=60)
    registry.record_failure("em", "boom")
    lines = registry.status_lines()
    assert lines[0] == "futu: 정상"
    assert lines[1].startswith("em: 쿨다운")
