"""HTTP-Integrationstests der FastAPI-Endpunkte — netzfrei & deterministisch.

Nutzt FastAPI ``TestClient`` (App läuft in-process, unabhängig von einem
laufenden uvicorn). Die einzige Netz-/IO-Grenze der Batch-Ausführung
(``load_from_node``) wird gemockt; alles andere ist die echte Pipeline.

Fokus: der Ergebnis-Contract inkl. der 4-stufigen Kategorie
(``category`` / ``category_label`` bei /api/check; ``kategorien`` + category-
Spalte bei /api/batch/*). Ausführen (im backend/-Verzeichnis):
    ./.venv/Scripts/python -m tests.test_api
"""

from __future__ import annotations

import io
import shutil
import sys
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import batch, image_source  # noqa: E402
from app.main import app  # noqa: E402

_VALID_CATEGORIES = {"unproblematisch", "zu_pruefen", "nicht_messbar", "problematisch"}


def _jpeg(copyright_text: str | None = None, color=(120, 120, 120)) -> bytes:
    img = Image.new("RGB", (96, 72), color)
    buf = io.BytesIO()
    if copyright_text:
        exif = img.getexif()
        exif[0x8298] = copyright_text  # Copyright
        img.save(buf, format="JPEG", exif=exif)
    else:
        img.save(buf, format="JPEG")
    return buf.getvalue()


def _upload(client: TestClient, data: bytes, *, allow_external: bool) -> dict:
    """POST /api/check im Upload-Modus. allow_external=False hält den Lauf
    netzfrei (nur Commons/Openverse sind extern, und die entfallen so)."""
    r = client.post(
        "/api/check",
        data={"mode": "upload", "allow_external": str(allow_external).lower()},
        files={"file": ("x.jpg", data, "image/jpeg")},
    )
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
    return r.json()


def _wait_done(client: TestClient, job_id: str, timeout_s: float = 8.0) -> dict:
    """Pollt den Batch-Status bis 'done'/'error' (gemockter Lauf → schnell)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        js = client.get(f"/api/batch/{job_id}").json()
        if js["status"] in ("done", "error"):
            return js
        time.sleep(0.05)
    return client.get(f"/api/batch/{job_id}").json()


def main() -> int:  # noqa: C901 — linearer Testtreiber, bewusst flach
    failures = 0

    def expect(name, actual, want):
        nonlocal failures
        ok = actual == want
        print(f"  [{'OK ' if ok else 'FAIL'}] {name}: {actual!r} (erwartet {want!r})")
        if not ok:
            failures += 1

    # Persistenz in ein Temp-Verzeichnis umlenken -> keine Artefakte im Repo.
    orig_persist = batch._PERSIST_DIR
    tmp_persist = Path(tempfile.mkdtemp(prefix="bildcheck_jobs_"))
    batch._PERSIST_DIR = tmp_persist

    try:
        _run_cases(app, expect)
    finally:
        batch._PERSIST_DIR = orig_persist
        shutil.rmtree(tmp_persist, ignore_errors=True)

    print(f"\nErgebnis: {'ALLE OK' if failures == 0 else str(failures) + ' FEHLGESCHLAGEN'}")
    return 1 if failures else 0


def _run_cases(app, expect) -> None:
    with TestClient(app) as client:
        print("1) /api/check Upload (sauberes Bild, extern aus) -> nicht_messbar")
        d = _upload(client, _jpeg(None), allow_external=False)
        expect("clean-category", d.get("category"), "nicht_messbar")
        expect("clean-label", d.get("category_label"), "Nicht messbar")
        expect("clean-verdict", d.get("verdict"), "yellow")

        print("2) /api/check Upload (Agentur-EXIF) -> problematisch (Ampel->Kategorie via HTTP)")
        d = _upload(client, _jpeg("© 2024 Getty Images"), allow_external=False)
        expect("agency-category", d.get("category"), "problematisch")
        expect("agency-verdict", d.get("verdict"), "red")

        print("3) /api/check: category immer aus der gültigen 4er-Skala + Label gesetzt")
        d = _upload(client, _jpeg(None), allow_external=False)
        expect("category-valid", d.get("category") in _VALID_CATEGORIES, True)
        expect("label-nonempty", bool(d.get("category_label")), True)

        print("4) /api/batch/template -> CSV-Muster mit Kopfzeile")
        r = client.get("/api/batch/template")
        expect("template-status", r.status_code, 200)
        expect("template-header", "node_id;repository" in r.text, True)

        print("5) /api/batch/jobs -> Liste")
        r = client.get("/api/batch/jobs")
        expect("jobs-status", r.status_code, 200)
        expect("jobs-islist", isinstance(r.json().get("jobs"), list), True)

        print("6) /api/batch/csv (load_from_node gemockt) -> kategorien + category-Export")
        # Netz-Grenze mocken: liefert ein Agentur-EXIF-Bild als Upload-Kontext,
        # sodass die echte Pipeline RED/problematisch produziert — ohne Netz.
        orig_loader = batch.load_from_node
        batch.load_from_node = lambda repo, node_id, auth=None: (
            image_source.load_from_upload("mock.jpg", _jpeg("© Getty Images"))
        )
        try:
            r = client.post(
                "/api/batch/csv",
                data={"csv_text": "11111111-2222-3333-4444-555555555555;prod",
                      "default_repository": "prod"},
            )
            expect("csv-accepted", r.status_code, 200)
            job_id = r.json()["job_id"]
            js = _wait_done(client, job_id)
            expect("csv-done", js["status"], "done")
            kat = js.get("kategorien") or {}
            expect("csv-kat-problematisch", kat.get("problematisch"), 1)
            expect("csv-kat-sum", sum(kat.values()), 1)

            # Export enthält die category-Spalte + den Wert
            csv_txt = client.get(f"/api/batch/{job_id}/export.csv").text
            header = csv_txt.splitlines()[0]
            expect("export-csv-header", "category" in header, True)
            expect("export-csv-value", "problematisch" in csv_txt, True)
            jrows = client.get(f"/api/batch/{job_id}/export.json").json()["results"]
            expect("export-json-category", jrows[0].get("category"), "problematisch")
        finally:
            batch.load_from_node = orig_loader


if __name__ == "__main__":
    raise SystemExit(main())
