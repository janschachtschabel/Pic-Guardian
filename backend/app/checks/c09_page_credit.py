"""Prüfschritt — Sichtbarer Bildnachweis im DOM der Fundseite (Option 2).

Deutsche Seiten führen den Bildnachweis fast immer als Text (Namensnennungspflicht
§ 13 UrhG), nicht als Metadatum. Sucht figcaption / Caption-/Credit-Klassen /
alt/title in der Nähe des Bildes. Zuordnung Bild↔Credit über den Dateinamen
(src, data-src, srcset, og:image), sonst seitenweit (schwächer). Zusätzlich
werden die Bild-URLs der Seite auf Agentur-Asset-Muster geprüft
(z.B. gettyimages-123456 im src) — das fängt Agenturbilder OHNE sichtbaren
Credit, solange der Original-Dateiname erhalten blieb.
"""

from __future__ import annotations

import re

from ..schemas import CheckSignal, Verdict
from ..wordlists import (
    CREDIT_MARKERS,
    contains_agency,
    contains_free_source,
    find_cc_license,
    match_agency_asset,
)
from .base import BaseCheck, CheckContext

from bs4 import BeautifulSoup

_CREDIT_CLASS_HINTS = (
    "caption", "credit", "copyright", "bildnachweis", "bildquelle",
    "image-source", "wp-caption-text", "quelle", "fotocredit",
)

_OG_IMAGE_PROPS = ("og:image", "og:image:secure_url", "og:image:url", "twitter:image")
_CSS_URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", re.I)


def _basename(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("?")[0].lower()


def _srcset_urls(val: str) -> list[str]:
    """Zerlegt ein srcset-Attribut in seine Kandidaten-URLs."""
    out: list[str] = []
    for part in (val or "").split(","):
        u = part.strip().split(" ")[0].strip()
        if u:
            out.append(u)
    return out


def _img_urls(img) -> list[str]:
    urls: list[str] = []
    for attr in ("src", "data-src"):
        if img.get(attr):
            urls.append(img[attr])
    for attr in ("srcset", "data-srcset"):
        if img.get(attr):
            urls.extend(_srcset_urls(img[attr]))
    return urls


def _has_credit_class(tag) -> bool:
    cls = " ".join(tag.get("class") or []).lower()
    return any(h in cls for h in _CREDIT_CLASS_HINTS)


def _has_marker(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in CREDIT_MARKERS)


class PageCreditCheck(BaseCheck):
    id = "page_credit"
    label = "Sichtbarer Bildnachweis (DOM)"
    category = "page"

    def applies(self, ctx: CheckContext) -> bool:
        return bool(ctx.image.page_html)

    def execute(self, ctx: CheckContext) -> CheckSignal:
        soup = BeautifulSoup(ctx.image.page_html, "lxml")
        target = _basename(ctx.image.origin_url) if ctx.image.origin_url else None
        if target and len(target) <= 4:
            target = None  # zu kurz für einen verlässlichen Vergleich

        texts: list[str] = []
        targeted = False
        # Agentur-Asset-Muster in Bild-URLs: (url, pattern) — getrennt nach
        # Zielbild-Treffer und seitenweitem Treffer.
        url_hit_target: tuple[str, str] | None = None
        url_hit_page: tuple[str, str] | None = None

        # 1) alle <img> durchgehen: Zielbild finden (exakter Basename-Vergleich,
        #    nicht Substring — sonst matcht "cat.jpg" fälschlich "black-cat.jpg")
        #    und jede Kandidaten-URL auf Agentur-Asset-Muster prüfen.
        for img in soup.find_all("img"):
            urls = _img_urls(img)
            is_target = bool(target and any(_basename(u) == target for u in urls))
            for u in urls:
                hit = match_agency_asset(u)
                if hit and hit[1]:  # nur starke Muster (mit Asset-ID) auf URLs
                    if is_target and url_hit_target is None:
                        url_hit_target = (u, hit[0].pattern, hit[2])
                    elif not is_target and url_hit_page is None:
                        url_hit_page = (u, hit[0].pattern, hit[2])
            if is_target and not targeted:
                targeted = True
                for attr in ("alt", "title", "data-credit", "data-caption"):
                    if img.get(attr):
                        texts.append(img[attr])
                fig = img.find_parent("figure")
                if fig and fig.find("figcaption"):
                    texts.append(fig.find("figcaption").get_text(" ", strip=True))
                # nahe Geschwister mit Credit-Klasse
                parent = img.parent
                for _ in range(2):
                    if parent is None:
                        break
                    for sib in parent.find_all(_has_credit_class, recursive=False):
                        texts.append(sib.get_text(" ", strip=True))
                    parent = parent.parent

        # 1b) og:image — ist das geprüfte Bild das Hauptbild der Seite, binden
        #     seitenweite Credits mit höherer Sicherheit an genau dieses Bild.
        og_match = False
        for meta in soup.find_all("meta"):
            prop = (meta.get("property") or meta.get("name") or "").lower()
            if prop not in _OG_IMAGE_PROPS:
                continue
            u = meta.get("content") or ""
            if not u:
                continue
            is_target = bool(target and _basename(u) == target)
            if is_target:
                og_match = True
            hit = match_agency_asset(u)
            if hit and hit[1]:
                if is_target and url_hit_target is None:
                    url_hit_target = (u, hit[0].pattern, hit[2])
                elif not is_target and url_hit_page is None:
                    url_hit_page = (u, hit[0].pattern, hit[2])

        # 1c) <picture>/<source srcset> + CSS background-image url() — dieselben
        #     Agentur-Asset-Muster, andere Einbindungsart (Brainstorming Nr. 13).
        if url_hit_page is None and url_hit_target is None:
            more_urls: list[str] = []
            for src_tag in soup.find_all("source"):
                more_urls.extend(_srcset_urls(src_tag.get("srcset") or ""))
            for tag in soup.find_all(style=True):
                for m in _CSS_URL_RE.finditer(tag.get("style") or ""):
                    more_urls.append(m.group(1))
            for u in more_urls:
                hit = match_agency_asset(u)
                if hit and hit[1]:
                    url_hit_page = (u, hit[0].pattern, hit[2])
                    break

        bound = targeted or og_match

        # 2) seitenweit: alle figcaption + Credit-Klassen (schwächeres Signal)
        if not texts:
            for cap in soup.find_all("figcaption"):
                texts.append(cap.get_text(" ", strip=True))
            for el in soup.find_all(_has_credit_class):
                texts.append(el.get_text(" ", strip=True))

        texts = [t.strip() for t in texts if t and t.strip()]
        # nur Texte mit Nachweis-Charakter behalten
        credits = [t for t in texts if _has_marker(t) or contains_agency(t) or contains_free_source(t)]

        joined = " | ".join(dict.fromkeys(credits))[:600]
        evidence = [f"Bildnachweis: {joined}"] if credits else []
        conf_factor = 1.0 if bound else 0.7
        data: dict = {"credit_text": credits[0][:300]} if credits else {}

        agency = contains_agency(" ".join(credits))
        if agency:
            data["supplier"] = agency
            # Ein Agenturname ist per se ein starkes Signal — die seitenweite
            # Unsicherheit betrifft nur, WELCHES Bild, nicht OB Agenturmaterial
            # vorliegt. Daher auch ohne Bild-Zuordnung starkes RED (>= 0.8).
            return self.signal(
                verdict=Verdict.RED, confidence=0.85 if bound else 0.8,
                summary=f"Agentur im Bildnachweis: {agency}"
                + ("" if bound else " (seitenweit auf der Fundseite)"),
                evidence=evidence, data=data,
            )

        # 2b) Agentur-Asset-Muster in einer Bild-URL der Fundseite — fängt
        #     Agenturbilder ohne sichtbaren Credit (Original-Dateiname erhalten).
        if url_hit_target or url_hit_page:
            url, pattern, supplier = url_hit_target or url_hit_page
            data["supplier"] = supplier  # Agentur aus dem Muster (fürs Protokoll)
            return self.signal(
                verdict=Verdict.RED,
                confidence=0.85 if url_hit_target else 0.8,
                summary=f"Agentur-Asset-Muster in Bild-URL der Fundseite: {supplier}"
                + ("" if url_hit_target else " (anderes Bild der Seite)") + ".",
                evidence=evidence + [f"URL: {url[:200]}", f"Muster: {pattern}"],
                data=data,
            )

        if not credits:
            return self.signal(
                verdict=Verdict.NEUTRAL,
                summary="Kein sichtbarer Bildnachweis im Seitenumfeld gefunden.",
            )

        cc_label, cc_uri = find_cc_license(" ".join(credits))
        if cc_uri:
            data["license_uri"] = cc_uri
            data["license_label"] = cc_label
            return self.signal(
                verdict=Verdict.GREEN, confidence=round(0.7 * conf_factor, 2),
                summary=f"Freie Lizenz im Bildnachweis: {cc_label}.",
                evidence=evidence, data=data,
            )

        return self.signal(
            verdict=Verdict.YELLOW, confidence=round(0.5 * conf_factor, 2),
            summary="Bildnachweis vorhanden, aber nicht klassifizierbar — "
            "als Attribution gespeichert, redaktionelle Prüfung.",
            evidence=evidence, data=data,
        )
