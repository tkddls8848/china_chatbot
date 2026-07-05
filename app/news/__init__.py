from news.registry import NewsSourceRegistry, SourceSpec, build_source_specs
from news.sources import (
    GlobalArticle,
    fetch_cls_raw,
    fetch_futu_raw,
    fetch_stock_news_raw,
)

__all__ = [
    "GlobalArticle",
    "NewsSourceRegistry",
    "SourceSpec",
    "build_source_specs",
    "fetch_cls_raw",
    "fetch_futu_raw",
    "fetch_stock_news_raw",
]
