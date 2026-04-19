from fastapi import Depends
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.services.alert_service import AlertService
from src.services.calendar_service import CalendarService
from src.services.market_service import MarketService
from src.services.news_service import NewsService
from src.services.stock_service import StockService


def get_market_service(db: Session = Depends(get_db)) -> MarketService:
    return MarketService(db)


def get_stock_service(db: Session = Depends(get_db)) -> StockService:
    return StockService(db)


def get_news_service(db: Session = Depends(get_db)) -> NewsService:
    return NewsService(db)


def get_calendar_service(db: Session = Depends(get_db)) -> CalendarService:
    return CalendarService(db)


def get_alert_service(db: Session = Depends(get_db)) -> AlertService:
    return AlertService(db)
