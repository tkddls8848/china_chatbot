"""읽기 전용 공개 웹.

별도 프로세스로 실행하며 ``data/webpub`` 산출물만 읽는다. 인증과 TLS는 이
프로세스 앞단의 Caddy가 담당한다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from webpub_pages import ABOUT_HTML, INDEX_HTML, RESEARCH_HTML

WEBPUB_DIR = Path(__file__).resolve().parent.parent / "data" / "webpub"


def _read_json(name: str) -> dict[str, Any]:
    try:
        value = json.loads((WEBPUB_DIR / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def build_app() -> FastAPI:
    app = FastAPI(title="Stock Chatbot", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX_HTML

    @app.get("/research", response_class=HTMLResponse)
    def research_page() -> str:
        return RESEARCH_HTML

    @app.get("/about", response_class=HTMLResponse)
    def about_page() -> str:
        return ABOUT_HTML

    @app.get("/api/market")
    def market() -> dict[str, Any]:
        return _read_json("market.json")

    @app.get("/api/research")
    def research() -> dict[str, Any]:
        return _read_json("research.json")

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return _read_json("meta.json")

    @app.get("/market_chart.png")
    def market_chart() -> FileResponse:
        path = WEBPUB_DIR / "market_chart.png"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="시장 산출물이 아직 없습니다.")
        return FileResponse(path, media_type="image/png")

    return app


def main() -> None:
    import uvicorn

    uvicorn.run(
        build_app(),
        host=os.environ.get("WEBPUB_HOST", "127.0.0.1"),
        port=int(os.environ.get("WEBPUB_PORT", "8788")),
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
