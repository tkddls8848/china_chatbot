from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SectorDefinition:
    sector_id: str
    sector_name: str
    codes: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class StockUniverseEntry:
    code: str
    name: str
    market: str
    sector_id: str
    sector_name: str
    market_cap_cny: float = 0.0


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value != value:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
