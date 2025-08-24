"""Lightweight instrumentation utilities for timing function execution.

Creates structured NDJSON logs (one JSON per line) with fields:
  timestamp_start, timestamp_end, duration_ms, func, module, request_id, ok, error

The request_id is a correlation ID for a high-level fetch/process call.
Use new_request_id() at the start of a logical API/request handling flow.

Environment variables:
  PERF_LOG_FILE: path to log file (default: perf.log)
  PERF_LOG_DISABLE: if set to a truthy value, disables timing logs.
"""
from __future__ import annotations

import os
import json
import time
import uuid
import threading
import functools
import contextvars
from datetime import datetime, timezone
from typing import Callable, Any, Optional

_req_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("request_id", default=None)
_lock = threading.Lock()
_log_path = os.getenv("PERF_LOG_FILE", "perf.log")
_disabled = os.getenv("PERF_LOG_DISABLE", "").lower() in {"1", "true", "yes", "on"}


def get_request_id() -> Optional[str]:
    return _req_id_var.get()


def set_request_id(rid: Optional[str]) -> Optional[str]:
    return _req_id_var.set(rid)


def new_request_id() -> str:
    rid = uuid.uuid4().hex
    set_request_id(rid)
    return rid


def _write_line(obj: dict):
    if _disabled:
        return
    try:
        line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return
    try:
        with _lock:
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        # Silencioso para não quebrar fluxo principal.
        pass


def timed(func: Callable) -> Callable:
    """Decorator que registra tempo de execução em arquivo NDJSON.

    Mantém assinatura (functools.wraps). Em caso de exceção, ok=False e campo error.
    """
    if getattr(func, "__name__", "").startswith("_<"):
        return func  # ignore internal dunder-like

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if _disabled:
            return func(*args, **kwargs)
        start_perf = time.perf_counter()
        start_ts = datetime.now(timezone.utc)
        rid = get_request_id()
        ok = True
        err_txt = None
        try:
            return func(*args, **kwargs)
        except Exception as e:  # pragma: no cover - logging path
            ok = False
            err_txt = f"{type(e).__name__}:{str(e)[:400]}"
            raise
        finally:
            end_ts = datetime.now(timezone.utc)
            duration_ms = (time.perf_counter() - start_perf) * 1000.0
            rec = {
                "timestamp_start": start_ts.isoformat(),
                "timestamp_end": end_ts.isoformat(),
                "duration_ms": round(duration_ms, 3),
                "func": func.__name__,
                "module": getattr(func, "__module__", None),
                "request_id": rid,
                "ok": ok,
            }
            if err_txt:
                rec["error"] = err_txt
            _write_line(rec)
    return wrapper


__all__ = [
    "timed",
    "new_request_id",
    "get_request_id",
    "set_request_id",
]
