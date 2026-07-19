"""Prüfschritt — Zentrale Bildnachweis-Seite der Fundseiten-Domain.

Viele (Bildungs-)Seiten führen ihre Bildquellen nicht an den Bildern selbst,
sondern gesammelt auf einer eigenen Seite („Bildnachweis", „Bildquellen").
Der Check folgt einem solchen Link von der Fundseite (nur gleiche Domain,
SSRF-geschützt) und prüft den Text auf Agentur-Nennungen und — wenn möglich —
auf den Dateinamen des geprüften Bilds.

Bewertung bewusst konservativ: eine Agentur-Nennung auf der zentralen
Nachweis-Seite belegt Agenturmaterial IRGENDWO auf der Site, nicht zwingend
für dieses Bild → ohne Dateinamen-Zuordnung nur YELLOW.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ..config import SETTINGS
from ..net_guard import BlockedURLError, safe_get
from ..schemas import CheckSignal, Verdict
from ..wordlists import contains_agency, contains_free_source
from .base import BaseCheck, CheckContext

_LINK_RE = re.compile(
    r"bildnachweis|bildquellen?|bildrechte|fotonachweis|foto[-_ ]?credits?"
    r"|photo[-_ ]?credits?|image[-_ ]?credits?",
    re.I,
)

_MAX_LINKS = 2  # höchstens so viele Nachweis-Seiten pro Fundseite abrufen


def _same_site(page_url: str, link_url: str) -> bool:
    """Gleicher Host oder gleiche registrierbare Domain (www.x.de ~ x.de)."""
    a = urlparse(page_url).netloc.lower()
    b = urlparse(link_url).netloc.lower()
    if not a or not b:
        return False
    if a == b:
        return True
    tail = lambda h: ".".join(h.rsplit(".", 2)[-2:])  # noqa: E731
    return tail(a) == tail(b)


def classify_credit_page(text: str, target_basename: str | None) -> tuple[Verdict, float, str]:
    """Pure Klassifikation des Nachweis-Seitentexts (testbar ohne Netz).
    Returns (verdict, confidence, summary)."""
    low = text.lower()
    agency = contains_agency(text)
    named = bool(target_basename and len(target_basename) > 4 and target_basename in low)
    if agency and named:
        return (
            Verdict.RED, 0.85,
            f"Bildnachweis-Seite nennt Agentur ({agency}) und den Dateinamen "
            "des geprüften Bilds.",
        )
    if agency:
        return (
            Verdict.YELLOW, 0.6,
            f"Bildnachweis-Seite der Domain nennt eine Agentur ({agency}) — "
            "Zuordnung zum geprüften Bild unklar, redaktionelle Prüfung.",
        )
    free = contains_free_source(text)
    if free:
        return (
            Verdict.YELLOW, 0.3,
            f"Bildnachweis-Seite nennt freie Quellen ({free}) — kein "
            "bildbezogener Beleg, aber kein Agentur-Hinweis.",
        )
    return (Verdict.NEUTRAL, 0.0, "Bildnachweis-Seite ohne verwertbares Signal.")


class CreditPageCheck(BaseCheck):
    id = "credit_page"
    label = "Bildnachweis-Seite der Domain"
    category = "page"

    def applies(self, ctx: CheckContext) -> bool:
        return bool(ctx.image.page_html and ctx.image.source_page)

    def execute(self, ctx: CheckContext) -> CheckSignal:
        soup = BeautifulSoup(ctx.image.page_html, "lxml")
        page_url = ctx.image.source_page or ""

        # Kandidaten-Links einsammeln (Text ODER href matcht), dedupliziert.
        candidates: list[str] = []
        for a in soup.find_all("a"):
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("#", "mailto:", "javascript:")):
                continue
            label = a.get_text(" ", strip=True)
            if not (_LINK_RE.search(href) or _LINK_RE.search(label)):
                continue
            absolute = urljoin(page_url, href)
            if not absolute.startswith(("http://", "https://")):
                continue
            if not _same_site(page_url, absolute):
                continue  # fremde Domains nicht abrufen
            if absolute.split("#")[0] == page_url.split("#")[0]:
                continue  # Selbstverweis
            if absolute not in candidates:
                candidates.append(absolute)

        if not candidates:
            return self.signal(
                verdict=Verdict.NEUTRAL,
                summary="Kein Link auf eine Bildnachweis-Seite gefunden.",
            )

        target = None
        if ctx.image.origin_url:
            target = ctx.image.origin_url.rsplit("/", 1)[-1].split("?")[0].lower()

        headers = {"User-Agent": SETTINGS.user_agent, "Accept": "text/html,*/*"}
        best: tuple[Verdict, float, str] | None = None
        best_url = ""
        for url in candidates[:_MAX_LINKS]:
            try:
                with httpx.Client(timeout=SETTINGS.http_timeout) as client:
                    r = safe_get(client, url, headers=headers, max_bytes=3_000_000)
            except (httpx.HTTPError, BlockedURLError):
                continue
            if r.status_code >= 400 or "html" not in r.headers.get("content-type", "").lower():
                continue
            try:
                text = BeautifulSoup(r.text[:2_000_000], "lxml").get_text(" ", strip=True)
            except Exception:  # noqa: BLE001
                continue
            verdict, conf, summary = classify_credit_page(text, target)
            if best is None or conf > best[1]:
                best, best_url = (verdict, conf, summary), url
                if verdict == Verdict.RED:
                    break  # stärkster Befund — weitere Links unnötig

        if best is None:
            return self.signal(
                verdict=Verdict.NEUTRAL,
                summary="Bildnachweis-Seite verlinkt, aber nicht abrufbar.",
                evidence=[f"Link: {candidates[0][:200]}"],
            )

        verdict, conf, summary = best
        return self.signal(
            verdict=verdict, confidence=conf, summary=summary,
            evidence=[f"Nachweis-Seite: {best_url[:200]}"],
        )
