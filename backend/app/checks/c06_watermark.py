"""Prüfschritt 6 — Sichtbares Wasserzeichen / eingebrannter Credit via OCR (Option 7).

Optional: nutzt ``pytesseract`` + System-Tesseract, falls vorhanden. Findet
eingebrannten Agentur-Text ("Shutterstock", "Getty Images", "Preview" …).
Ohne Tesseract meldet der Schritt sauber "nicht verfügbar".
"""

from __future__ import annotations

from ..schemas import CheckSignal, SignalStatus, Verdict
from ..wordlists import WATERMARK_TEXT_MARKERS
from .base import BaseCheck, CheckContext

try:
    import pytesseract

    _HAS_TESS = True
except Exception:  # noqa: BLE001
    _HAS_TESS = False


class WatermarkCheck(BaseCheck):
    id = "watermark_ocr"
    label = "Wasserzeichen / eingebrannter Credit (OCR)"
    category = "file"

    def applies(self, ctx: CheckContext) -> bool:
        return ctx.image.pil() is not None

    def execute(self, ctx: CheckContext) -> CheckSignal:
        if not _HAS_TESS:
            return self.signal(
                status=SignalStatus.UNAVAILABLE,
                summary="OCR nicht verfügbar — 'pytesseract' + Tesseract "
                "installieren, um diesen Schritt zu aktivieren.",
            )
        img = ctx.image.pil()
        try:
            text = pytesseract.image_to_string(img)
        except Exception as exc:  # noqa: BLE001 — u.a. TesseractNotFoundError
            return self.signal(
                status=SignalStatus.UNAVAILABLE,
                summary=f"Tesseract-Binary nicht gefunden ({exc}).",
            )

        low = " " + text.lower() + " "
        found = sorted({m for m in WATERMARK_TEXT_MARKERS if m in low})
        agency_like = [m for m in found if m not in ("preview", "sample", "watermark", "demo")]

        if agency_like:
            return self.signal(
                verdict=Verdict.RED,
                confidence=0.8,
                summary=f"Agentur-Wasserzeichen erkannt: {', '.join(agency_like)}.",
                evidence=[f"OCR-Fund: {', '.join(found)}"],
                data={"watermark_score": 1.0, "supplier": agency_like[0]},
            )
        if found:  # nur generische Marker wie "preview"
            return self.signal(
                verdict=Verdict.YELLOW,
                confidence=0.4,
                summary=f"Mögliches Wasserzeichen ('{', '.join(found)}') — "
                "unklar, Review.",
                evidence=[f"OCR-Fund: {', '.join(found)}"],
                data={"watermark_score": 0.5},
            )
        return self.signal(
            verdict=Verdict.NEUTRAL,
            summary="Kein Agentur-Wasserzeichen im OCR-Text.",
            data={"watermark_score": 0.0},
        )
