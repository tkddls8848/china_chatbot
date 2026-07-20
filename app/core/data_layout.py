"""data/ 하위 파일의 기능별 디렉토리 배치와 레거시 평면 배치 이전.

데이터 파일은 코드의 기능 모듈 구조와 같은 기준으로 소유 기능 키의
하위 디렉토리(data/news/, data/watchlist/, ...)에 둔다. 과거 버전은
data/ 바로 아래 평면으로 저장했으므로, 봇 시작 시 한 번 새 위치가
비어 있는 옛 파일을 옮겨 기존 배포의 데이터를 보존한다.
"""

import logging
from pathlib import Path

from core.config import (
    DATA_DIR,
    NEWS_LOG_FILE,
    PREDICTION_LOG_FILE,
    RESEARCH_STATE_FILE,
    SENT_IDS_FILE,
    STOCK_DB_FILE,
    WATCHLIST_EVENTS_FILE,
    WATCHLIST_FILE,
)

logger = logging.getLogger(__name__)


def _default_pairs() -> list[tuple[Path, Path]]:
    """(레거시 경로, 새 경로) 목록. 레거시는 data/ 바로 아래 같은 파일명."""
    new_paths = (
        SENT_IDS_FILE,
        NEWS_LOG_FILE,
        WATCHLIST_FILE,
        WATCHLIST_EVENTS_FILE,
        STOCK_DB_FILE,
        PREDICTION_LOG_FILE,
        RESEARCH_STATE_FILE,
    )
    return [(DATA_DIR / path.name, path) for path in new_paths]


def migrate_legacy_data_files(
    pairs: list[tuple[Path, Path]] | None = None,
) -> list[Path]:
    """레거시 평면 배치 파일을 기능별 디렉토리로 옮긴다.

    새 위치에 파일이 이미 있으면 데이터 손실을 막기 위해 옛 파일을
    건드리지 않고 경고만 남긴다. 옮긴 새 경로 목록을 반환한다.
    """
    moved: list[Path] = []
    for legacy, current in pairs if pairs is not None else _default_pairs():
        if not legacy.exists():
            continue
        if current.exists():
            logger.warning(
                "[DATA] 새 위치 %s가 이미 있어 레거시 %s를 옮기지 않았습니다.",
                current,
                legacy,
            )
            continue
        current.parent.mkdir(parents=True, exist_ok=True)
        legacy.rename(current)
        moved.append(current)
        logger.info("[DATA] 데이터 파일 이동: %s -> %s", legacy, current)
    return moved
