from pathlib import Path
from typing import Any

from momentum.models import SectorDefinition, StockUniverseEntry
from momentum.store import MomentumStore
from stock_db import StockDatabase


def _normalize_code(value: Any) -> str:
    code = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
    if not code:
        return ""
    return code.zfill(5) if len(code) <= 5 else code.zfill(6)


def load_sector_definitions(store: MomentumStore) -> list[SectorDefinition]:
    raw = store.read_json(store.sector_map_file, [])
    sectors: list[SectorDefinition] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        sector_id = str(item.get("sector_id") or "").strip()
        sector_name = str(item.get("sector_name") or sector_id).strip()
        codes = tuple(
            code for raw_code in item.get("codes", []) if (code := _normalize_code(raw_code))
        )
        keywords = tuple(str(x).strip() for x in item.get("keywords", []) if str(x).strip())
        if sector_id and sector_name and codes:
            sectors.append(SectorDefinition(sector_id, sector_name, codes, keywords))
    return sectors


def build_universe(
    stock_db: StockDatabase,
    sectors: list[SectorDefinition],
) -> list[StockUniverseEntry]:
    by_code = {
        str(item.get("code") or ""): item
        for item in stock_db.get_candidate_universe()
        if str(item.get("code") or "")
    }
    universe: list[StockUniverseEntry] = []
    seen: set[tuple[str, str]] = set()
    for sector in sectors:
        for code in sector.codes:
            key = (sector.sector_id, code)
            if key in seen:
                continue
            seen.add(key)
            stock = by_code.get(code, {})
            name = (
                str(stock.get("display_name") or "").strip()
                or str(stock.get("cn_name") or "").strip()
                or code
            )
            market = str(stock.get("market") or "")
            universe.append(
                StockUniverseEntry(
                    code=code,
                    name=name,
                    market=market,
                    sector_id=sector.sector_id,
                    sector_name=sector.sector_name,
                )
            )
    return universe
