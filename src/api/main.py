from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import admin, alert, calendar, market, news, stock, watchlist
from src.config import settings
from src.data.rss_client import _build_registry
from src.db.models.rss_feed import RssFeed
from src.db.session import SessionLocal, create_tables


def _seed_feeds() -> None:
    with SessionLocal() as db:
        if db.query(RssFeed).count() > 0:
            return
        for feed in _build_registry():
            db.add(RssFeed(url=feed["url"], label=feed["label"], market_tag=feed["market_tag"]))
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    _seed_feeds()
    yield


app = FastAPI(title="China Market Bot", version="0.5.1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/admin")
async def admin_redirect() -> RedirectResponse:
    return RedirectResponse(url="/admin.html")


app.include_router(market.router,    prefix="/api/market",    tags=["market"])
app.include_router(stock.router,     prefix="/api/stock",     tags=["stock"])
app.include_router(news.router,      prefix="/api/news",      tags=["news"])
app.include_router(calendar.router,  prefix="/api/calendar",  tags=["calendar"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])
app.include_router(alert.router,     prefix="/api/alert",     tags=["alert"])
app.include_router(admin.router,     prefix="/api/admin",     tags=["admin"])

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
