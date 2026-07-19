"""Batch-Prüfung der 5000-Node-Stichprobe über die echte Prüf-Pipeline.

Nutzt exakt dieselbe Logik wie das Batch-Feature (load_from_node + run_pipeline),
erfasst aber pro Node die vollständige Signal-Liste für die Statistik. Ergebnisse
werden zeilenweise nach <outdir>/ergebnisse.jsonl geschrieben (crash-sicher +
fortsetzbar).

Aufruf (aus backend/ mit venv):
    python ../tools/run_batch.py <workers> <extern:0|1> <outdir>
Beispiele:
    python ../tools/run_batch.py 10 0 batch_lauf_5000          # ohne externe Dienste
    python ../tools/run_batch.py 10 1 batch_lauf_5000_extern   # mit Commons + Openverse
"""

from __future__ import annotations

import csv
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import image_source          # noqa: E402
from app.config import REPOSITORIES    # noqa: E402
from app.edu_sharing import EduSharingError  # noqa: E402
from app.image_source import ImageLoadError  # noqa: E402
from app.pipeline import run_pipeline  # noqa: E402
from app.risk_hub import RiskHub       # noqa: E402
from app.schemas import SignalStatus, Verdict  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "batch_lauf_5000" / "batch_5000.csv"   # gemeinsame Stichprobe

_KAT = {"red": "problematisch", "yellow": "nicht_bestimmbar", "green": "unproblematisch"}
_hub = RiskHub()
_write_lock = threading.Lock()
_counter = {"done": 0}

# in main() gesetzt
ALLOW_EXTERNAL = False
JSONL: Path = SAMPLE


def _check(node_id: str, repo_id: str) -> dict:
    repo = REPOSITORIES[repo_id]
    render = repo.render_url_template.format(node_id=node_id)
    img = None
    try:
        img = image_source.load_from_node(repo, node_id, None)
        rep = run_pipeline(img, allow_external=ALLOW_EXTERNAL, risk_hub=_hub, include_preview=False)
        f = rep.fields
        problems = [
            {"check": s.id, "label": s.label, "summary": s.summary}
            for s in rep.signals
            if s.status == SignalStatus.DONE and s.verdict == Verdict.RED
        ]
        unklar = [
            {"check": s.id, "summary": s.summary}
            for s in rep.signals
            if s.status == SignalStatus.DONE and s.verdict == Verdict.YELLOW
        ]
        # positive/informative externe Befunde separat festhalten (für den Vergleich)
        extern = [
            {"check": s.id, "verdict": s.verdict.value, "summary": s.summary}
            for s in rep.signals
            if s.external and s.status == SignalStatus.DONE
            and s.verdict in (Verdict.GREEN, Verdict.RED, Verdict.INFO)
        ]
        return {
            "node_id": node_id, "repo": repo_id,
            "kategorie": _KAT.get(rep.verdict.value, rep.verdict.value),
            # 4-stufige Ergebnis-Skala (Quelle der Wahrheit: Backend-Aggregation)
            "category": rep.category,
            "verdict": rep.verdict.value, "confidence": rep.confidence,
            "headline": rep.headline, "probleme": problems, "unklar": unklar,
            "extern": extern, "external_used": rep.external_used,
            "lizenz": f.license_label or "", "lizenz_uri": f.license_uri or "",
            "lieferant": f.supplier or "", "urheber": f.creator or "",
            "quelle": f.source_page or "", "quell_domain": f.source_domain or "",
            "acquire_url": f.acquire_url or "", "sha1": f.sha1 or "",
            "mime": rep.source.mime or "", "render_url": render, "fehler": None,
        }
    except (ImageLoadError, EduSharingError) as exc:
        return {"node_id": node_id, "repo": repo_id, "kategorie": "fehler",
                "verdict": "error", "headline": "", "probleme": [], "unklar": [],
                "extern": [], "render_url": render, "fehler": str(exc)[:200]}
    except Exception as exc:  # noqa: BLE001
        return {"node_id": node_id, "repo": repo_id, "kategorie": "fehler",
                "verdict": "error", "headline": "", "probleme": [], "unklar": [],
                "extern": [], "render_url": render,
                "fehler": f"{type(exc).__name__}: {str(exc)[:180]}"}
    finally:
        img = None


def _run(node_id: str, repo_id: str, total: int) -> None:
    res = _check(node_id, repo_id)
    with _write_lock:
        with JSONL.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(res, ensure_ascii=False) + "\n")
        _counter["done"] += 1
        n = _counter["done"]
    if n % 100 == 0 or n == total:
        print(f"  {n}/{total} ({100*n/total:.0f}%) — {node_id[:8]} {res['kategorie']}", flush=True)


def main() -> int:
    global ALLOW_EXTERNAL, JSONL
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    ALLOW_EXTERNAL = len(sys.argv) > 2 and sys.argv[2] == "1"
    outdir = ROOT / (sys.argv[3] if len(sys.argv) > 3 else "batch_lauf_5000")
    outdir.mkdir(exist_ok=True)
    JSONL = outdir / "ergebnisse.jsonl"

    rows = list(csv.reader(SAMPLE.open(encoding="utf-8"), delimiter=";"))[1:]
    items = [(r[0].strip(), r[1].strip() if len(r) > 1 and r[1].strip() else "prod") for r in rows if r]

    done: set[str] = set()
    if JSONL.exists():
        for line in JSONL.open(encoding="utf-8"):
            try:
                done.add(json.loads(line)["node_id"])
            except Exception:  # noqa: BLE001
                pass
    todo = [(n, r) for n, r in items if n not in done]
    _counter["done"] = len(done)
    total = len(items)
    print(f"OUT={outdir.name} extern={ALLOW_EXTERNAL} | Gesamt {total} | "
          f"bereits {len(done)} | offen {len(todo)} | Workers {workers}", flush=True)

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for n, r in todo:
            ex.submit(_run, n, r, total)
    print(f"\nFertig: {total} Nodes in {(time.monotonic()-t0)/60:.1f} min -> {JSONL}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
