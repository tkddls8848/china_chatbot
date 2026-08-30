"""Compact manifest와 byte-addressed detail JSONL generation 저장."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from core.storage import write_json_atomic

MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_SHARD_BYTES = 16 * 1024 * 1024


def _encoded(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _validate_accounting(manifest: dict[str, Any]) -> None:
    accounting = manifest.get("accounting", {})
    fetched = int(accounting.get("fetched_record_count", 0))
    unique = int(accounting.get("unique_event_count", 0))
    duplicate = int(accounting.get("duplicate_event_count", 0))
    opened = int(accounting.get("open_event_count", 0))
    non_open = int(accounting.get("excluded_non_open_count", 0))
    ready = int(accounting.get("consensus_ready_event_count", 0))
    unavailable = int(accounting.get("unavailable_event_count", 0))
    if fetched != unique + duplicate:
        raise ValueError("fetched accounting mismatch")
    if unique != opened + non_open:
        raise ValueError("unique accounting mismatch")
    if opened != ready + unavailable:
        raise ValueError("open accounting mismatch")
    if sum(manifest.get("category_counts", {}).values()) != opened:
        raise ValueError("category accounting mismatch")


def write_generation(
    root: Path,
    manifest: dict[str, Any],
    rows: Iterable[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    generation_id = str(manifest["generation_id"])
    generation_dir = root / "generations" / generation_id
    generation_dir.mkdir(parents=True, exist_ok=False)
    events: list[dict[str, Any]] = []
    shard_index = -1
    shard_handle = None
    shard_size = 0
    try:
        for compact, detail in rows:
            detail = {**detail, "generation_id": generation_id}
            data = _encoded(detail)
            if len(data) > MAX_SHARD_BYTES:
                raise ValueError(f"detail row exceeds shard limit: {compact['id']}")
            if shard_handle is None or shard_size + len(data) > MAX_SHARD_BYTES:
                if shard_handle is not None:
                    shard_handle.flush()
                    os.fsync(shard_handle.fileno())
                    shard_handle.close()
                shard_index += 1
                shard_size = 0
                shard_handle = open(generation_dir / f"details-{shard_index:03d}.jsonl", "wb")
            offset = shard_size
            shard_handle.write(data)
            shard_size += len(data)
            events.append(
                {
                    **compact,
                    "generation_id": generation_id,
                    "detail_ref": {
                        "shard": f"details-{shard_index:03d}.jsonl",
                        "offset": offset,
                        "length": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    },
                }
            )
        if shard_handle is not None:
            shard_handle.flush()
            os.fsync(shard_handle.fileno())
            shard_handle.close()
            shard_handle = None
        full_manifest = {**manifest, "events": events, "detail_shard_count": shard_index + 1}
        _validate_accounting(full_manifest)
        manifest_data = json.dumps(full_manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(manifest_data) > MAX_MANIFEST_BYTES:
            raise ValueError(f"manifest exceeds {MAX_MANIFEST_BYTES} bytes")
        write_json_atomic(generation_dir / "manifest.json", full_manifest)
        # current는 마지막에만 바꾼다. 앞 단계 실패 시 last-good이 그대로 남는다.
        write_json_atomic(root / "current.json", full_manifest)
        return full_manifest
    except BaseException:
        if shard_handle is not None:
            shard_handle.close()
        raise


def read_detail(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    ref = event["detail_ref"]
    path = root / "generations" / str(event["generation_id"]) / ref["shard"]
    with open(path, "rb") as handle:
        handle.seek(int(ref["offset"]))
        data = handle.read(int(ref["length"]))
    if hashlib.sha256(data).hexdigest() != ref["sha256"]:
        raise ValueError("detail hash mismatch")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("detail is not an object")
    return value
