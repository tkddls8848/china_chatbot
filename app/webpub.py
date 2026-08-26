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
        return _INDEX_HTML

    @app.get("/research", response_class=HTMLResponse)
    def research_page() -> str:
        return _RESEARCH_HTML

    @app.get("/about", response_class=HTMLResponse)
    def about_page() -> str:
        return _ABOUT_HTML

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


_STYLE = """
<style>
:root { color-scheme: light dark; font-family: system-ui, sans-serif; }
body { max-width: 980px; margin: auto; padding: 24px; background:#f7f8fa; color:#18212f; }
header { display:flex; justify-content:space-between; align-items:center; gap:16px; margin-bottom:24px; }
nav a { color:inherit; margin-left:14px; } .card { background:#fff; border:1px solid #e5e7eb;
border-radius:12px; padding:20px; margin:16px 0; } img { width:100%; height:auto; }
.muted { color:#64748b; font-size:.9rem; } pre { white-space:pre-wrap; overflow-wrap:anywhere; }
table { border-collapse:collapse; width:100%; } th,td { text-align:left; padding:8px; border-bottom:1px solid #e5e7eb; }
@media (prefers-color-scheme: dark) { body { background:#111827; color:#e5e7eb; } .card {background:#1f2937;border-color:#374151;} }
</style>
"""

_HEADER = """<header><div><strong>Stock Chatbot</strong><div class='muted'>읽기 전용 시장 관측</div></div>
<nav><a href='/'>시장</a><a href='/research'>리서치</a><a href='/about'>정보</a></nav></header>"""

_INDEX_HTML = f"""<!doctype html><html lang='ko'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>시장 컨센서스</title>{_STYLE}<body>{_HEADER}
<main><div class='card'><h1>시장 컨센서스</h1><p class='muted' id='time'>산출물을 불러오는 중…</p><img src='/market_chart.png' alt='국가별 시장 감성 차트' onerror="this.replaceWith(document.createTextNode('시장 차트가 아직 생성되지 않았습니다.'))"></div>
<div class='card'><h2>국가별 수치</h2><div id='markets'>산출물이 아직 없습니다.</div></div><p class='muted'>뉴스 감성 관측치이며 투자 조언이나 매매 신호가 아닙니다.</p></main>
<script>fetch('/api/market').then(r=>r.json()).then(d=>{{document.querySelector('#time').textContent=d.generated_at?`기준 시각: ${{d.generated_at}}`:'산출물이 아직 없습니다.';let m=d.markets||{{}};let rows=Object.entries(m).sort((a,b)=>(b[1].avg_sentiment||0)-(a[1].avg_sentiment||0)).map(([k,v])=>`<tr><td>${{k}}</td><td>${{Number(v.avg_sentiment||0).toFixed(2)}}</td><td>${{v.count||0}}</td></tr>`).join('');if(rows)document.querySelector('#markets').innerHTML=`<table><tr><th>시장</th><th>감성</th><th>기사 수</th></tr>${{rows}}</table>`}});</script></body></html>"""

_RESEARCH_HTML = f"""<!doctype html><html lang='ko'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>리서치</title>{_STYLE}<body>{_HEADER}
<main><div class='card'><h1>리서치</h1><p id='sight' class='muted'>산출물을 불러오는 중…</p><pre id='result'>최근 분석이 없습니다.</pre></div><p class='muted'>리서치는 텔레그램에서 실행하며, 이 페이지는 마지막 결과만 표시합니다.</p></main>
<script>fetch('/api/research').then(r=>r.json()).then(d=>{{document.querySelector('#sight').textContent=d.sight?`주제: ${{d.sight}} · 기준 시각: ${{d.generated_at||'-'}}`:'저장된 리서치 주제가 없습니다.';document.querySelector('#result').textContent=d.last_result?JSON.stringify(d.last_result,null,2):'최근 분석이 없습니다.'}});</script></body></html>"""

_ABOUT_HTML = f"""<!doctype html><html lang='ko'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>정보</title>{_STYLE}<body>{_HEADER}
<main><div class='card'><h1>정보</h1><p>이 사이트는 개인 운영 봇이 생성한 마지막 시장 관측·리서치 산출물을 읽기 전용으로 보여 줍니다.</p><p>데이터는 갱신 시각 기준이며 투자 조언이나 매매 추천이 아닙니다.</p></div></main></body></html>"""


if __name__ == "__main__":
    main()
