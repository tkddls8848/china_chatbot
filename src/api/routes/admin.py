from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.config import settings
from src.data.akshare_client import _info_cache, _spot_cache
from src.db.models.alert import Alert
from src.db.models.rss_feed import RssFeed
from src.db.models.watchlist import Watchlist
from src.db.session import get_db
from src.services.market_service import MarketService, _cache as market_cache
from src.services.news_service import NewsService, _cache as news_cache

router = APIRouter()

_token_header = APIKeyHeader(name="X-Admin-Token", auto_error=False)


def require_admin(token: str | None = Depends(_token_header)) -> None:
    if not token or token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")


# ── 상태 ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_status(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> dict:
    feeds_count = db.query(RssFeed).filter(RssFeed.is_active == True).count()
    return {
        "version": "0.5.1",
        "rsshub_base_url": settings.RSSHUB_BASE_URL,
        "feeds_count": feeds_count,
        "cache_ttl_seconds": settings.CACHE_TTL_SECONDS,
        "cache": {
            "market": market_cache.info(),
            "news": news_cache.info(),
            "ak_spot": _spot_cache.info(),
            "ak_info": _info_cache.info(),
        },
    }


# ── 캐시 강제 갱신 ─────────────────────────────────────────────────────────

@router.post("/refresh/index")
async def force_index_refresh(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> dict:
    from datetime import datetime, timezone
    market_cache.clear()
    await MarketService(db).get_all_indices()
    return {"ok": True, "refreshed_at": datetime.now(timezone.utc).isoformat()}


@router.post("/refresh/rss")
async def force_rss_refresh(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> dict:
    from datetime import datetime, timezone
    news_cache.clear()
    await NewsService(db).refresh_cache()
    return {"ok": True, "refreshed_at": datetime.now(timezone.utc).isoformat()}


# ── RSS 피드 관리 (DB 영속) ─────────────────────────────────────────────────

class FeedBody(BaseModel):
    url: str
    label: str = ""
    market_tag: str = "cn"


class FeedDeleteBody(BaseModel):
    url: str


@router.get("/feeds")
async def list_feeds(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> list[dict]:
    rows = db.query(RssFeed).order_by(RssFeed.id).all()
    return [
        {
            "id": r.id,
            "url": r.url,
            "label": r.label,
            "market_tag": r.market_tag,
            "is_active": r.is_active,
            "created_at": str(r.created_at),
        }
        for r in rows
    ]


@router.post("/feeds", status_code=status.HTTP_201_CREATED)
async def add_feed(
    body: FeedBody,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> dict:
    label = body.label.strip() or body.url
    exists = db.query(RssFeed).filter(RssFeed.url == body.url).first()
    if exists:
        if not exists.is_active:
            exists.is_active = True
            exists.label = label
            exists.market_tag = body.market_tag
            db.commit()
            news_cache.clear()
            return {"ok": True, "url": body.url, "label": label, "restored": True}
        raise HTTPException(status_code=409, detail="Feed already exists")
    feed = RssFeed(url=body.url, label=label, market_tag=body.market_tag)
    db.add(feed)
    db.commit()
    news_cache.clear()
    return {"ok": True, "url": body.url, "label": label, "market_tag": body.market_tag}


@router.delete("/feeds")
async def remove_feed(
    body: FeedDeleteBody,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> dict:
    row = db.query(RssFeed).filter(RssFeed.url == body.url).first()
    if not row:
        raise HTTPException(status_code=404, detail="Feed not found")
    db.delete(row)
    db.commit()
    news_cache.clear()
    return {"ok": True, "url": body.url}


@router.patch("/feeds/{feed_id}")
async def toggle_feed(
    feed_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> dict:
    row = db.query(RssFeed).filter(RssFeed.id == feed_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Feed not found")
    row.is_active = not row.is_active
    db.commit()
    news_cache.clear()
    return {"ok": True, "id": feed_id, "is_active": row.is_active}


# ── 관심종목 / 알림 조회 ────────────────────────────────────────────────────

@router.get("/watchlist")
async def list_watchlist(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> list[dict]:
    rows = db.query(Watchlist).order_by(Watchlist.created_at.desc()).all()
    return [{"id": r.id, "ticker": r.ticker, "market": r.market, "created_at": str(r.created_at)} for r in rows]


@router.get("/alerts")
async def list_alerts(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> list[dict]:
    rows = db.query(Alert).order_by(Alert.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "ticker": r.ticker,
            "condition": r.condition,
            "price": float(r.price),
            "is_active": r.is_active,
            "triggered_at": str(r.triggered_at) if r.triggered_at else None,
            "created_at": str(r.created_at),
        }
        for r in rows
    ]
