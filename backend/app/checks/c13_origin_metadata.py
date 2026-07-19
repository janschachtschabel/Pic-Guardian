"""Prüfschritt — Metadaten des ORIGINALBILDS von der Fundseite (Option 5 auf dem
un-re-gehosteten Bild).

Die WLO-Vorschau (`ctx.image`) ist eine re-encodierte Kopie, deren EXIF/IPTC/XMP
beim CMS-Resizing verworfen wurde → die Metadaten-Prüfung darauf ist fast immer
leer. Das Bild auf der **Fundseite** (`<img src>`) ist eine Stufe näher am
Original und trägt häufiger noch Rechte-Metadaten. Dieser Check identifiziert das
Fundseiten-Bild (Dateiname-Abgleich, sonst og:image), lädt es und wertet dessen
Metadaten mit derselben Logik wie c03 aus.

Opt-in (`BILDCHECK_FETCH_ORIGIN=1`) — kostet einen zusätzlichen Download pro Node;
für die Ingestion/Erschließung sinnvoll, im Massen-Batch standardmäßig aus.
Übersprungen, wenn ein früherer Check das Bild bereits als Agentur/ROT erkannt hat.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..config import SETTINGS
from ..image_source import ImageLoadError, load_from_url
from ..schemas import SignalStatus, Verdict
from .base import BaseCheck, CheckContext
from .c03_embedded_metadata import classify_metadata, extract_metadata

_OG_IMAGE_PROPS = ("og:image", "og:image:secure_url", "og:image:url", "twitter:image")


def _basename(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("?")[0].lower()


def find_origin_url(html: str, target: str, page_url: str) -> str | None:
    """Ermittelt die URL des Originalbilds auf der Fundseite: exakter Dateiname-
    Abgleich zum geprüften Bild, sonst das og:image (Hauptbild). Gibt eine
    absolute URL zurück oder None, wenn nichts eindeutig zuzuordnen ist."""
    soup = BeautifulSoup(html, "lxml")
    candidates: list[str] = []
    for img in soup.find_all("img"):
        for attr in ("src", "data-src"):
            if img.get(attr):
                candidates.append(img[attr])
        for attr in ("srcset", "data-srcset"):
            if img.get(attr):
                for part in img[attr].split(","):
                    u = part.strip().split(" ")[0].strip()
                    if u:
                        candidates.append(u)

    if target and len(target) > 4:
        for u in candidates:
            if _basename(u) == target:
                return urljoin(page_url, u)

    for meta in soup.find_all("meta"):
        prop = (meta.get("property") or meta.get("name") or "").lower()
        if prop in _OG_IMAGE_PROPS and meta.get("content"):
            return urljoin(page_url, meta["content"])
    return None


class OriginMetadataCheck(BaseCheck):
    id = "origin_metadata"
    label = "Metadaten des Originalbilds (Fundseite)"
    category = "file"

    def applies(self, ctx: CheckContext) -> bool:
        if not SETTINGS.fetch_origin_image:
            return False
        if not (ctx.image.page_html and ctx.image.source_page):
            return False
        # Kein Zugewinn, wenn die Seite das Bild bereits als Agentur/ROT erkannt hat.
        for s in ctx.prior_signals:
            if getattr(s, "status", None) == SignalStatus.DONE and s.verdict == Verdict.RED:
                return False
        return True

    def execute(self, ctx: CheckContext):
        target = _basename(ctx.image.origin_url) if ctx.image.origin_url else ""
        url = find_origin_url(ctx.image.page_html, target, ctx.image.source_page)
        if not url:
            return self.signal(
                status=SignalStatus.SKIPPED,
                summary="Originalbild auf der Fundseite nicht eindeutig identifizierbar.",
            )
        # Nicht die WLO-Kopie erneut laden (kein Zugewinn).
        if ctx.image.origin_url and urlparse(url).netloc == urlparse(ctx.image.origin_url).netloc:
            return self.signal(
                status=SignalStatus.SKIPPED,
                summary="Fundseiten-Bild ist die WLO-Kopie selbst.",
            )
        try:
            orig = load_from_url(url)
        except ImageLoadError as exc:
            return self.signal(
                status=SignalStatus.UNAVAILABLE,
                summary=f"Originalbild nicht ladbar: {exc}",
            )

        verdict, conf, summary, evidence, data = classify_metadata(
            extract_metadata(orig.pil(), orig.data)
        )
        ev = [f"Original: {url[:150]}"] + evidence
        if verdict == Verdict.NEUTRAL:
            return self.signal(
                verdict=Verdict.NEUTRAL,
                summary="Originalbild geladen, aber ebenfalls ohne Rechte-Metadaten.",
                evidence=ev,
            )
        return self.signal(
            verdict=verdict, confidence=conf,
            summary=summary + " (aus Originalbild der Fundseite)",
            evidence=ev, data=data,
        )
