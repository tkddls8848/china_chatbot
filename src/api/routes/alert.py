from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.deps import get_alert_service
from src.services.alert_service import AlertService

router = APIRouter()


class AlertCreate(BaseModel):
    ticker: str
    condition: str  # above | below
    price: float


@router.get("")
def get_alerts(svc: AlertService = Depends(get_alert_service)) -> list[dict]:
    return [{"id": a.id, "ticker": a.ticker, "condition": a.condition, "price": float(a.price)}
            for a in svc.get_alerts()]


@router.post("")
def create_alert(body: AlertCreate, svc: AlertService = Depends(get_alert_service)) -> dict:
    alert = svc.create_alert(body.ticker, body.condition, body.price)
    return {"id": alert.id, "ticker": alert.ticker, "condition": alert.condition, "price": float(alert.price)}


@router.delete("/{alert_id}")
def delete_alert(alert_id: int, svc: AlertService = Depends(get_alert_service)) -> dict:
    return {"ok": svc.delete_alert(alert_id)}
