from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_OWNER_ID: int = 0
    WEBAPP_URL: str = ""

    DATABASE_URL: str = "sqlite:///./data/app.db"

    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    CACHE_TTL_SECONDS: int = 900

    RSSHUB_BASE_URL: str = "http://localhost:1200"
    RSS_FEED_URLS: str = (
        "http://localhost:1200/cls/telegraph,"
        "http://localhost:1200/cls/hot,"
        "http://localhost:1200/eastmoney/report/strategyreport,"
        "http://localhost:1200/eastmoney/search/A股,"
        "http://localhost:1200/sina/news/stock,"
        "http://localhost:1200/sse/disclosure,"
        "http://localhost:1200/scmp/section/2,"
        "http://localhost:1200/reuters/cn"
    )
    RSS_SOURCE_LABELS: str = "财联社전보,财联社인기,东方财富리서치,东方财富A株,新浪财经,上交所공시,SCMP,Reuters"
    RSS_MAX_ITEMS_PER_FEED: int = 20
    RSS_FETCH_TIMEOUT: int = 10

    ADMIN_TOKEN: str = "change-me"

    TRANSLATE_ENABLED: bool = False
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    TRANSLATE_MODEL: str = "qwen2.5:7b"
    TRANSLATE_BATCH_SIZE: int = 20


settings = Settings()
