from fastapi import APIRouter, Depends

from src.api.deps import get_market_service
from src.services.market_service import MarketService

router = APIRouter()


@router.get("")
async def get_all_markets(svc: MarketService = Depends(get_market_service)) -> list[dict]:
    return await svc.get_all_indices()


@router.get("/{market_id}")
async def get_market(market_id: str, svc: MarketService = Depends(get_market_service)) -> dict:
    return await svc.get_index(market_id)


@router.get("/{market_id}/top")
async def get_top_stocks(
    market_id: str,
    limit: int = 20,
    svc: MarketService = Depends(get_market_service),
) -> list[dict]:
    return await svc.get_top_stocks(market_id, limit)
