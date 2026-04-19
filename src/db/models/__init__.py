from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from src.db.models.watchlist import Watchlist  # noqa: E402
from src.db.models.alert import Alert  # noqa: E402

__all__ = ["Base", "Watchlist", "Alert"]
