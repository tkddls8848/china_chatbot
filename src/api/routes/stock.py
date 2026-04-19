from fastapi import APIRouter, Depends, Query

from src.api.deps import get_stock_service
from src.services.stock_service import StockService

router = APIRouter()


@router.get("/search")
async def search_stocks(q: str = Query(...), svc: StockService = Depends(get_stock_service)) -> list[dict]:
    return await svc.search(q)


@router.get("/{ticker}")
async def get_stock(ticker: str, svc: StockService = Depends(get_stock_service)) -> dict:
    return await svc.get_info(ticker)


@router.get("/{ticker}/chart")
async def get_chart(
    ticker: str,
    period: str = "1mo",
    interval: str = "1d",
    svc: StockService = Depends(get_stock_service),
) -> list[dict]:
    return await svc.get_chart(ticker, period, interval)


@router.get("/{ticker}/news")
async def get_stock_news(
    ticker: str,
    limit: int = 20,
    svc: StockService = Depends(get_stock_service),
) -> list[dict]:
    return await svc.get_news(ticker, limit)
