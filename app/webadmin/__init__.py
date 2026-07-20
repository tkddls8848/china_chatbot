"""봇 프로세스에 내장되는 관리용 웹 대시보드.

텔레그램 봇과 같은 asyncio 이벤트 루프에서 FastAPI(uvicorn)를 백그라운드
태스크로 구동한다. 관심종목·뉴스·리서치·신호 상태를 기존 `app.bot_data`
서비스와 `data/<기능키>/*.json`을 그대로 재사용해 조회·관리한다.

봇을 제어하므로 항상 인증(HTTP Basic) 뒤에 두며, 기본은 로컬 바인딩이다.
"""

from webadmin.server import start_web_admin, stop_web_admin

__all__ = ["start_web_admin", "stop_web_admin"]
