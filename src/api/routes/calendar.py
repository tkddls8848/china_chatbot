from datetime import date

from fastapi import APIRouter, Depends, Query

from src.api.deps import get_calendar_service
from src.services.calendar_service import CalendarService

router = APIRouter()


@router.get("")
async def get_calendar(
    start: date | None = Query(None),
    end: date | None = Query(None),
    svc: CalendarService = Depends(get_calendar_service),
) -> list[dict]:
    return await svc.get_calendar(start, end)
