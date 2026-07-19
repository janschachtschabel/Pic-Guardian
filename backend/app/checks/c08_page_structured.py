"""Prüfschritt — Strukturierte Rechteangaben auf der Fundseite (Option 1).

Liest schema.org (JSON-LD/Microdata/RDFa), OpenGraph und ccREL (rel="license")
sowie Dublin-Core-Meta aus dem Fundseiten-HTML. Braucht ``page_html`` — im
URL-Modus aus dem Feld „Fundseite", im Node-Modus aus ``ccm:wwwurl``.
"""

from __future__ import annotations

from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..schemas import CheckSignal, Verdict
from ..wordlists import contains_agency, find_cc_license, normalize_license_uri
from .base import BaseCheck, CheckContext

try:
    import extruct  # type: ignore

    _HAS_EXTRUCT = True
except Exception:  # noqa: BLE001
    _HAS_EXTRUCT = False

_PD_MARKERS = ("publicdomain", "public_domain", "gemeinfrei", "/pdm", "/cc0", "/zero")
_LICENSE_KEYS = {"license", "acquirelicensepage", "credittext", "copyrightnotice", "creator"}


def _short(key: str) -> str:
    return key.lower().rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def _collect(obj, out: dict[str, list]) -> None:
    """Sammelt relevante Rechte-Keys rekursiv aus verschachtelten Strukturen."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _short(str(k)) in _LICENSE_KEYS:
                out.setdefault(_short(str(k)), []).append(v)
            _collect(v, out)
    elif isinstance(obj, list):
        for it in obj:
            _collect(it, out)


def _as_url(v) -> str | None:
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, dict):
        for key in ("@id", "url", "@value", "contentUrl"):
            if isinstance(v.get(key), str):
                return v[key].strip() or None
    if isinstance(v, list) and v:
        return _as_url(v[0])
    return None


def _as_text(v) -> str | None:
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, dict):
        return _as_url(v)
    if isinstance(v, list) and v:
        return _as_text(v[0])
    return None


def _img_basename(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("?")[0].lower()


def _image_bound_license(obj, target: str) -> str | None:
    """Sucht eine Lizenz, die direkt an einem ImageObject des Zielbilds hängt
    (JSON-LD ``@type`` bzw. Microdata ``type`` = ImageObject, dessen
    contentUrl/url auf den Basename des geprüften Bilds zeigt)."""
    if isinstance(obj, dict):
        types = obj.get("@type") or obj.get("type") or ""
        if isinstance(types, list):
            types = " ".join(str(t) for t in types)
        if "imageobject" in str(types).lower():
            props = obj.get("properties") if isinstance(obj.get("properties"), dict) else obj
            src = _as_url(props.get("contentUrl") or props.get("url"))
            lic = _as_url(props.get("license"))
            if lic and src and _img_basename(src) == target:
                return lic
        for v in obj.values():
            if (r := _image_bound_license(v, target)) is not None:
                return r
    elif isinstance(obj, list):
        for it in obj:
            if (r := _image_bound_license(it, target)) is not None:
                return r
    return None


class PageStructuredCheck(BaseCheck):
    id = "page_structured"
    label = "Strukturierte Rechteangaben (schema.org/ccREL)"
    category = "page"

    def applies(self, ctx: CheckContext) -> bool:
        return bool(ctx.image.page_html)

    def execute(self, ctx: CheckContext) -> CheckSignal:
        html = ctx.image.page_html
        page_url = ctx.image.source_page or ""
        found: dict[str, list] = {}

        extracted = None
        if _HAS_EXTRUCT:
            try:
                extracted = extruct.extract(
                    html,
                    base_url=page_url,
                    syntaxes=["json-ld", "microdata", "rdfa", "opengraph"],
                    errors="ignore",
                )
                _collect(extracted, found)
            except Exception:  # noqa: BLE001
                pass

        # ccREL: rel="license" an <a>/<link>
        rel_licenses: list[str] = []
        dc_rights: list[str] = []
        try:
            soup = BeautifulSoup(html, "lxml")
            for tag in soup.find_all(["a", "link"]):
                rels = [r.lower() for r in (tag.get("rel") or [])]
                if "license" in rels and tag.get("href"):
                    rel_licenses.append(tag["href"])
            for meta in soup.find_all("meta"):
                name = (meta.get("name") or meta.get("property") or "").lower()
                if name in ("dc.rights", "dcterms.rights", "dcterms.license", "dc.creator"):
                    if meta.get("content"):
                        dc_rights.append(meta["content"])
        except Exception:  # noqa: BLE001
            pass

        licenses = [u for v in found.get("license", []) if (u := _as_url(v))]
        licenses += rel_licenses
        acquire = [u for v in found.get("acquirelicensepage", []) if (u := _as_url(v))]
        credits = [t for v in found.get("credittext", []) if (t := _as_text(v))]
        credits += [t for v in found.get("copyrightnotice", []) if (t := _as_text(v))]
        credits += dc_rights
        creators = [t for v in found.get("creator", []) if (t := _as_text(v))]

        if not any([licenses, acquire, credits, creators]):
            return self.signal(
                verdict=Verdict.NEUTRAL,
                summary="Keine strukturierten Rechteangaben auf der Fundseite.",
            )

        evidence: list[str] = []
        if licenses:
            evidence.append("license: " + "; ".join(licenses[:3]))
        if acquire:
            evidence.append("acquireLicensePage: " + "; ".join(acquire[:2]))
        if credits:
            evidence.append("credit/copyright: " + "; ".join(c[:120] for c in credits[:2]))
        data: dict = {}
        if creators:
            data["creator"] = creators[0]
        if credits:
            data["credit_text"] = credits[0]

        page_host = urlparse(page_url).netloc.lower()

        # Lizenz-URLs klassifizieren: CC / Public Domain / Agentur.
        free_uri: str | None = None
        free_label: str | None = None
        agency_license = False
        # ALLE Lizenz-Links klassifizieren, bevor entschieden wird — sonst hinge
        # das Verdikt (RED vs GREEN) bei gemischten Links an der DOM-Reihenfolge.
        for u in licenses:
            cc = normalize_license_uri(u)
            low = u.lower()
            if cc and free_uri is None:
                free_uri = cc
            elif any(t in low for t in _PD_MARKERS) and free_uri is None:
                free_uri, free_label = u, "Public Domain / gemeinfrei"
            if contains_agency(low):
                agency_license = True

        cc_label, cc_from_text = find_cc_license(" ".join(credits + licenses))
        credit_agency = contains_agency(" ".join(credits))

        # 1) Agentur (im Credit oder als Lizenz-Link) -> RED
        if credit_agency or agency_license:
            data["supplier"] = credit_agency or "Agentur"
            detail = f": {credit_agency}" if credit_agency else " (Lizenz-Link)"
            return self.signal(
                verdict=Verdict.RED, confidence=0.8,
                summary=f"Agentur in Rechteangabe der Fundseite{detail}.",
                evidence=evidence, data=data,
            )

        # 2) Freie Lizenz (CC/PD) deklariert -> GREEN.
        #    Schlägt acquireLicensePage: freie Werke (z.B. Commons) verweisen für
        #    Google-„Licensable" auf ihre eigene Lizenzinfo-Seite.
        if free_uri or cc_from_text:
            data["license_uri"] = free_uri or cc_from_text
            data["license_label"] = free_label or cc_label
            # Bindung ermitteln: nur eine FREIE Lizenz direkt am ImageObject des
            # Zielbilds gilt als bildbezogen. Eine seitenweite Angabe (z.B. der
            # CC-Hinweis für den Artikeltext einer Nachrichtenseite) belegt die
            # Lizenz des eingebetteten Bilds nicht — Scope "page" wird in der
            # Aggregation wie eine Selbstauskunft behandelt.
            target = _img_basename(ctx.image.origin_url) if ctx.image.origin_url else ""
            bound = None
            if extracted is not None and len(target) > 4:
                bound = _image_bound_license(extracted, target)
                if bound and not (
                    normalize_license_uri(bound)
                    or any(t in bound.lower() for t in _PD_MARKERS)
                ):
                    bound = None
            data["license_scope"] = "image" if bound else "page"
            return self.signal(
                verdict=Verdict.GREEN, confidence=0.8,
                summary=f"Freie Lizenz strukturiert ausgezeichnet: "
                f"{free_label or cc_label or (free_uri or cc_from_text)}"
                + ("" if bound else " (seitenweite Angabe)") + ".",
                evidence=evidence, data=data,
            )

        # 3) acquireLicensePage auf EXTERNE Domain -> Kaufweg -> RED.
        #    Selbstverweis auf die Fundseiten-Domain ist KEIN Kaufsignal.
        for a in acquire:
            ahost = urlparse(a if a.startswith("http") else "https:" + a).netloc.lower()
            if ahost and ahost != page_host:
                data["acquire_url"] = a
                return self.signal(
                    verdict=Verdict.RED, confidence=0.8,
                    summary="Fundseite verweist auf externe Lizenzerwerb-Seite "
                    "(schema.org acquireLicensePage).",
                    evidence=evidence, data=data,
                )

        # 4) Angaben vorhanden, aber nicht klassifizierbar -> YELLOW
        if credits or creators:
            return self.signal(
                verdict=Verdict.YELLOW, confidence=0.4,
                summary="Rechteangaben auf der Fundseite gefunden, aber nicht "
                "eindeutig — redaktionelle Prüfung.",
                evidence=evidence, data=data,
            )

        # 5) nur Selbstverweis / OpenGraph ohne Lizenzsignal -> NEUTRAL
        return self.signal(
            verdict=Verdict.NEUTRAL,
            summary="Strukturierte Angaben ohne eindeutiges Lizenzsignal.",
            evidence=evidence, data=data,
        )
