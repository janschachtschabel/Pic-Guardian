"""Prüfschritt 7 — Wikimedia Commons SHA-1-Lookup (Option 9, extern, Opt-in).

Positivnachweis: findet ein bit-identisches Bild in Wikimedia Commons und
übernimmt dessen Lizenz aus den extmetadata. Ein Treffer ist ein starkes
GREEN-Signal inkl. ableitbarer Attribution.

Externer Dienst -> nur mit Opt-in (überträgt den SHA-1-Hash, nicht das Bild;
der Hash ist bereits anonym — trotzdem als extern behandelt).
"""

from __future__ import annotations

import hashlib

import httpx

from ..config import SETTINGS
from ..rate_limit import throttle
from ..schemas import CheckSignal, SignalStatus, Verdict
from ..wordlists import normalize_license_uri
from .base import BaseCheck, CheckContext

_API = "https://commons.wikimedia.org/w/api.php"


class CommonsCheck(BaseCheck):
    id = "commons_sha1"
    label = "Wikimedia Commons (SHA-1-Abgleich)"
    category = "match"
    external = True

    def execute(self, ctx: CheckContext) -> CheckSignal:
        sha1 = hashlib.sha1(ctx.image.data).hexdigest()
        headers = {"User-Agent": SETTINGS.user_agent}
        with httpx.Client(timeout=SETTINGS.http_timeout, headers=headers) as client:
            throttle(_API)
            r = client.get(
                _API,
                params={
                    "action": "query",
                    "list": "allimages",
                    "aisha1": sha1,
                    "ailimit": "1",
                    "format": "json",
                    "maxlag": "5",  # bei hoher Serverlast höflich zurücktreten
                },
            )
            if r.status_code == 429:
                return self.signal(
                    status=SignalStatus.UNAVAILABLE,
                    summary="Wikimedia-Rate-Limit (429) — später erneut prüfen.",
                    data={"sha1": sha1},
                )
            r.raise_for_status()
            body = r.json()
            # maxlag/Soft-Fehler kommt als 200 + error-Body -> NICHT als "kein
            # Treffer" (NEUTRAL) fehldeuten, sondern als "nicht verfügbar".
            if body.get("error"):
                return self.signal(
                    status=SignalStatus.UNAVAILABLE,
                    summary="Wikimedia vorübergehend nicht verfügbar (maxlag) — "
                    "später erneut.",
                    data={"sha1": sha1},
                )
            images = (body.get("query", {}).get("allimages")) or []
            if not images:
                return self.signal(
                    verdict=Verdict.NEUTRAL,
                    summary="Kein bit-identisches Bild in Wikimedia Commons "
                    "(SHA-1 findet nur exakte Kopien).",
                    evidence=[f"SHA-1: {sha1}"],
                    data={"sha1": sha1},
                )

            title = images[0].get("title", "")
            meta = self._license_meta(client, title)

        lic_short = meta.get("LicenseShortName", "")
        lic_url = normalize_license_uri(meta.get("LicenseUrl", "")) or meta.get("LicenseUrl")
        artist = _strip_html(meta.get("Artist", ""))
        data = {"sha1": sha1}
        if lic_url:
            data["license_uri"] = lic_url
        if lic_short:
            data["license_label"] = lic_short
        if artist:
            data["creator"] = artist
        evidence = [f"Commons: {title}", f"Lizenz: {lic_short or '—'}"]
        if artist:
            evidence.append(f"Urheber: {artist}")

        return self.signal(
            verdict=Verdict.GREEN,
            confidence=0.9,
            summary=f"Bit-identisch in Wikimedia Commons ({lic_short or 'Lizenz siehe Commons'}).",
            evidence=evidence,
            data=data,
        )

    @staticmethod
    def _license_meta(client: httpx.Client, title: str) -> dict:
        try:
            throttle(_API)
            r = client.get(
                _API,
                params={
                    "action": "query",
                    "titles": title,
                    "prop": "imageinfo",
                    "iiprop": "extmetadata",
                    "format": "json",
                    "maxlag": "5",
                },
            )
            r.raise_for_status()
            pages = r.json().get("query", {}).get("pages", {})
            for page in pages.values():
                info = (page.get("imageinfo") or [{}])[0]
                ext = info.get("extmetadata") or {}
                return {k: v.get("value", "") for k, v in ext.items()}
        except Exception:  # noqa: BLE001
            pass
        return {}


def _strip_html(text: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", text or "").strip()
