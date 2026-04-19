import asyncio
import logging
from datetime import date

import akshare as ak
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class CalendarService:
    def __init__(self, db: Session) -> None:
        self._db = db

    async def get_calendar(self, start: date | None = None, end: date | None = None) -> list[dict]:
        loop = asyncio.get_event_loop()
        results: list[dict] = []

        async def fetch(func, label: str, date_col: str, value_col: str) -> None:
            try:
                df = await loop.run_in_executor(None, func)
                for _, row in df.tail(6).iterrows():
                    results.append({
                        "type": label,
                        "date": str(row[date_col]),
                        "value": str(row[value_col]),
                    })
            except Exception as e:
                logger.warning("%s 조회 실패: %s", label, e)

        await asyncio.gather(
            fetch(ak.macro_china_cpi_monthly,        "CPI (소비자물가)",   "日期", "今值"),
            fetch(ak.macro_china_pmi_manufacturing,  "PMI 제조업",         "日期", "今值"),
        )

        results.sort(key=lambda x: x["date"], reverse=True)
        return results
