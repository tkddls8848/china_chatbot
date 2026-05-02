import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    bot_token: str
    chat_id: str
    sent_ids_file: Path
    watchlist_file: Path
    stock_db_file: Path
    market_view_file: Path
    prompt_dir: Path
    market_view_prompt_file: Path
    max_sent_ids: int
    telegram_message_limit: int
    cls_futu_news_limit: int
    stock_news_limit: int
    schedule_interval_minutes: int
    translate_concurrency: int
    stock_db_enabled: bool
    view_max_changes: int
    view_max_add: int
    view_max_remove: int
    view_pending_ttl_minutes: int
    view_news_limit_per_stock: int
    view_max_news_items: int
    view_global_news_limit: int
    view_news_days: int
    view_max_candidates: int
    market_view_num_predict: int
    xinhua_enabled: bool
    xinhua_news_limit: int
    xinhua_feeds: list[str]
    ollama_base_url: str
    ollama_num_gpu: int
    translate_model: str
    translate_enabled: bool
    translate_timeout: int
    translate_fallback_to_original: bool
    translate_num_predict: int
    market_view_model: str
    market_view_enabled: bool
    market_view_timeout: int

    @classmethod
    def from_env(cls) -> "Settings":
        base_dir = Path(__file__).resolve().parent.parent
        load_dotenv(base_dir / ".env")
        prompt_dir = Path(os.environ.get("TRANSLATE_PROMPT_DIR", "prompts"))
        if not prompt_dir.is_absolute():
            prompt_dir = base_dir / prompt_dir

        return cls(
            base_dir=base_dir,
            bot_token=os.environ["BOT_TOKEN"],
            chat_id=os.environ["CHAT_ID"],
            sent_ids_file=base_dir / "data" / "sent_ids.json",
            watchlist_file=base_dir / "data" / "watchlist.json",
            stock_db_file=base_dir / "data" / "stock_db.json",
            market_view_file=base_dir / "data" / "market_view.json",
            prompt_dir=prompt_dir,
            market_view_prompt_file=prompt_dir / "market_view_ko.txt",
            max_sent_ids=1000,
            telegram_message_limit=4096,
            cls_futu_news_limit=int(os.environ.get("CLS_FUTU_NEWS_LIMIT", "10")),
            stock_news_limit=int(os.environ.get("STOCK_NEWS_LIMIT", "5")),
            schedule_interval_minutes=int(os.environ.get("SCHEDULE_INTERVAL_MINUTES", "3")),
            translate_concurrency=int(os.environ.get("TRANSLATE_CONCURRENCY", "2")),
            stock_db_enabled=os.environ.get("STOCK_DB_ENABLED", "true").lower() == "true",
            view_max_changes=int(os.environ.get("VIEW_MAX_CHANGES", "5")),
            view_max_add=int(os.environ.get("VIEW_MAX_ADD", "5")),
            view_max_remove=int(os.environ.get("VIEW_MAX_REMOVE", "3")),
            view_pending_ttl_minutes=int(os.environ.get("VIEW_PENDING_TTL_MINUTES", "10")),
            view_news_limit_per_stock=int(os.environ.get("VIEW_NEWS_LIMIT_PER_STOCK", "2")),
            view_max_news_items=int(os.environ.get("VIEW_MAX_NEWS_ITEMS", "20")),
            view_global_news_limit=int(os.environ.get("VIEW_GLOBAL_NEWS_LIMIT", "20")),
            view_news_days=int(os.environ.get("VIEW_NEWS_DAYS", "7")),
            view_max_candidates=int(os.environ.get("VIEW_MAX_CANDIDATES", "60")),
            market_view_num_predict=int(os.environ.get("MARKET_VIEW_NUM_PREDICT", "1024")),
            xinhua_enabled=os.environ.get("XINHUA_ENABLED", "true").lower() == "true",
            xinhua_news_limit=int(os.environ.get("XINHUA_NEWS_LIMIT", "5")),
            xinhua_feeds=[
                os.environ.get("XINHUA_FEED_POLITICS", "http://www.xinhuanet.com/politics/rss.htm"),
                os.environ.get("XINHUA_FEED_ECONOMY", "http://www.xinhuanet.com/fortune/rss.htm"),
            ],
            ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
            ollama_num_gpu=int(os.environ.get("OLLAMA_NUM_GPU", "0")),
            translate_model=os.environ.get("TRANSLATE_MODEL", "gemma4"),
            translate_enabled=os.environ.get("TRANSLATE_ENABLED", "true").lower() == "true",
            translate_timeout=int(os.environ.get("TRANSLATE_TIMEOUT", "60")),
            translate_fallback_to_original=(
                os.environ.get("TRANSLATE_FALLBACK_TO_ORIGINAL", "false").lower() == "true"
            ),
            translate_num_predict=int(os.environ.get("TRANSLATE_NUM_PREDICT", "768")),
            market_view_model=os.environ.get(
                "MARKET_VIEW_MODEL",
                os.environ.get("TRANSLATE_MODEL", "gemma4"),
            ),
            market_view_enabled=os.environ.get("MARKET_VIEW_ENABLED", "true").lower() == "true",
            market_view_timeout=int(
                os.environ.get("MARKET_VIEW_TIMEOUT", os.environ.get("TRANSLATE_TIMEOUT", "180"))
            ),
        )
