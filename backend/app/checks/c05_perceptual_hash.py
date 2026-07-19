"""Prüfschritt 5 — Perceptual Hash + interner Risikospeicher (Option 8).

Berechnet SHA-1 (exakte Identität) und dHash (perceptuell) und gleicht sie
gegen den internen Risikospeicher bestätigter Problembilder ab. Der Hash wird
in ExtractedFields mitgeführt (Dedup + Re-Evaluierung ohne Neu-Crawl).
"""

from __future__ import annotations

import hashlib

from ..schemas import CheckSignal, Verdict
from .base import BaseCheck, CheckContext

try:
    import imagehash

    _HAS_IMAGEHASH = True
except Exception:  # noqa: BLE001
    _HAS_IMAGEHASH = False


class PerceptualHashCheck(BaseCheck):
    id = "perceptual_hash"
    label = "Perceptual Hash & Risikospeicher"
    category = "match"

    def execute(self, ctx: CheckContext) -> CheckSignal:
        sha1 = hashlib.sha1(ctx.image.data).hexdigest()
        data: dict = {"sha1": sha1}
        evidence = [f"SHA-1: {sha1}"]

        img = ctx.image.pil()
        phash: str | None = None
        if img is not None and _HAS_IMAGEHASH:
            try:
                phash = str(imagehash.dhash(img))
                data["phash"] = phash
                evidence.append(f"dHash: {phash}")
            except Exception:  # noqa: BLE001
                phash = None

        hub = ctx.risk_hub
        hub_size = getattr(hub, "size", 0)

        if hub is not None:
            exact = hub.match_sha1(sha1)
            if exact:
                return self.signal(
                    verdict=Verdict.RED,
                    confidence=0.95,
                    summary="Exakter Treffer im Risikospeicher "
                    "(bekanntes Problembild).",
                    evidence=evidence + [f"Notiz: {exact.get('note', '')}"],
                    data=data,
                )
            near = hub.match_phash(phash)
            if near:
                return self.signal(
                    verdict=Verdict.RED,
                    confidence=0.85,
                    summary=f"Sehr ähnliches Bild im Risikospeicher "
                    f"(Hamming-Distanz {near.get('distance')}).",
                    evidence=evidence + [f"Notiz: {near.get('note', '')}"],
                    data=data,
                )

        return self.signal(
            verdict=Verdict.NEUTRAL,
            summary=f"Hash berechnet, kein Treffer im Risikospeicher "
            f"({hub_size} Einträge).",
            evidence=evidence,
            data=data,
        )
