"""Prüfschritt — Openverse CC-Katalog-Recherche (Option 9, extern, Opt-in).

Openverse bietet keinen Reverse-Image-/Hash-Lookup, daher ist dies bewusst ein
INFO-Check (Recherche-Hilfe, kein Ampel-Einfluss): Suche nach dem extrahierten
Urheber/Titel im >800-Mio.-CC-Bestand. Ein Treffer belegt NICHT, dass das
geprüfte Bild dieses Werk ist — er ist ein Startpunkt für die Redaktion.
"""

from __future__ import annotations

import re

from ..config import SETTINGS
from ..rate_limit import throttle
from ..schemas import CheckSignal, SignalStatus, Verdict
from .base import BaseCheck, CheckContext

import httpx

_API = "https://api.openverse.org/v1/images/"


def _clean_name(fn: str | None) -> str | None:
    if not fn:
        return None
    stem = fn.rsplit(".", 1)[0]
    stem = re.sub(r"[-_]+", " ", stem)
    stem = re.sub(r"\b(img|dsc|dscf|photo|foto|image|bild|screenshot|scan)\b", " ", stem, flags=re.I)
    stem = re.sub(r"\d+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem if len(stem) >= 4 else None


class OpenverseCheck(BaseCheck):
    id = "openverse"
    label = "Openverse (CC-Katalog-Recherche)"
    category = "match"
    external = True

    def execute(self, ctx: CheckContext) -> CheckSignal:
        query = (
            ctx.extracted("creator")
            or ctx.extracted("credit_text")
            or _clean_name(ctx.image.filename)
        )
        if not query:
            return self.signal(
                verdict=Verdict.NEUTRAL,
                summary="Kein Urheber/Titel als Suchbegriff verfügbar — Openverse "
                "übersprungen.",
            )
        query = query[:120]

        with httpx.Client(timeout=SETTINGS.http_timeout, headers={"User-Agent": SETTINGS.user_agent}) as client:
            throttle(_API)
            r = client.get(_API, params={"q": query, "page_size": 5})
            if r.status_code in (401, 429):
                return self.signal(
                    status=SignalStatus.UNAVAILABLE,
                    summary="Openverse-Limit erreicht (429/401) — später erneut "
                    "oder mit registriertem Token.",
                )
            r.raise_for_status()
            results = (r.json().get("results")) or []

        if not results:
            return self.signal(
                verdict=Verdict.NEUTRAL,
                summary=f"Keine Openverse-Treffer für '{query}'.",
            )

        evidence = [
            f"{res.get('title', '?')} — {res.get('license', '?')} "
            f"{(res.get('license_version') or '')} · {res.get('foreign_landing_url', '')}"
            for res in results[:5]
        ]
        return self.signal(
            verdict=Verdict.INFO,
            confidence=0.0,
            summary=f"{len(results)} mögliche CC-Werke bei Openverse zu '{query}' "
            "(Recherche-Hilfe, kein Beweis für dieses Bild).",
            evidence=evidence,
        )
