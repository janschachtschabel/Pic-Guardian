"""Höflichkeits-Throttle für externe APIs (Wikimedia Commons, Openverse).

Thread-sicher — der Batch verarbeitet Nodes im ThreadPool, und ohne Drosselung
würden hunderte externe Requests in schneller Folge die Rate-Limits/Etikette der
freien Dienste verletzen (Wikimedia: seriell + korrekter User-Agent, sonst
IP-Block; Openverse: 100/min Burst, 10.000/Tag, IP-geteilt).

Erzwingt pro Host einen Mindestabstand zwischen Requests. Der pro-Host-Lock
serialisiert konkurrierende Batch-Worker auf denselben Dienst.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from urllib.parse import urlsplit

# Mindestabstand (Sekunden) je Host-Suffix.
_INTERVALS: dict[str, float] = {
    "openverse.org": 0.75,   # ~80/min < 100/min-Burst
    "wikimedia.org": 0.30,   # Commons: seriell/höflich (kein hartes Read-Limit)
    "archive.org": 0.50,     # Wayback Availability API + Snapshot-Abruf
}

_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_next_at: dict[str, float] = {}
_guard = threading.Lock()


def _interval_for(host: str) -> float:
    for suffix, iv in _INTERVALS.items():
        if host == suffix or host.endswith("." + suffix):
            return iv
    return 0.0


def throttle(url: str) -> None:
    """Blockiert, bis der Mindestabstand zum letzten Request an denselben Host
    eingehalten ist. No-op für Hosts ohne konfiguriertes Intervall."""
    host = urlsplit(url).netloc.lower()
    interval = _interval_for(host)
    if interval <= 0:
        return
    with _guard:
        lock = _locks[host]
    with lock:
        now = time.monotonic()
        earliest = _next_at.get(host, 0.0)
        if now < earliest:
            time.sleep(earliest - now)
        _next_at[host] = time.monotonic() + interval
