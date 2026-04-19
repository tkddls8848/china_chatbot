from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.deps import get_alert_service
from src.services.alert_service import AlertService

router = APIRouter()


class WatchlistAdd(BaseModel):
    ticker: str
    market: str


@router.get("")
def get_watchlist(svc: AlertService = Depends(get_alert_service)) -> list[dict]:
    return [{"id": i.id, "ticker": i.ticker, "market": i.market} for i in svc.get_watchlist()]


@router.post("")
def add_watchlist(body: WatchlistAdd, svc: AlertService = Depends(get_alert_service)) -> dict:
    item = svc.add_watchlist(body.ticker, body.market)
    return {"id": item.id, "ticker": item.ticker, "market": item.market}


@router.delete("/{ticker}")
def remove_watchlist(ticker: str, svc: AlertService = Depends(get_alert_service)) -> dict:
    return {"ok": svc.remove_watchlist(ticker)}
