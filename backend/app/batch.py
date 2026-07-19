"""Batch-Prüfung von edu-sharing-Nodes.

Zwei Eingänge:
  * Sammlung: rekursive Traversierung (children/collections + references),
    Dedup über originalId.
  * CSV: Zeilen ``node_id;repository`` (repository optional -> Default).

Jobs laufen asynchron in einem ThreadPool (große Sammlungen dauern Minuten) und
werden per Job-ID gepollt. Ergebnisse sind reine Metadaten — es werden **keine
Bilddaten** gehalten (kein image_data_uri, nichts auf Disk); die Bild-Bytes eines
Nodes werden direkt nach seiner Prüfung freigegeben.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

from . import edu_sharing
from .config import REPOSITORIES, Repository
from .image_source import ImageLoadError, load_from_node
from .pipeline import run_pipeline
from .schemas import SignalStatus, Verdict

_log = logging.getLogger(__name__)

MAX_DEPTH_DEFAULT = 8
MAX_NODES_DEFAULT = 500
_MAX_JOBS = 50

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="batch")
_JOBS: "dict[str, BatchJob]" = {}
_LOCK = threading.Lock()

# Abgeschlossene Jobs werden hier als JSON abgelegt — die Historie übersteht
# damit Neustarts (Ergebnisse sind reine Metadaten, keine Bilddaten).
_PERSIST_DIR = Path(__file__).resolve().parent.parent / "data" / "batch_jobs"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Datenmodelle
# --------------------------------------------------------------------------
@dataclass
class BatchItemResult:
    node_id: str
    repository: str
    verdict: str = ""            # red | yellow | green | error
    category: str = ""           # problematisch|zu_pruefen|nicht_messbar|unproblematisch
    confidence: float = 0.0
    headline: str = ""
    license_label: str = ""
    license_uri: str = ""
    creator: str = ""
    credit_text: str = ""
    supplier: str = ""
    acquire_url: str = ""
    source_page: str = ""
    source_domain: str = ""
    sha1: str = ""
    phash: str = ""
    render_url: str = ""
    reasons: str = ""
    error: str = ""
    checked_at: str = ""


@dataclass
class BatchJob:
    id: str
    kind: str                    # collection | csv
    source: str
    allow_external: bool
    status: str = "pending"      # pending | running | done | error
    total: int | None = None     # None solange Traversierung läuft
    done: int = 0
    results: list[BatchItemResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None
    created_at: str = field(default_factory=_now)
    finished_at: str | None = None


# --------------------------------------------------------------------------
# Job-Store
# --------------------------------------------------------------------------
def _register(job: BatchJob) -> None:
    with _LOCK:
        _JOBS[job.id] = job
        if len(_JOBS) > _MAX_JOBS:
            finished = [
                j for j in _JOBS.values() if j.status in ("done", "error")
            ]
            finished.sort(key=lambda j: j.finished_at or j.created_at)
            for old in finished[: len(_JOBS) - _MAX_JOBS]:
                _JOBS.pop(old.id, None)


def get_job(job_id: str) -> BatchJob | None:
    with _LOCK:
        job = _JOBS.get(job_id)
    if job is not None:
        return job
    return _load_persisted(job_id)


_ITEM_FIELDS = {f.name for f in fields(BatchItemResult)}


def _persist(job: BatchJob) -> None:
    """Abgeschlossenen Job atomar als JSON ablegen (Historie über Neustarts)."""
    try:
        _PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        payload = to_json(job)
        tmp = _PERSIST_DIR / f"{job.id}.json.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _PERSIST_DIR / f"{job.id}.json")
    except Exception:  # noqa: BLE001 — Persistenz darf den Job nicht kippen
        _log.exception("Batch-Job %s konnte nicht persistiert werden", job.id)


def _load_persisted(job_id: str) -> BatchJob | None:
    if not job_id.isalnum():  # IDs sind Hex — schließt Pfad-Tricks aus
        return None
    path = _PERSIST_DIR / f"{job_id}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        info = payload.get("job") or {}
        job = BatchJob(
            id=info.get("job_id") or job_id,
            kind=info.get("kind", ""),
            source=info.get("source", ""),
            allow_external=False,
            status=info.get("status", "done"),
            total=info.get("total"),
            done=info.get("done", 0),
            truncated=bool(info.get("truncated")),
            warnings=list(info.get("warnings") or []),
            error=info.get("error"),
            created_at=info.get("created_at") or "",
        )
        job.finished_at = info.get("finished_at")
        job.results = [
            BatchItemResult(**{k: v for k, v in r.items() if k in _ITEM_FIELDS})
            for r in payload.get("results") or []
        ]
        return job
    except Exception:  # noqa: BLE001
        _log.exception("Persistierter Batch-Job %s nicht lesbar", job_id)
        return None


def list_jobs() -> list[dict]:
    """Alle bekannten Jobs (laufende + persistierte Historie), neueste zuerst."""
    with _LOCK:
        mem = list(_JOBS.values())
    infos = {j.id: status(j) for j in mem}
    if _PERSIST_DIR.exists():
        for path in _PERSIST_DIR.glob("*.json"):
            jid = path.stem
            if jid in infos:
                continue
            try:
                info = (json.loads(path.read_text(encoding="utf-8")).get("job")) or {}
            except Exception:  # noqa: BLE001
                continue
            if info.get("job_id"):
                infos[info["job_id"]] = info
    return sorted(infos.values(), key=lambda i: i.get("created_at") or "", reverse=True)


# --------------------------------------------------------------------------
# Traversierung
# --------------------------------------------------------------------------
def collect_collection_items(
    repo: Repository, root_id: str, auth_header: str | None,
    max_depth: int, max_nodes: int,
) -> tuple[list[str], bool]:
    """DFS durch die Sammlungshierarchie -> deduplizierte Content-Node-IDs.
    Returns (node_ids, truncated)."""
    seen_coll: set[str] = set()
    seen_node: set[str] = set()
    items: list[str] = []
    frontier: list[tuple[str, int]] = [(root_id.strip(), 0)]

    while frontier:
        cid, depth = frontier.pop()
        if cid in seen_coll or depth > max_depth:
            continue
        seen_coll.add(cid)

        for ref in edu_sharing.list_collection_references(repo, cid, auth_header):
            oid = edu_sharing.reference_original_id(ref)
            if oid and oid not in seen_node:
                seen_node.add(oid)
                items.append(oid)
                if len(items) >= max_nodes:
                    return items, True

        for sub in edu_sharing.list_subcollections(repo, cid, auth_header):
            sid = (sub.get("ref") or {}).get("id")
            if sid:
                frontier.append((sid, depth + 1))

    return items, False


# --------------------------------------------------------------------------
# CSV-Eingabe
# --------------------------------------------------------------------------
_HEADER_TOKENS = {"node_id", "nodeid", "node", "id"}


def parse_csv(content: str, default_repo: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Parst ``node_id;repository`` (Semikolon; Komma als Fallback)."""
    items: list[tuple[str, str]] = []
    warnings: list[str] = []
    first_content_line = True
    for i, raw in enumerate(content.splitlines(), start=1):
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("#"):
            continue  # Leer- und Kommentarzeilen (auch die # im Template) überspringen
        parts = line.split(";") if ";" in line else line.split(",")
        node_id = parts[0].strip()
        if not node_id:
            continue
        # Header-Erkennung an der ERSTEN Inhaltszeile (nicht an physischer Zeile 1 —
        # das Template hat Kommentarzeilen davor).
        if first_content_line and node_id.lower() in _HEADER_TOKENS:
            first_content_line = False
            continue
        first_content_line = False
        repo_id = parts[1].strip() if len(parts) > 1 and parts[1].strip() else default_repo
        if repo_id not in REPOSITORIES:
            warnings.append(f"Zeile {i}: unbekanntes Repository '{repo_id}' → Default '{default_repo}'.")
            repo_id = default_repo
        items.append((node_id, repo_id))
    return items, warnings


def csv_template() -> str:
    return (
        "# Muster: eine Zeile pro Node, Semikolon-getrennt.\n"
        "# Spalte 1 = Node-ID (Pflicht), Spalte 2 = Repository-ID "
        "(optional: prod|staging, sonst Default).\n"
        "node_id;repository\n"
        "abcd1234-0000-0000-0000-000000000000;prod\n"
        "efgh5678-0000-0000-0000-000000000000;staging\n"
    )


# --------------------------------------------------------------------------
# Ausführung
# --------------------------------------------------------------------------
def start_collection_batch(
    repo: Repository, node_id: str, auth_header: str | None, allow_external: bool,
    max_depth: int, max_nodes: int, risk_hub,
) -> BatchJob:
    job = BatchJob(
        id=uuid.uuid4().hex[:12], kind="collection",
        source=f"Sammlung {node_id} @ {repo.id}", allow_external=allow_external,
    )
    _register(job)
    _EXECUTOR.submit(
        _run_collection, job, repo, node_id, auth_header, max_depth, max_nodes, risk_hub
    )
    return job


def start_csv_batch(
    items: list[tuple[str, str]], warnings: list[str], allow_external: bool,
    auth_map: dict[str, str | None], risk_hub,
) -> BatchJob:
    job = BatchJob(
        id=uuid.uuid4().hex[:12], kind="csv",
        source=f"CSV ({len(items)} Einträge)", allow_external=allow_external,
        total=len(items), warnings=list(warnings),
    )
    _register(job)
    _EXECUTOR.submit(_run_items, job, items, auth_map, risk_hub)
    return job


def _set(job: BatchJob, **fields) -> None:
    """Job-Felder konsistent unter dem gemeinsamen Lock setzen."""
    with _LOCK:
        for k, v in fields.items():
            setattr(job, k, v)


def _run_collection(job, repo, node_id, auth_header, max_depth, max_nodes, risk_hub):
    try:
        _set(job, status="running")
        ids, truncated = collect_collection_items(
            repo, node_id, auth_header, max_depth, max_nodes
        )
        _set(job, truncated=truncated, total=len(ids))
        _process(job, [(nid, repo.id) for nid in ids], {repo.id: auth_header}, risk_hub)
    except edu_sharing.EduSharingError as exc:
        _set(job, status="error", error=str(exc))
    except Exception:  # noqa: BLE001
        _log.exception("Batch-Job %s abgebrochen", job.id)
        _set(job, status="error", error="Unerwarteter Fehler bei der Sammlungs-Prüfung.")
    finally:
        _finish(job)


def _run_items(job, items, auth_map, risk_hub):
    try:
        _set(job, status="running")
        _process(job, items, auth_map, risk_hub)
    except Exception:  # noqa: BLE001
        _log.exception("Batch-Job %s abgebrochen", job.id)
        _set(job, status="error", error="Unerwarteter Fehler bei der CSV-Prüfung.")
    finally:
        _finish(job)


def _finish(job: BatchJob) -> None:
    with _LOCK:
        if job.status == "running":
            job.status = "done"
        job.finished_at = _now()
    _persist(job)  # außerhalb des Locks — to_json/status locken selbst


def _process(job, items, auth_map, risk_hub):
    for node_id, repo_id in items:
        repo = REPOSITORIES.get(repo_id)
        if repo is None:
            res = BatchItemResult(
                node_id=node_id, repository=repo_id, verdict="error",
                error=f"Unbekanntes Repository '{repo_id}'.", checked_at=_now(),
            )
        else:
            # Netzwerk-I/O außerhalb des Locks; nur die Mutation ist synchronisiert.
            res = _check_node(repo, node_id, auth_map.get(repo_id), job.allow_external, risk_hub)
        with _LOCK:
            job.results.append(res)
            job.done += 1


def _check_node(repo, node_id, auth_header, allow_external, risk_hub) -> BatchItemResult:
    render_url = repo.render_url_template.format(node_id=node_id)
    img = None
    try:
        img = load_from_node(repo, node_id, auth_header)
        report = run_pipeline(img, allow_external, risk_hub, include_preview=False)
        return _to_item(node_id, repo.id, render_url, report)
    except (ImageLoadError, edu_sharing.EduSharingError) as exc:
        return BatchItemResult(
            node_id=node_id, repository=repo.id, render_url=render_url,
            verdict="error", error=str(exc), checked_at=_now(),
        )
    except Exception as exc:  # noqa: BLE001
        return BatchItemResult(
            node_id=node_id, repository=repo.id, render_url=render_url,
            verdict="error", error=f"Fehler: {exc}", checked_at=_now(),
        )
    finally:
        img = None  # Bild-Bytes freigeben — kein Bild bleibt auf dem Server


def _to_item(node_id, repo_id, render_url, report) -> BatchItemResult:
    f = report.fields
    reasons = "; ".join(
        s.summary for s in report.signals
        if s.status == SignalStatus.DONE and s.verdict in (Verdict.RED, Verdict.GREEN)
    )
    return BatchItemResult(
        node_id=node_id, repository=repo_id, render_url=render_url,
        verdict=report.verdict.value, category=report.category,
        confidence=report.confidence,
        headline=report.headline,
        license_label=f.license_label or "", license_uri=f.license_uri or "",
        creator=f.creator or "", credit_text=f.credit_text or "",
        supplier=f.supplier or "", acquire_url=f.acquire_url or "",
        source_page=f.source_page or "", source_domain=f.source_domain or "",
        sha1=f.sha1 or "", phash=f.phash or "",
        reasons=reasons, checked_at=report.checked_at or _now(),
    )


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------
_CSV_COLUMNS = [
    "node_id", "repository", "verdict", "category", "confidence", "headline",
    "license_label", "license_uri", "creator", "credit_text", "supplier",
    "acquire_url", "source_page", "source_domain", "sha1", "phash",
    "render_url", "reasons", "error", "checked_at",
]


def to_csv(job: BatchJob) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\n")
    writer.writerow(_CSV_COLUMNS)
    for r in _results_snapshot(job):
        row = asdict(r)
        row["confidence"] = f"{r.confidence:.2f}"
        writer.writerow([row[c] for c in _CSV_COLUMNS])
    return buf.getvalue()


def to_json(job: BatchJob) -> dict:
    return {"job": status(job), "results": [asdict(r) for r in _results_snapshot(job)]}


def _results_snapshot(job: BatchJob) -> list[BatchItemResult]:
    """Konsistente Kopie der Ergebnisliste (Writer läuft in einem anderen Thread)."""
    with _LOCK:
        return list(job.results)


def _category_of(r: BatchItemResult) -> str:
    """4-stufige Kategorie eines Ergebnisses; leitet sie für Alt-Daten ohne
    gespeicherte Kategorie aus Verdict/Belegen ab."""
    if r.category:
        return r.category
    if r.verdict == "error":
        return "fehler"
    if r.verdict == "red":
        return "problematisch"
    if r.verdict == "green":
        return "unproblematisch"
    # yellow: mit konkretem Warnhinweis -> zu prüfen, sonst nicht messbar
    return "zu_pruefen" if (r.supplier or r.acquire_url) else "nicht_messbar"


def status(job: BatchJob) -> dict:
    with _LOCK:
        snapshot = list(job.results)
        info = {
            "job_id": job.id, "kind": job.kind, "source": job.source,
            "status": job.status, "total": job.total, "done": job.done,
            "truncated": job.truncated, "warnings": list(job.warnings),
            "error": job.error, "created_at": job.created_at,
            "finished_at": job.finished_at,
        }
    counts = {"red": 0, "yellow": 0, "green": 0, "error": 0}
    # 4-stufige Ergebnis-Skala (Endnutzer-Sicht) parallel zur Ampel.
    kategorien = {"problematisch": 0, "zu_pruefen": 0, "nicht_messbar": 0,
                  "unproblematisch": 0, "fehler": 0}
    for r in snapshot:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
        k = _category_of(r)
        kategorien[k] = kategorien.get(k, 0) + 1
    info["counts"] = counts
    info["kategorien"] = kategorien
    return info


def to_report(job: BatchJob) -> str:
    results = _results_snapshot(job)
    by_cat: dict[str, list[BatchItemResult]] = {
        "problematisch": [], "zu_pruefen": [], "nicht_messbar": [],
        "unproblematisch": [], "fehler": [],
    }
    for r in results:
        by_cat[_category_of(r)].append(r)

    lines = [
        "# Batch-Prüfbericht — Bild-Lizenz-Check",
        "",
        f"- **Quelle:** {job.source}",
        f"- **Erstellt:** {job.created_at}",
        f"- **Abgeschlossen:** {job.finished_at or '—'}",
        f"- **Status:** {job.status}",
        f"- **Geprüft:** {len(results)}"
        + (f" / {job.total}" if job.total is not None else ""),
        "",
        "| 🔴 problematisch | 🟠 zu prüfen | 🟡 nicht messbar | 🟢 unproblematisch | ⚠ Fehler |",
        "|---:|---:|---:|---:|---:|",
        f"| {len(by_cat['problematisch'])} | {len(by_cat['zu_pruefen'])} | "
        f"{len(by_cat['nicht_messbar'])} | {len(by_cat['unproblematisch'])} | "
        f"{len(by_cat['fehler'])} |",
        "",
        "**Deutung:** *problematisch* = Warnsignal ohne Gegenbeleg (nicht ausliefern); "
        "*zu prüfen* = Warnhinweis, aber nicht eindeutig (redaktionell klären); "
        "*nicht messbar* = kein belastbares Signal (Default-Deny, keine automatische "
        "Freigabe); *unproblematisch* = Positivnachweis einer freien Lizenz.",
        "",
    ]
    if job.truncated:
        lines.append("> ⚠ Node-Limit erreicht — Sammlung nur teilweise geprüft.\n")
    if job.warnings:
        lines.append("**Hinweise:** " + "; ".join(job.warnings) + "\n")

    def _block(title: str, rows: list[BatchItemResult]) -> None:
        if not rows:
            return
        lines.append(f"## {title} ({len(rows)})")
        lines.append("")
        for r in rows:
            detail = r.error or r.reasons or r.headline
            lines.append(f"- `{r.node_id}` ({r.repository}) — {detail}  \n  {r.render_url}")
        lines.append("")

    _block("🔴 Problematisch — lizenzpflichtig/geschützt", by_cat["problematisch"])
    _block("🟠 Zu prüfen — Warnhinweis, redaktionell klären", by_cat["zu_pruefen"])
    _block("🟡 Nicht messbar — kein Signal (Default-Deny)", by_cat["nicht_messbar"])
    _block("⚠ Fehler bei der Prüfung", by_cat["fehler"])
    _block("🟢 Unproblematisch — Freigabe möglich", by_cat["unproblematisch"])

    lines.append("---")
    lines.append("*Technische Indizien, keine Rechtsberatung. Default-Deny bei Unklarheit.*")
    return "\n".join(lines)
