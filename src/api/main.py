from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.routes import alert, calendar, market, news, stock, watchlist
from src.db.session import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(title="China Market Bot", version="0.4.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


app.include_router(market.router,    prefix="/api/market",    tags=["market"])
app.include_router(stock.router,     prefix="/api/stock",     tags=["stock"])
app.include_router(news.router,      prefix="/api/news",      tags=["news"])
app.include_router(calendar.router,  prefix="/api/calendar",  tags=["calendar"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])
app.include_router(alert.router,     prefix="/api/alert",     tags=["alert"])

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
