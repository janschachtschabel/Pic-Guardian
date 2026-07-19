"""Prüfschritt 4 — C2PA / Content Credentials (Option 6).

Optional: nutzt das ``c2pa``-Paket, falls installiert. Fehlendes Manifest ist
der Normalfall und KEIN Negativsignal (-> INFO). Ein gültiges Manifest eines
Agentur-Signers ist RED, ein CC-/PD-Manifest ein GREEN-Hinweis.
"""

from __future__ import annotations

import json

from ..schemas import CheckSignal, SignalStatus, Verdict
from ..wordlists import contains_agency, contains_free_source
from .base import BaseCheck, CheckContext

try:  # optionales Paket
    import c2pa  # type: ignore

    _HAS_C2PA = True
except Exception:  # noqa: BLE001
    _HAS_C2PA = False


def _read_manifest(mime: str | None, data: bytes) -> dict | None:
    """Versucht, ein C2PA-Manifest zu lesen — API-Varianten defensiv abfangen."""
    fmt = (mime or "image/jpeg")
    # neuere API: c2pa.Reader
    try:
        reader = c2pa.Reader(fmt, data)  # type: ignore[attr-defined]
        return json.loads(reader.json())
    except Exception:  # noqa: BLE001
        pass
    try:
        reader = c2pa.Reader.from_bytes(fmt, data)  # type: ignore[attr-defined]
        return json.loads(reader.json())
    except Exception:  # noqa: BLE001
        pass
    return None


class C2paCheck(BaseCheck):
    id = "c2pa"
    label = "C2PA / Content Credentials"
    category = "file"

    def execute(self, ctx: CheckContext) -> CheckSignal:
        if not _HAS_C2PA:
            return self.signal(
                status=SignalStatus.UNAVAILABLE,
                summary="Optionales Paket 'c2pa' nicht installiert.",
                data={"c2pa_status": "unavailable"},
            )
        try:
            manifest = _read_manifest(ctx.image.mime, ctx.image.data)
        except Exception:  # noqa: BLE001
            manifest = None

        if not manifest or not manifest.get("manifests"):
            return self.signal(
                verdict=Verdict.INFO,
                summary="Kein C2PA-Manifest (Normalfall, kein Negativsignal).",
                data={"c2pa_status": "absent"},
            )

        active = manifest.get("active_manifest")
        m = manifest["manifests"].get(active, {}) if active else {}
        signer = ((m.get("signature_info") or {}).get("issuer")) or m.get("claim_generator", "")
        title = m.get("title", "")
        evidence = [f"Signer: {signer}", f"Titel: {title}"]

        if contains_agency(signer + " " + title):
            return self.signal(
                verdict=Verdict.RED,
                confidence=0.85,
                summary=f"C2PA-Manifest eines Agentur-Signers: {signer}.",
                evidence=evidence,
                data={"c2pa_status": "valid", "supplier": signer},
            )
        if contains_free_source(signer + " " + title):
            return self.signal(
                verdict=Verdict.GREEN,
                confidence=0.6,
                summary=f"C2PA-Manifest mit freier Quelle: {signer}.",
                evidence=evidence,
                data={"c2pa_status": "valid"},
            )
        return self.signal(
            verdict=Verdict.INFO,
            summary=f"C2PA-Manifest vorhanden (Signer: {signer or 'unbekannt'}). "
            "Belegt Herkunftsbehauptung, nicht die Rechtelage.",
            evidence=evidence,
            data={"c2pa_status": "valid"},
        )
