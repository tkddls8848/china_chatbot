from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_OWNER_ID: int = 0       # 봇 주인 텔레그램 ID (1인 전용)
    WEBAPP_URL: str = ""

    DATABASE_URL: str = "sqlite:///./chinachat.db"

    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    CACHE_TTL_SECONDS: int = 900


settings = Settings()
