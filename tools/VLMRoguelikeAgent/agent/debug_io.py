"""Optional request/response tracing for VLM decisions."""
from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("vlm-agent.trace")

_enabled = os.getenv("VLM_TRACE", "0") == "1" or os.getenv("VLM_INSPECT", "0") == "1"
_out_dir = Path(os.getenv("VLM_TRACE_DIR", "trace"))
_counter = 0
_lock = threading.Lock()
_events: list[dict[str, Any]] = []


def configure(*, enabled: bool | None = None, out_dir: str | None = None) -> None:
    global _enabled, _out_dir
    if enabled is not None:
        _enabled = enabled
    if out_dir:
        _out_dir = Path(out_dir)
    if _enabled:
        _out_dir.mkdir(parents=True, exist_ok=True)
        log.info("VLM trace enabled: %s", _out_dir.resolve())


def enabled() -> bool:
    return _enabled


def list_events() -> list[dict[str, Any]]:
    with _lock:
        return [dict(item) for item in _events]


def get_event(event_id: int) -> dict[str, Any] | None:
    with _lock:
        for item in _events:
            if item.get("id") == event_id:
                return dict(item)
    return None


def read_event_detail(event_id: int) -> dict[str, Any] | None:
    event = get_event(event_id)
    if not event:
        return None
    req_dir = Path(str(event["dir"]))
    detail = dict(event)
    for name in ("request", "raw_decision", "decision"):
        path = req_dir / f"{name}.json"
        if path.exists():
            detail[name] = json.loads(path.read_text(encoding="utf-8"))
    for name in ("user", "system"):
        path = req_dir / f"{name}.txt"
        detail[name] = path.read_text(encoding="utf-8") if path.exists() else ""
    return detail


def screenshot_path(event_id: int, index: int) -> Path | None:
    event = get_event(event_id)
    if not event:
        return None
    req_dir = Path(str(event["dir"]))
    path = req_dir / f"screenshot-{index}.png"
    if path.exists() and path.is_file():
        return path
    return None


def _next_dir(endpoint: str, session_id: str) -> Path:
    global _counter
    with _lock:
        _counter += 1
        seq = _counter
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_endpoint = endpoint.strip("/").replace("/", "_") or "decision"
    safe_session = session_id.replace("/", "_")[:12] or "no-session"
    return _out_dir / f"{seq:04d}-{stamp}-{safe_endpoint}-{safe_session}"


def _remember_event(event: dict[str, Any]) -> None:
    with _lock:
        _events.append(event)
        del _events[:-200]


def _json_default(value: Any) -> str:
    return repr(value)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def _write_screenshots(req_dir: Path, screenshots: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, image_b64 in enumerate(screenshots):
        record: dict[str, Any] = {
            "index": index,
            "base64_chars": len(image_b64),
        }
        if not image_b64:
            record["file"] = None
            records.append(record)
            continue
        try:
            data = base64.b64decode(image_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            record["decode_error"] = str(exc)
            records.append(record)
            continue
        image_path = req_dir / f"screenshot-{index}.png"
        image_path.write_bytes(data)
        record["file"] = image_path.name
        record["bytes"] = len(data)
        records.append(record)
    return records


def trace_decision(
    *,
    endpoint: str,
    session_id: str,
    context: dict[str, Any],
    screenshots: list[str],
    user_text: str,
    system_text: str,
    raw_decision: Any,
    decision: dict[str, Any],
) -> None:
    if not _enabled:
        return

    req_dir = _next_dir(endpoint, session_id)
    req_dir.mkdir(parents=True, exist_ok=True)
    screenshot_records = _write_screenshots(req_dir, screenshots)

    _write_json(
        req_dir / "request.json",
        {
            "endpoint": endpoint,
            "session_id": session_id,
            "context": context,
            "screenshots": screenshot_records,
        },
    )
    (req_dir / "user.txt").write_text(user_text, encoding="utf-8")
    if system_text:
        (req_dir / "system.txt").write_text(system_text, encoding="utf-8")
    _write_json(req_dir / "raw_decision.json", raw_decision)
    _write_json(req_dir / "decision.json", decision)

    log.info(
        "VLM INPUT %s session=%s screenshots=%d context=%s",
        endpoint,
        session_id,
        len(screenshots),
        json.dumps(context, ensure_ascii=False, default=_json_default),
    )
    log.info(
        "VLM OUTPUT %s action=%s confidence=%.2f dir=%s",
        endpoint,
        decision.get("action"),
        float(decision.get("confidence", 0) or 0),
        req_dir,
    )
    _remember_event(
        {
            "id": int(req_dir.name.split("-", 1)[0]),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "endpoint": endpoint,
            "session_id": session_id,
            "action": decision.get("action"),
            "confidence": float(decision.get("confidence", 0) or 0),
            "dir": str(req_dir),
            "screenshots": screenshot_records,
        }
    )
