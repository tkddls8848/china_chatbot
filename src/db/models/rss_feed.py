from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models import Base


class RssFeed(Base):
    __tablename__ = "rss_feeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    market_tag: Mapped[str] = mapped_column(String(16), default="cn")  # cn | hk | global
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
