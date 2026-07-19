"""FastAPI-App — HTTP-Schnittstelle des Prüfdienstes."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from . import __version__, batch, image_source
from .checks import ALL_CHECKS
from .config import DEFAULT_REPOSITORY, REPOSITORIES, SETTINGS
from .edu_sharing import EduSharingError, basic_auth_header
from .image_source import ImageLoadError
from .pipeline import run_pipeline
from .risk_hub import RiskHub, hashes_for
from .schemas import CheckReport, RepositoryInfo, RepositoryList

app = FastAPI(
    title="Bild-Lizenz-Check",
    version=__version__,
    description="Prüfdienst zur Erkennung problematischer Bildlizenzen / "
    "Urheberrechtsprobleme (Default-Deny).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(SETTINGS.cors_origins),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

RISK_HUB = RiskHub()


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "risk_hub_size": RISK_HUB.size,
        "checks": [c.id for c in ALL_CHECKS],
    }


@app.get("/api/repositories", response_model=RepositoryList)
def repositories() -> RepositoryList:
    return RepositoryList(
        repositories=[
            RepositoryInfo(id=r.id, label=r.label, base_url=r.base_url)
            for r in REPOSITORIES.values()
        ],
        default=DEFAULT_REPOSITORY,
    )


@app.post("/api/check", response_model=CheckReport)
def check(
    mode: str = Form(..., description="url | upload | node"),
    image_url: str | None = Form(None),
    node_id: str | None = Form(None),
    repository: str = Form(DEFAULT_REPOSITORY),
    source_page: str | None = Form(None),
    allow_external: bool | None = Form(None),
    es_user: str | None = Form(None),
    es_password: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> CheckReport:
    try:
        image = _load_image(
            mode, image_url, node_id, repository, source_page, es_user, es_password, file
        )
    except (ImageLoadError, EduSharingError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Einzelprüfung: externe Dienste standardmäßig AN (mit Frist im Pipeline-Lauf).
    # Der Client kann es explizit überschreiben.
    if allow_external is None:
        allow_external = SETTINGS.external_default_single
    return run_pipeline(image, allow_external=allow_external, risk_hub=RISK_HUB)


def _load_image(
    mode, image_url, node_id, repository, source_page, es_user, es_password, file
):
    if mode == "url":
        if not image_url:
            raise ImageLoadError("Bitte eine Bild-URL angeben.")
        return image_source.load_from_url(image_url, source_page=source_page)

    if mode == "upload":
        if file is None:
            raise ImageLoadError("Bitte eine Datei hochladen.")
        # Begrenzt lesen (nicht die ganze Datei ungeprüft in den RAM).
        data = file.file.read(SETTINGS.max_image_bytes + 1)
        if len(data) > SETTINGS.max_image_bytes:
            raise ImageLoadError("Datei überschreitet die Größenbeschränkung.")
        return image_source.load_from_upload(file.filename, data)

    if mode == "node":
        if not node_id:
            raise ImageLoadError("Bitte eine Node-ID angeben.")
        repo = REPOSITORIES.get(repository)
        if repo is None:
            raise ImageLoadError(f"Unbekanntes Repository '{repository}'.")
        auth = basic_auth_header(es_user, es_password) if es_user and es_password else None
        return image_source.load_from_node(repo, node_id, auth)

    raise ImageLoadError(f"Ungültiger Modus '{mode}'.")


# --- Risikospeicher-Pflege (Option 8 / 12: bestätigte Fälle einspeisen) -----
@app.post("/api/risk-hub")
def risk_hub_add(
    phash: str | None = Form(None),
    sha1: str | None = Form(None),
    note: str = Form(""),
) -> dict:
    if not phash and not sha1:
        raise HTTPException(422, "phash oder sha1 erforderlich.")
    # Nur Hex zulassen — ein nicht-hex-Eintrag würde sonst den Abgleich stören.
    for name, val in (("phash", phash), ("sha1", sha1)):
        if val is not None:
            v = val.strip()
            if not v or not all(c in "0123456789abcdefABCDEF" for c in v):
                raise HTTPException(422, f"{name} muss ein Hex-Wert sein.")
    entry = RISK_HUB.add(
        phash=phash.strip() if phash else None,
        sha1=sha1.strip() if sha1 else None,
        note=note, source="manual",
    )
    return {"added": entry, "risk_hub_size": RISK_HUB.size}


@app.delete("/api/risk-hub/{hash_value}")
def risk_hub_remove(hash_value: str) -> dict:
    removed = RISK_HUB.remove(hash_value)
    return {"removed": removed, "risk_hub_size": RISK_HUB.size}


@app.post("/api/review/confirm-node")
def review_confirm_node(
    node_id: str = Form(...),
    repository: str = Form(DEFAULT_REPOSITORY),
    note: str = Form(""),
    es_user: str | None = Form(None),
    es_password: str | None = Form(None),
) -> dict:
    """Review-Bestätigung (Option 12): lädt das Bild des Nodes, berechnet
    SHA-1 + dHash und legt beide als bestätigten Problemfall in den
    Risikospeicher — Wiederverwendungen desselben Bilds (auch ohne Credit auf
    anderen Seiten) werden damit künftig per pHash erkannt."""
    repo = REPOSITORIES.get(repository)
    if repo is None:
        raise HTTPException(422, f"Unbekanntes Repository '{repository}'.")
    auth = basic_auth_header(es_user, es_password) if es_user and es_password else None
    try:
        img = image_source.load_from_node(repo, node_id, auth)
    except (ImageLoadError, EduSharingError) as exc:
        raise HTTPException(422, str(exc)) from exc
    sha1, phash = hashes_for(img.data, img.pil())
    if RISK_HUB.match_sha1(sha1):
        return {"added": None, "duplicate": True, "risk_hub_size": RISK_HUB.size}
    entry = RISK_HUB.add(
        phash=phash, sha1=sha1,
        note=note or f"Review-bestätigt: Node {node_id} ({repository})",
        source="review",
    )
    return {"added": entry, "duplicate": False, "risk_hub_size": RISK_HUB.size}


# --- Batch-Prüfung (Sammlung / CSV) -----------------------------------------
@app.get("/api/batch/template", response_class=Response)
def batch_template() -> Response:
    """Muster-CSV für den Datei-Batch (node_id;repository)."""
    return Response(content=batch.csv_template(), media_type="text/plain; charset=utf-8")


@app.get("/api/batch/jobs")
def batch_jobs() -> dict:
    """Job-Historie: laufende Jobs + persistierte abgeschlossene Läufe.
    (Muss vor der dynamischen {job_id}-Route registriert sein.)"""
    return {"jobs": batch.list_jobs()}


@app.post("/api/batch/collection")
def batch_collection(
    node_id: str = Form(..., description="Node-ID der (Wurzel-)Sammlung"),
    repository: str = Form(DEFAULT_REPOSITORY),
    allow_external: bool = Form(False),
    max_depth: int = Form(batch.MAX_DEPTH_DEFAULT),
    max_nodes: int = Form(batch.MAX_NODES_DEFAULT),
    es_user: str | None = Form(None),
    es_password: str | None = Form(None),
) -> dict:
    repo = REPOSITORIES.get(repository)
    if repo is None:
        raise HTTPException(422, f"Unbekanntes Repository '{repository}'.")
    auth = basic_auth_header(es_user, es_password) if es_user and es_password else None
    job = batch.start_collection_batch(
        repo, node_id, auth, allow_external,
        max(1, min(max_depth, 20)), max(1, min(max_nodes, 5000)), RISK_HUB,
    )
    return batch.status(job)


@app.post("/api/batch/csv")
def batch_csv(
    file: UploadFile | None = File(None),
    csv_text: str | None = Form(None),
    default_repository: str = Form(DEFAULT_REPOSITORY),
    allow_external: bool = Form(False),
    es_user: str | None = Form(None),
    es_password: str | None = Form(None),
) -> dict:
    if default_repository not in REPOSITORIES:
        raise HTTPException(422, f"Unbekanntes Repository '{default_repository}'.")
    if file is not None:
        raw = file.file.read(5_000_000 + 1)  # CSV-Obergrenze ~5 MB
        if len(raw) > 5_000_000:
            raise HTTPException(413, "CSV-Datei überschreitet die Größenbeschränkung.")
        content = raw.decode("utf-8-sig", errors="replace")
    elif csv_text:
        content = csv_text
    else:
        raise HTTPException(422, "CSV-Datei (file) oder csv_text erforderlich.")
    items, warnings = batch.parse_csv(content, default_repository)
    if not items:
        raise HTTPException(422, "Keine gültigen Node-IDs in der Eingabe.")
    if len(items) > 5000:
        items = items[:5000]
        warnings.append("Eingabe auf die ersten 5000 Zeilen begrenzt.")
    auth = basic_auth_header(es_user, es_password) if es_user and es_password else None
    # Credentials NUR an das gewählte Default-Repository — nicht an fremde Repos
    # in der CSV (sonst gingen z.B. Staging-Zugangsdaten an den Prod-Host).
    auth_map = {default_repository: auth}
    job = batch.start_csv_batch(items, warnings, allow_external, auth_map, RISK_HUB)
    return batch.status(job)


@app.get("/api/batch/{job_id}")
def batch_status(job_id: str) -> dict:
    return batch.status(_require_job(job_id))


@app.get("/api/batch/{job_id}/export.json")
def batch_export_json(job_id: str) -> dict:
    return batch.to_json(_require_job(job_id))


@app.get("/api/batch/{job_id}/export.csv", response_class=Response)
def batch_export_csv(job_id: str) -> Response:
    job = _require_job(job_id)
    body = "﻿" + batch.to_csv(job)  # BOM -> Excel öffnet UTF-8 korrekt
    return Response(
        content=body, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="bildcheck-{job_id}.csv"'},
    )


@app.get("/api/batch/{job_id}/report", response_class=Response)
def batch_report(job_id: str) -> Response:
    job = _require_job(job_id)
    return Response(content=batch.to_report(job), media_type="text/markdown; charset=utf-8")


def _require_job(job_id: str) -> "batch.BatchJob":
    job = batch.get_job(job_id)
    if job is None:
        raise HTTPException(404, f"Batch-Job '{job_id}' nicht gefunden.")
    return job


# --- Statisches Frontend (Single-Container-Deployment) ----------------------
# Wird NUR gemountet, wenn ein gebautes Frontend vorliegt (im Docker-Image nach
# /app/static kopiert, Pfad via BILDCHECK_STATIC_DIR). Muss NACH allen /api-
# Routen stehen, damit diese Vorrang vor dem Catch-all "/" behalten. Im Dev-
# Betrieb ist die Variable leer -> API-only, das Frontend läuft über `ng serve`.
_STATIC_DIR = os.environ.get("BILDCHECK_STATIC_DIR", "").strip()
if _STATIC_DIR and Path(_STATIC_DIR).is_dir():
    # html=True liefert index.html für "/" und ist damit für die tab-basierte
    # SPA (kein Client-Routing) ausreichend.
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="frontend")
