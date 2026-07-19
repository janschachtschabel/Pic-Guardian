"""Pydantic-Datenmodelle — der gemeinsame Ergebnis-Contract von Checks,
Aggregation und Frontend.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    """Ampel-Wertung eines Einzelsignals bzw. des Gesamtergebnisses."""

    RED = "red"        # lizenzpflichtig / geschützt — Warnung
    YELLOW = "yellow"  # unklar / Review nötig
    GREEN = "green"    # nachgewiesen unkritisch
    NEUTRAL = "neutral"  # Check lief, aber kein Signal (zählt wie "unchecked")
    INFO = "info"      # rein informativ, ohne Ampel-Wirkung


class SignalStatus(str, Enum):
    """Technischer Ausführungsstatus eines Prüfschritts."""

    DONE = "done"              # ausgeführt, Ergebnis liegt vor
    SKIPPED = "skipped"        # bewusst übersprungen (z.B. nicht anwendbar)
    UNAVAILABLE = "unavailable"  # Abhängigkeit/Dienst fehlt (z.B. Opt-in aus)
    ERROR = "error"            # Fehler bei der Ausführung


class CheckSignal(BaseModel):
    """Ergebnis eines einzelnen Prüfschritts."""

    id: str
    label: str
    category: str = Field(description="file | page | match | repository | external")
    status: SignalStatus = SignalStatus.DONE
    verdict: Verdict = Verdict.NEUTRAL
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    summary: str = ""
    evidence: list[str] = Field(default_factory=list)
    external: bool = False  # nutzt dieser Check einen externen Dienst?
    duration_ms: int | None = None
    # strukturierte Extraktion (fließt in ExtractedFields der Aggregation)
    data: dict = Field(default_factory=dict)


class ExtractedFields(BaseModel):
    """Aggregierte, für Attribution/Re-Evaluierung relevante Felder
    (angelehnt an das vorgeschlagene Schema image_license_*).
    """

    license_status: Verdict = Verdict.YELLOW
    license_uri: str | None = None
    license_label: str | None = None
    license_field: str | None = None      # ausgelesener Copyright-/Rights-Text
    acquire_url: str | None = None         # Kauf-/Lizenzseite -> starkes RED
    credit_text: str | None = None
    creator: str | None = None
    supplier: str | None = None            # erkannte Agentur / Lieferant
    source_domain: str | None = None
    source_page: str | None = None
    phash: str | None = None               # dHash 64 bit (hex)
    sha1: str | None = None
    c2pa_status: str | None = None         # valid | invalid | absent | unavailable
    watermark_score: float | None = None


class SourceInfo(BaseModel):
    """Beschreibung der Bildquelle."""

    mode: str                      # url | upload | node
    origin_url: str | None = None  # Original-Bild-URL
    source_page: str | None = None
    filename: str | None = None
    mime: str | None = None
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    node_id: str | None = None
    repository: str | None = None
    node_render_url: str | None = None


class CheckReport(BaseModel):
    """Gesamtergebnis einer Prüfung."""

    verdict: Verdict
    # 4-stufige Ergebnis-Skala (Endnutzer): unproblematisch | zu_pruefen |
    # nicht_messbar | problematisch. Die feinere `verdict`-Ampel bleibt darunter.
    category: str = "nicht_messbar"
    category_label: str = "Nicht messbar"
    confidence: float = Field(ge=0.0, le=1.0)
    headline: str
    recommendation: str
    signals: list[CheckSignal] = Field(default_factory=list)
    fields: ExtractedFields = Field(default_factory=ExtractedFields)
    source: SourceInfo
    image_data_uri: str | None = None  # verkleinertes Anzeigebild (base64)
    external_used: bool = False
    checked_at: str | None = None


class RepositoryInfo(BaseModel):
    id: str
    label: str
    base_url: str


class RepositoryList(BaseModel):
    repositories: list[RepositoryInfo]
    default: str
