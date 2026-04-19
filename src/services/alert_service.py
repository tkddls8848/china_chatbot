from datetime import datetime

from sqlalchemy.orm import Session

from src.data.akshare_client import AkshareClient
from src.db.models.alert import Alert
from src.db.models.watchlist import Watchlist


class AlertService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._ak = AkshareClient()

    # ── 관심종목 ───────────────────────────────────────────

    def get_watchlist(self) -> list[Watchlist]:
        return self._db.query(Watchlist).all()

    def add_watchlist(self, ticker: str, market: str) -> Watchlist:
        item = Watchlist(ticker=ticker, market=market)
        self._db.add(item)
        self._db.commit()
        self._db.refresh(item)
        return item

    def remove_watchlist(self, ticker: str) -> bool:
        item = self._db.query(Watchlist).filter(Watchlist.ticker == ticker).first()
        if not item:
            return False
        self._db.delete(item)
        self._db.commit()
        return True

    # ── 알림 ───────────────────────────────────────────────

    def get_alerts(self) -> list[Alert]:
        return self._db.query(Alert).filter(Alert.is_active == True).all()

    def create_alert(self, ticker: str, condition: str, price: float) -> Alert:
        alert = Alert(ticker=ticker, condition=condition, price=price)
        self._db.add(alert)
        self._db.commit()
        self._db.refresh(alert)
        return alert

    def delete_alert(self, alert_id: int) -> bool:
        alert = self._db.query(Alert).filter(Alert.id == alert_id).first()
        if not alert:
            return False
        self._db.delete(alert)
        self._db.commit()
        return True

    async def check_price_alerts(self) -> list[dict]:
        active = self._db.query(Alert).filter(Alert.is_active == True).all()
        if not active:
            return []
        df = await self._ak.get_stock_spot()
        price_map: dict[str, float] = {
            str(row.get("代码", "")): float(row.get("最新价", 0) or 0)
            for _, row in df.iterrows()
        }
        triggered = []
        for alert in active:
            current = price_map.get(alert.ticker)
            if current is None:
                continue
            hit = (alert.condition == "above" and current >= float(alert.price)) or \
                  (alert.condition == "below" and current <= float(alert.price))
            if hit:
                alert.is_active = False
                alert.triggered_at = datetime.utcnow()
                triggered.append({"alert": alert, "current_price": current})
        if triggered:
            self._db.commit()
        return triggered
