import math
import os
import threading
import time

# Per-IP sliding-window rate limiter. Two independent one-minute windows per
# client: reads (GET/HEAD and any non-write method) and writes (POST/PUT/DELETE).
# State lives in process memory, matching the single-process model — counts are
# not shared across instances. An X-Forwarded-For header is never consulted; the
# peer address of the connection is the only trusted source. The server is
# threaded, so all access to the shared state is guarded by a lock.

_WINDOW_SECONDS = 60
_WRITE_METHODS = frozenset(("POST", "PUT", "DELETE"))


def _limit_from_env(name, fallback):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return fallback
    try:
        value = int(raw)
    except ValueError:
        return fallback
    return value if value > 0 else fallback


_READ_LIMIT = _limit_from_env("RATE_LIMIT_READ_PER_MINUTE", 600)
_WRITE_LIMIT = _limit_from_env("RATE_LIMIT_WRITE_PER_MINUTE", 60)

# ip -> {"read": [timestamps], "write": [timestamps]} still within the window.
_hits = {}
_lock = threading.Lock()
_last_sweep = 0.0


def _prune(stamps, cutoff):
    i = 0
    n = len(stamps)
    while i < n and stamps[i] <= cutoff:
        i += 1
    if i > 0:
        del stamps[:i]


def _sweep(now, cutoff):
    # Drop aged-out timestamps across all clients and forget idle ones, so memory
    # stays bounded by the clients active in the last window. Runs at most once
    # per window, piggybacked on a request under the lock — no background thread.
    global _last_sweep
    if now - _last_sweep < _WINDOW_SECONDS:
        return
    _last_sweep = now
    for ip in list(_hits.keys()):
        entry = _hits[ip]
        _prune(entry["read"], cutoff)
        _prune(entry["write"], cutoff)
        if not entry["read"] and not entry["write"]:
            del _hits[ip]


def check(ip, method):
    """Records a request from ip with the given method. Returns None when the
    request is within its bucket's limit, otherwise the whole seconds until the
    oldest in-window request expires (at least 1) — the Retry-After value."""
    bucket = "write" if method in _WRITE_METHODS else "read"
    limit = _WRITE_LIMIT if bucket == "write" else _READ_LIMIT
    now = time.time()
    cutoff = now - _WINDOW_SECONDS
    with _lock:
        _sweep(now, cutoff)
        entry = _hits.get(ip)
        if entry is None:
            entry = {"read": [], "write": []}
            _hits[ip] = entry
        stamps = entry[bucket]
        _prune(stamps, cutoff)
        if len(stamps) >= limit:
            return max(1, math.ceil(stamps[0] + _WINDOW_SECONDS - now))
        stamps.append(now)
        return None
