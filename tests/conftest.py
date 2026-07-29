"""공통 테스트 부트스트랩과 샌드박스 친화적인 임시 경로 설정."""

import os
import sys
import tempfile
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = WORKSPACE_ROOT / "app"
TEST_TEMP_ROOT = WORKSPACE_ROOT / ".test-tmp"

sys.path.insert(0, str(APP_ROOT))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")

TEST_TEMP_ROOT.mkdir(exist_ok=True)
for variable in ("TMPDIR", "TEMP", "TMP", "PYTEST_DEBUG_TEMPROOT"):
    os.environ[variable] = str(TEST_TEMP_ROOT)
tempfile.tempdir = str(TEST_TEMP_ROOT)
