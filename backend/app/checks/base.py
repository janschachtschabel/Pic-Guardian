"""Basisklasse & Kontext für Prüfschritte.

Jeder Check erbt von ``BaseCheck`` und implementiert ``execute``. Die
Basisklasse kapselt einheitlich: Opt-in-Gate für externe Dienste,
Anwendbarkeit, Fehlerbehandlung und Zeitmessung. Dadurch bleibt jeder Check
klein und die Pipeline erweiterbar.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..image_source import ImageContext
from ..schemas import CheckSignal, SignalStatus, Verdict


@dataclass
class CheckContext:
    """Laufzeit-Kontext, den jeder Check erhält."""

    image: ImageContext
    allow_external: bool
    risk_hub: "object | None" = None  # RiskHub (spät gebunden, vermeidet Zyklus)
    # bereits gelaufene Signale — erlaubt späteren Checks, auf früher extrahierte
    # Felder (z.B. Urheber) aufzubauen.
    prior_signals: list = field(default_factory=list)

    def extracted(self, key: str) -> str | None:
        for s in self.prior_signals:
            val = (getattr(s, "data", None) or {}).get(key)
            if val:
                return str(val)
        return None


class BaseCheck:
    id: str = ""
    label: str = ""
    category: str = "file"       # file | page | match | repository | external
    external: bool = False       # nutzt externen Dienst -> Opt-in nötig

    # -- von Subklassen zu überschreiben -----------------------------------
    def applies(self, ctx: CheckContext) -> bool:
        return True

    def execute(self, ctx: CheckContext) -> CheckSignal:
        raise NotImplementedError

    # -- Framework ---------------------------------------------------------
    def run(self, ctx: CheckContext) -> CheckSignal:
        start = time.perf_counter()
        if self.external and not ctx.allow_external:
            return self.signal(
                status=SignalStatus.UNAVAILABLE,
                summary="Externer Dienst deaktiviert — Opt-in erforderlich "
                "(überträgt das Bild an Dritte).",
            )
        if not self.applies(ctx):
            return self.signal(
                status=SignalStatus.SKIPPED, summary="Für diese Quelle nicht anwendbar."
            )
        try:
            sig = self.execute(ctx)
        except Exception as exc:  # noqa: BLE001 — Check darf Pipeline nicht kippen
            sig = self.signal(
                status=SignalStatus.ERROR, summary=f"Prüfung fehlgeschlagen: {exc}"
            )
        sig.duration_ms = int((time.perf_counter() - start) * 1000)
        return sig

    # -- Helper ------------------------------------------------------------
    def signal(
        self,
        *,
        status: SignalStatus = SignalStatus.DONE,
        verdict: Verdict = Verdict.NEUTRAL,
        confidence: float = 0.0,
        summary: str = "",
        evidence: list[str] | None = None,
        data: dict | None = None,
    ) -> CheckSignal:
        return CheckSignal(
            id=self.id,
            label=self.label,
            category=self.category,
            external=self.external,
            status=status,
            verdict=verdict,
            confidence=confidence,
            summary=summary,
            evidence=evidence or [],
            data=data or {},
        )
