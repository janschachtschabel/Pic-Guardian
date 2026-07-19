"""Orchestrierung: ImageContext -> alle Checks -> aggregierter CheckReport.

Bewusst dünn gehalten — die Wiederverwendbarkeit als Prüfdienst liegt genau
hier: ``run_pipeline`` ist frei von HTTP-/Framework-Details.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import datetime, timezone

from .aggregate import CATEGORY_LABELS, aggregate
from .checks import ALL_CHECKS, BaseCheck, CheckContext
from .config import REPOSITORIES, SETTINGS
from .image_source import ImageContext, build_preview_data_uri
from .risk_hub import RiskHub
from .schemas import CheckReport, CheckSignal, SignalStatus, SourceInfo, Verdict

# Externe Checks werden mit Frist ausgeführt: antwortet ein Dienst nicht
# rechtzeitig, wird sein Signal auf UNAVAILABLE gesetzt und die Prüfung läuft
# weiter (kein Abbruch). Die httpx-Threads laufen im Hintergrund aus.
_DEADLINE_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ext-check")


def _run_with_deadline(check: BaseCheck, ctx: CheckContext, timeout: float) -> CheckSignal:
    fut = _DEADLINE_POOL.submit(check.run, ctx)
    try:
        return fut.result(timeout=timeout)
    except FuturesTimeout:
        return CheckSignal(
            id=check.id, label=check.label, category=check.category,
            external=check.external, status=SignalStatus.UNAVAILABLE,
            verdict=Verdict.NEUTRAL,
            summary=f"Externer Dienst antwortete nicht innerhalb von "
            f"{timeout:.0f} s — übersprungen (kein Abbruch der Prüfung).",
        )


def run_pipeline(
    image: ImageContext,
    allow_external: bool,
    risk_hub: RiskHub | None = None,
    include_preview: bool = True,
    external_timeout: float | None = None,
) -> CheckReport:
    if external_timeout is None:
        external_timeout = SETTINGS.external_timeout
    ctx = CheckContext(image=image, allow_external=allow_external, risk_hub=risk_hub)
    signals: list = []
    for check in ALL_CHECKS:
        if check.external and allow_external and external_timeout and external_timeout > 0:
            sig = _run_with_deadline(check, ctx, external_timeout)
        else:
            sig = check.run(ctx)
        signals.append(sig)
        ctx.prior_signals = signals  # spätere Checks sehen frühere Ergebnisse

    verdict, confidence, headline, recommendation, fields, category = aggregate(
        signals, image
    )
    external_used = any(
        s.external and s.status == SignalStatus.DONE for s in signals
    )

    render_url = None
    if image.mode == "node" and image.node_id and image.repository in REPOSITORIES:
        render_url = REPOSITORIES[image.repository].render_url_template.format(
            node_id=image.node_id
        )

    source = SourceInfo(
        mode=image.mode,
        origin_url=image.origin_url,
        source_page=image.source_page,
        filename=image.filename,
        mime=image.mime,
        width=image.width,
        height=image.height,
        size_bytes=image.size_bytes,
        node_id=image.node_id,
        repository=image.repository,
        node_render_url=render_url,
    )

    return CheckReport(
        verdict=verdict,
        category=category,
        category_label=CATEGORY_LABELS.get(category, category),
        confidence=confidence,
        headline=headline,
        recommendation=recommendation,
        signals=signals,
        fields=fields,
        source=source,
        image_data_uri=build_preview_data_uri(image) if include_preview else None,
        external_used=external_used,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
