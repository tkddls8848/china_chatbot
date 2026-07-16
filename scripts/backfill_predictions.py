"""과거 뉴스를 일괄 수집·감성 추출해 백테스트용 신호 로그를 만든다.

봇을 일정 기간 운영해 data/prediction_log.jsonl을 쌓는 대신, 종목별 과거
뉴스(ak.stock_news_em, 종목당 최근 약 100건)를 한 번에 긁어 봇과 동일한
프롬프트·LLM 호출로 감성을 추출하고, ts를 '뉴스 발행 시각'으로 기록한다.
결과는 운영 로그와 분리된 data/backtest_log.jsonl에 저장하며,
scripts/score_predictions.py --log 로 채점한다.

제약:
- stock_news_em은 임의 기간 조회를 지원하지 않는다. --days는 반환된 최근
  ~100건 안에서 자르는 필터일 뿐이다.
- 전역 속보 스트림(CLS/Futu 등)은 현재 페이지만 반환하므로 백필할 수 없다.

사용법(venv에서, Ollama 실행 중이어야 함):
    python scripts/backfill_predictions.py                  # 관심종목 전체
    python scripts/backfill_predictions.py --codes 600519,09988 --days 14
    python scripts/backfill_predictions.py --limit 10       # 종목당 최대 10건
    python scripts/score_predictions.py --log data/backtest_log.jsonl

중단 후 재실행하면 출력 로그에 이미 있는 기사는 건너뛴다(이어하기).
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

# Windows 콘솔(cp949)에서 중국어 제목 출력이 깨지지 않도록.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from core.config import (  # noqa: E402  (.env 읽기는 config.py로 일원화)
    BACKTEST_LOG_FILE,
    OLLAMA_BASE_URL,
    OLLAMA_NUM_GPU,
    PROMPT_DIR,
    TRANSLATION_MODEL,
    TRANSLATION_NUM_PREDICT,
    TRANSLATION_TIMEOUT,
    WATCHLIST_FILE,
)
from llm.translator import TranslationError, TranslationService  # noqa: E402
from news.sources import fetch_stock_news_raw  # noqa: E402
from news.utils import normalize_stock_code  # noqa: E402

DEFAULT_LOG = BACKTEST_LOG_FILE


def load_watchlist_codes() -> list[str]:
    if not WATCHLIST_FILE.exists():
        sys.exit(f"관심종목 파일이 없습니다: {WATCHLIST_FILE} (--codes로 직접 지정하세요)")
    data = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    return list(data.keys())


def load_done_keys(log_path: Path) -> set[str]:
    """출력 로그에 이미 기록된 기사 키(발행시각+제목 앞 20자) 집합."""
    if not log_path.exists():
        return set()
    done: set[str] = set()
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
            done.add(str(entry.get("article_key", "")))
        except (ValueError, json.JSONDecodeError):
            continue
    done.discard("")
    return done


def backfill_symbol(
    code: str,
    translator: TranslationService,
    cutoff: datetime,
    limit: int,
    done: set[str],
    log_path: Path,
) -> tuple[int, int]:
    """한 종목의 과거 뉴스를 감성 추출해 로그에 기록. (기록, 실패) 건수 반환."""
    try:
        df = fetch_stock_news_raw(code)
    except Exception as e:
        print(f"  [경고] {code} 뉴스 조회 실패: {e}")
        return 0, 0
    if df is None or df.empty:
        print(f"  {code}: 반환된 뉴스 없음")
        return 0, 0

    published = pd.to_datetime(df["发布时间"], errors="coerce")
    df = df[published >= cutoff]
    if limit > 0:
        df = df.head(limit)
    if df.empty:
        print(f"  {code}: 기간 내 뉴스 없음")
        return 0, 0

    written = failed = 0
    for _, row in df.iterrows():
        title = str(row["新闻标题"])
        key = str(row["发布时间"]) + title[:20]
        if key in done:
            continue
        try:
            translated = translator.translate_article(
                "stock", title, str(row["新闻内容"])
            )
        except TranslationError as e:
            failed += 1
            print(f"    [실패] {title[:40]}: {e}")
            continue
        if translated.sentiment is None:
            failed += 1
            print(f"    [실패] {title[:40]}: 감성 없음")
            continue

        # 운영 로그와 같은 스키마 + 백필 식별 필드. ts는 '뉴스 발행 시각'.
        entry = {
            "ts": pd.Timestamp(row["发布时间"]).isoformat(timespec="seconds"),
            "source": "stock",
            "title": translated.title[:120],
            "sentiment": translated.sentiment,
            "impact": translated.impact,
            "codes": [code],
            "article_key": key,
            "backfill": True,
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        done.add(key)
        written += 1
        print(f"    [{written}] {translated.sentiment:+.2f} {translated.title[:50]}")
    return written, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="과거 뉴스 일괄 감성 추출(백테스트 신호 생성)")
    parser.add_argument("--codes", default="", help="종목 코드(쉼표 구분). 비우면 관심종목 전체")
    parser.add_argument("--days", type=int, default=30, help="최근 N일 이내 뉴스만 처리")
    parser.add_argument("--limit", type=int, default=0, help="종목당 최대 처리 건수(0=제한 없음)")
    parser.add_argument("--log", default=str(DEFAULT_LOG), help="출력 JSONL 경로")
    args = parser.parse_args()

    codes = [normalize_stock_code(c.strip()) for c in args.codes.split(",") if c.strip()]
    if not codes:
        codes = load_watchlist_codes()
    if not codes:
        sys.exit("처리할 종목이 없습니다.")

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    done = load_done_keys(log_path)
    cutoff = datetime.now() - timedelta(days=max(1, args.days))

    translator = TranslationService(
        base_url=OLLAMA_BASE_URL,
        model=TRANSLATION_MODEL,
        enabled=True,
        timeout=TRANSLATION_TIMEOUT,
        prompt_dir=PROMPT_DIR,
        num_gpu=OLLAMA_NUM_GPU,
        num_predict=TRANSLATION_NUM_PREDICT,
    )

    print(f"백필 대상 {len(codes)}종목, 기간 {cutoff.date()} ~ 오늘, 모델 {TRANSLATION_MODEL}")
    if done:
        print(f"기존 로그에서 {len(done)}건 발견 — 중복 기사는 건너뜁니다.")

    total_written = total_failed = 0
    for i, code in enumerate(codes, 1):
        print(f"[{i}/{len(codes)}] {code}")
        written, failed = backfill_symbol(code, translator, cutoff, args.limit, done, log_path)
        total_written += written
        total_failed += failed

    print()
    print(f"완료: 신호 {total_written}건 기록, 실패 {total_failed}건 → {log_path}")
    if total_written or done:
        print(f"채점: python scripts/score_predictions.py --log {log_path}")


if __name__ == "__main__":
    main()
