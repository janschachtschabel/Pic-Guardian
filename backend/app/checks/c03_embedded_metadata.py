"""Prüfschritt 3 — Eingebettete Metadaten (Option 5): EXIF / IPTC / XMP / PLUS.

Reine Python-Auswertung (Pillow + XMP-Packet-Parsing), kein exiftool nötig.
Wichtig: ~85 % der Web-Bilder haben keine Metadaten mehr — leere Felder sind
KEIN GREEN, sondern "kein Signal".
"""

from __future__ import annotations

import re

from PIL import IptcImagePlugin

from ..schemas import CheckSignal, Verdict
from ..wordlists import (
    contains_agency,
    find_cc_license,
    match_agency_asset,
    normalize_license_uri,
)
from .base import BaseCheck, CheckContext

# EXIF-Tag-Namen -> ID
_EXIF_COPYRIGHT = 0x8298
_EXIF_ARTIST = 0x013B

# IPTC IIM-Records (Record 2)
_IPTC_COPYRIGHT = (2, 116)
_IPTC_BYLINE = (2, 80)
_IPTC_CREDIT = (2, 110)
_IPTC_SOURCE = (2, 115)
_IPTC_INSTRUCTIONS = (2, 40)  # SpecialInstructions — Agenturen hinterlegen dort Nutzungsauflagen


def _extract_exif(img) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        exif = img.getexif()
    except Exception:  # noqa: BLE001
        return out
    if not exif:
        return out
    cp = exif.get(_EXIF_COPYRIGHT)
    ar = exif.get(_EXIF_ARTIST)
    if cp:
        out["copyright"] = str(cp).strip()
    if ar:
        out["creator"] = str(ar).strip()
    return out


def _decode(v) -> str:
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace").strip()
    return str(v).strip()


def _extract_iptc(img) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        iptc = IptcImagePlugin.getiptcinfo(img)
    except Exception:  # noqa: BLE001
        iptc = None
    if not iptc:
        return out
    mapping = {
        _IPTC_COPYRIGHT: "copyright",
        _IPTC_BYLINE: "creator",
        _IPTC_CREDIT: "credit",
        _IPTC_SOURCE: "source",
        _IPTC_INSTRUCTIONS: "instructions",
    }
    for key, name in mapping.items():
        if key in iptc and iptc[key]:
            val = iptc[key]
            if isinstance(val, (list, tuple)):
                val = val[0]
            out[name] = _decode(val)
    return out


def _extract_xmp_packet(data: bytes) -> str | None:
    start = data.find(b"<x:xmpmeta")
    if start == -1:
        start = data.find(b"<rdf:RDF")
    if start == -1:
        return None
    end = data.find(b"</x:xmpmeta>")
    if end != -1:
        end += len(b"</x:xmpmeta>")
    else:
        e2 = data.find(b"</rdf:RDF>")
        end = e2 + len(b"</rdf:RDF>") if e2 != -1 else min(len(data), start + 200_000)
    return data[start:end].decode("utf-8", errors="replace")


def _xmp_value(xmp: str, field: str) -> str | None:
    """Liest ein XMP-Feld — sowohl Element- als auch Attribut-Serialisierung."""
    fe = re.escape(field)
    m = re.search(rf"<{fe}[^>]*>(.*?)</{fe}>", xmp, re.S | re.I)
    if m:
        inner = m.group(1)
        li = re.search(r"<rdf:li[^>]*>(.*?)</rdf:li>", inner, re.S | re.I)
        val = (li.group(1) if li else inner)
        val = re.sub(r"<[^>]+>", "", val).strip()
        if val:
            return val
    m = re.search(rf'{fe}\s*=\s*"([^"]*)"', xmp, re.I)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return None


def _extract_xmp(data: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    xmp = _extract_xmp_packet(data)
    if not xmp:
        return out
    fields = {
        "dc:rights": "copyright",
        "dc:creator": "creator",
        "photoshop:Credit": "credit",
        "photoshop:Source": "source",
        "photoshop:Instructions": "instructions",
        "xmpRights:WebStatement": "web_statement",
        "xmpRights:UsageTerms": "usage_terms",
        "plus:LicensorURL": "licensor_url",
        "plus:LicensorName": "licensor_name",
        "Iptc4xmpExt:DigitalSourceType": "digital_source",
        # Agentur-Workflows lassen die Herkunfts-ID oft stehen, auch wenn
        # Credit/Source gestrippt wurden — dpa nutzt urn:newsml:dpa.com-IDs.
        "xmpMM:DocumentID": "document_id",
        "xmpMM:OriginalDocumentID": "original_document_id",
    }
    for xmp_field, name in fields.items():
        val = _xmp_value(xmp, xmp_field)
        if val:
            out[name] = val
    return out


def extract_metadata(pil_img, data: bytes) -> dict[str, str]:
    """EXIF + IPTC + XMP eines Bilds zu einem Feld-Dict mergen. Wiederverwendbar
    für die WLO-Vorschau (c03) UND das Originalbild der Fundseite (c13)."""
    meta: dict[str, str] = {}
    if pil_img is not None:
        meta.update(_extract_exif(pil_img))
        # IPTC/EXIF sollen XMP nicht überschreiben, daher XMP zuletzt mergen
        for k, v in _extract_iptc(pil_img).items():
            meta.setdefault(k, v)
    for k, v in _extract_xmp(data).items():
        meta[k] = v  # XMP ist am aussagekräftigsten
    return meta


def classify_metadata(
    meta: dict[str, str],
) -> tuple[Verdict, float, str, list[str], dict]:
    """Reine Klassifikation eines Metadaten-Dicts (ohne Netz/Signal-Objekt).
    Returns (verdict, confidence, summary, evidence, data)."""
    if not meta:
        return (
            Verdict.NEUTRAL, 0.0,
            "Keine eingebetteten Rechte-Metadaten gefunden "
            "(häufig durch CMS-Resizing entfernt — kein Freigabe-Beleg).",
            [], {},
        )

    evidence = [f"{k}: {v[:180]}" for k, v in meta.items()]
    all_text = " ".join(meta.values())
    data: dict = {}
    if meta.get("creator"):
        data["creator"] = meta["creator"]
    if meta.get("credit"):
        data["credit_text"] = meta["credit"]
    if meta.get("copyright"):
        data["license_field"] = meta["copyright"]
    if meta.get("digital_source", "").lower().endswith("trainedalgorithmicmedia"):
        evidence.append("KI-Kennzeichnung (DigitalSourceType = trainedAlgorithmicMedia)")

    # 1) Agentur -> RED
    agency = (
        contains_agency(meta.get("credit", ""))
        or contains_agency(meta.get("source", ""))
        or contains_agency(meta.get("licensor_name", ""))
        or contains_agency(all_text)
    )
    licensor_url = meta.get("licensor_url") or ""
    web_statement = meta.get("web_statement") or ""

    if agency:
        data["supplier"] = agency
        return (Verdict.RED, 0.9, f"Agentur in Metadaten genannt: {agency}.",
                evidence, data)

    # 1b) Agentur-Asset-Muster in Herkunfts-IDs — Agentur-Workflows lassen die
    #     DocumentID oft stehen, wenn Credit/Source gestrippt wurden.
    doc_ids = " ".join(
        filter(None, (meta.get("document_id"), meta.get("original_document_id")))
    )
    asset_hit = match_agency_asset(doc_ids)
    if asset_hit and asset_hit[1]:  # nur starke Muster (mit Asset-ID)
        data["supplier"] = asset_hit[2]
        return (Verdict.RED, 0.85,
                f"Agentur-Asset-ID in den Herkunfts-Metadaten: {asset_hit[2]} "
                "(xmpMM:DocumentID).",
                evidence + [f"Muster: {asset_hit[0].pattern}"], data)

    # 2) Kaufweg-Signal -> RED: plus:LicensorURL ODER WebStatement auf Agentur-
    #    Domain. Generisches WebStatement (Museum-Open-Access) fällt auf YELLOW.
    for url, is_licensor in ((licensor_url, True), (web_statement, False)):
        if not url or not url.startswith("http") or normalize_license_uri(url):
            continue
        if is_licensor or contains_agency(url):
            data["acquire_url"] = url
            return (Verdict.RED, 0.8,
                    "Lizenzerwerb-/Lizenzgeber-URL in Metadaten (kein CC).",
                    evidence, data)

    # 3) CC-URI / CC-Code -> GREEN
    cc_uri = normalize_license_uri(web_statement) or normalize_license_uri(licensor_url)
    cc_label, cc_from_text = find_cc_license(all_text)
    if cc_uri or cc_from_text:
        data["license_uri"] = cc_uri or cc_from_text
        if cc_label:
            data["license_label"] = cc_label
        return (Verdict.GREEN, 0.8,
                f"Freie Lizenz in Metadaten: {cc_label or cc_uri}.", evidence, data)

    # 4) Felder vorhanden, aber nicht klassifizierbar -> YELLOW
    return (Verdict.YELLOW, 0.4,
            "Rechte-Metadaten vorhanden, aber nicht eindeutig klassifizierbar "
            "— redaktionelle Prüfung.", evidence, data)


class EmbeddedMetadataCheck(BaseCheck):
    id = "embedded_metadata"
    label = "Eingebettete Metadaten (EXIF/IPTC/XMP)"
    category = "file"

    def execute(self, ctx: CheckContext) -> CheckSignal:
        meta = extract_metadata(ctx.image.pil(), ctx.image.data)
        verdict, conf, summary, evidence, data = classify_metadata(meta)
        return self.signal(
            verdict=verdict, confidence=conf, summary=summary,
            evidence=evidence, data=data,
        )
