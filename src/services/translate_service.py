import hashlib
import logging

import httpx
from sqlalchemy.orm import Session

from src.config import settings
from src.db.models.translation import Translation

logger = logging.getLogger(__name__)

_SKIP_SOURCES = {"SCMP", "Reuters"}


def _url_hash(url: str, suffix: str = "") -> str:
    return hashlib.sha256((url + suffix).encode()).hexdigest()[:64]


def _has_chinese(text: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in text)


def _load_translations(db: Session, url_hashes: list[str]) -> dict[str, str]:
    if not url_hashes:
        return {}
    rows = db.query(Translation).filter(Translation.url_hash.in_(url_hashes)).all()
    return {r.url_hash: r.translated for r in rows}


def enrich_with_translations(db: Session, items: list[dict]) -> list[dict]:
    if not settings.TRANSLATE_ENABLED:
        return items
    title_hashes = [_url_hash(i["link"]) for i in items if i.get("link")]
    desc_hashes = [_url_hash(i["link"], ":desc") for i in items if i.get("link")]
    trans_map = _load_translations(db, title_hashes + desc_hashes)
    for item in items:
        link = item.get("link", "")
        item["title_ko"] = trans_map.get(_url_hash(link), "")
        item["description_ko"] = trans_map.get(_url_hash(link, ":desc"), "")
    return items


_MAX_DESC_CHARS = 400


async def _call_ollama(text: str, is_body: bool = False) -> str:
    system = (
        "You are a professional financial news translator. "
        "Translate Chinese text into natural, accurate Korean. "
        "Output only the Korean translation. No explanations."
    )
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{settings.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": settings.TRANSLATE_MODEL,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Translate to Korean:\n{text}"},
                ],
            },
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()


async def translate_pending(db: Session, items: list[dict]) -> int:
    if not settings.TRANSLATE_ENABLED:
        return 0

    candidates = [
        i for i in items
        if i.get("link")
        and i.get("source") not in _SKIP_SOURCES
        and _has_chinese(i.get("title", ""))
    ]
    if not candidates:
        return 0

    all_hashes = []
    for i in candidates:
        all_hashes.append(_url_hash(i["link"]))
        all_hashes.append(_url_hash(i["link"], ":desc"))

    existing = {
        r.url_hash
        for r in db.query(Translation.url_hash)
        .filter(Translation.url_hash.in_(all_hashes))
        .all()
    }

    count = 0
    batch_remaining = settings.TRANSLATE_BATCH_SIZE

    for item in candidates:
        if batch_remaining <= 0:
            break
        link = item.get("link", "")
        title = item.get("title", "")
        description = item.get("description", "")

        title_hash = _url_hash(link)
        desc_hash = _url_hash(link, ":desc")

        if title_hash not in existing:
            try:
                translated = await _call_ollama(title)
                if translated:
                    db.add(Translation(url_hash=title_hash, original=title, translated=translated))
                    count += 1
                    batch_remaining -= 1
            except Exception as e:
                logger.warning("제목 번역 실패 [%s]: %s: %s", title[:30], type(e).__name__, e)

        if description and _has_chinese(description) and desc_hash not in existing and batch_remaining > 0:
            try:
                translated = await _call_ollama(description[:_MAX_DESC_CHARS], is_body=True)
                if translated:
                    db.add(Translation(url_hash=desc_hash, original=description, translated=translated))
                    count += 1
                    batch_remaining -= 1
            except Exception as e:
                logger.warning("본문 번역 실패 [%s]: %s: %s", title[:30], type(e).__name__, e)

    if count:
        db.commit()
        logger.info("번역 완료: %d건", count)
    return count
