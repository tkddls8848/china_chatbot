from fastapi import APIRouter, Depends, Query

from src.api.deps import get_news_service
from src.services.news_service import NewsService

router = APIRouter()


@router.get("")
async def get_news(
    market: str = Query("all"),
    limit: int = Query(20, le=50),
    source: str = Query("all"),
    svc: NewsService = Depends(get_news_service),
) -> list[dict]:
    return await svc.get_news(market, limit, source)
