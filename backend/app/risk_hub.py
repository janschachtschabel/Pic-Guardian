"""Interner Risikospeicher (Option 8) — bestätigt problematische Bilder.

Bewusst schlank als JSON-Datei mit linearem Scan gehalten. Für den Regelbetrieb
mit >100k Einträgen wäre ein BK-Tree / LSH-Index angezeigt — die Schnittstelle
(match_phash / match_sha1 / add) bleibt dabei gleich.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path

_log = logging.getLogger(__name__)


def hashes_for(data: bytes, pil_img=None) -> tuple[str, str | None]:
    """SHA-1 + dHash eines Bilds — dieselben Hashes wie Prüfschritt c05,
    für Review-Bestätigung und Batch-Seeding."""
    sha1 = hashlib.sha1(data).hexdigest()
    phash: str | None = None
    if pil_img is not None:
        try:
            import imagehash

            phash = str(imagehash.dhash(pil_img))
        except Exception:  # noqa: BLE001
            phash = None
    return sha1, phash

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "risk_hub.json"


def _hamming_hex(a: str, b: str) -> int:
    """Hamming-Distanz zweier gleich langer Hex-Hashes. Defensiv: ein ungültiger
    (nicht-hex) Eintrag darf NICHT den gesamten Abgleich per Exception lahmlegen."""
    if len(a) != len(b):
        return 999
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return 999


class RiskHub:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._entries: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload.get("entries", []) if isinstance(payload, dict) else []
        except (ValueError, OSError) as exc:
            # NICHT still leeren — sonst „fails open" (Erkennung wäre unbemerkt aus).
            _log.error(
                "Risikospeicher %s nicht lesbar (%s) — starte mit leerem Speicher, "
                "bitte Datei prüfen.", self.path, exc,
            )
            return []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Atomar schreiben: erst temp, dann os.replace — verhindert Korruption
        # bei Absturz/parallelem Lesen.
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps({"entries": self._entries}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    # -- Abgleich ----------------------------------------------------------
    def match_sha1(self, sha1: str | None) -> dict | None:
        if not sha1:
            return None
        for e in self._snapshot():
            if e.get("sha1") and e["sha1"].lower() == sha1.lower():
                return e
        return None

    def match_phash(self, phash: str | None, max_distance: int = 6) -> dict | None:
        if not phash:
            return None
        best: dict | None = None
        best_d = max_distance + 1
        for e in self._snapshot():
            ep = e.get("phash")
            if not ep:
                continue
            d = _hamming_hex(phash, ep)
            if d < best_d:
                best_d, best = d, {**e, "distance": d}
        return best if best and best_d <= max_distance else None

    def _snapshot(self) -> list[dict]:
        """Konsistente Kopie für Leser (Batch-Threads lesen, /risk-hub schreibt)."""
        with self._lock:
            return list(self._entries)

    # -- Pflege ------------------------------------------------------------
    def add(
        self,
        *,
        phash: str | None = None,
        sha1: str | None = None,
        note: str = "",
        source: str = "manual",
    ) -> dict:
        entry = {"phash": phash, "sha1": sha1, "note": note, "source": source}
        with self._lock:
            self._entries.append(entry)
            self._save()
        return entry

    def remove(self, hash_value: str) -> bool:
        with self._lock:
            before = len(self._entries)
            self._entries = [
                e
                for e in self._entries
                if e.get("phash") != hash_value and e.get("sha1") != hash_value
            ]
            if len(self._entries) != before:
                self._save()
                return True
        return False

    @property
    def size(self) -> int:
        return len(self._entries)
