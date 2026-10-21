"""Central loader for config.json – single source of truth for all modules.

Cache policy:
- Returns the cached dict when the file's mtime has not changed.
- Reloads and updates the cache when the file is newer.
- On any error (missing file, JSON syntax) logs a warning, retains the last
  valid state, and retries on the next call.  Never poisons the cache with an
  empty dict after a transient failure.
- Returns {} only when no valid config has ever been successfully loaded.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CONFIG_PATH: Path = Path(__file__).parent.parent / "config.json"

_lock = threading.Lock()
_cached: Optional[dict] = None
_cached_mtime: float = -1.0


def get_config() -> dict:
    """Return the current config dict, auto-reloading when the file changes.

    Thread-safe.  The return value is the same dict object on cache hits, so
    callers must not mutate it.
    """
    global _cached, _cached_mtime
    with _lock:
        try:
            mtime = _CONFIG_PATH.stat().st_mtime
        except OSError as exc:
            logger.warning("Cannot stat %s: %s", _CONFIG_PATH, exc)
            return _cached if _cached is not None else {}

        if _cached is not None and mtime == _cached_mtime:
            return _cached

        try:
            new_cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(
                "Cannot load %s: %s – retaining last valid state", _CONFIG_PATH, exc
            )
            # _cached_mtime intentionally NOT updated → retry on next call.
            return _cached if _cached is not None else {}

        _cached = new_cfg
        _cached_mtime = mtime
        return _cached


def get_calibration() -> dict[tuple[int, int], dict]:
    """Return per-sensor calibration keyed by (dev, ch).

    Each value is the full sensor entry from config.json (name, dry_raw,
    wet_raw, …).  Entries missing dev or ch are silently skipped.
    Returns an empty dict when no valid config is available.
    """
    return {
        (int(s["dev"]), int(s["ch"])): s
        for s in get_config().get("sensors", [])
        if "dev" in s and "ch" in s
    }


def _reset_cache() -> None:
    """Reset the module-level cache.  For use in tests only."""
    global _cached, _cached_mtime
    with _lock:
        _cached = None
        _cached_mtime = -1.0
