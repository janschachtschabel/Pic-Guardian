"""Speist redaktionell BESTÄTIGTE Problem-Funde eines Batch-Laufs in den
Risikospeicher: lädt das Bild jedes problematischen Nodes, berechnet
SHA-1 + dHash und legt beide ab. Danach erkennt Prüfschritt c05 jede
Wiederverwendung desselben Bilds — auch auf Seiten ohne Credit/Metadaten.

WICHTIG: Nur nach redaktioneller Durchsicht des Protokolls ausführen —
unbestätigte False Positives würden sich sonst auf alle künftigen Prüfungen
fortpflanzen.

Aufruf (aus backend/): python ../tools/seed_risk_hub.py <outdir> [limit]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent / "backend"))

from app.config import REPOSITORIES              # noqa: E402
from app.image_source import load_from_node      # noqa: E402
from app.risk_hub import RiskHub, hashes_for     # noqa: E402

ROOT = TOOLS.parent


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    outdir = ROOT / sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    jsonl = outdir / "ergebnisse.jsonl"

    hub = RiskHub()
    problems = []
    for line in jsonl.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("kategorie") == "problematisch":
            problems.append(r)
    if limit:
        problems = problems[:limit]
    print(f"Problematische Nodes im Lauf: {len(problems)} | "
          f"Risikospeicher vorher: {hub.size} Einträge")

    added = dups = errors = 0
    for i, r in enumerate(problems, 1):
        nid, repo_id = r["node_id"], r.get("repo", "prod")
        try:
            img = load_from_node(REPOSITORIES[repo_id], nid, None)
            sha1, phash = hashes_for(img.data, img.pil())
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"  FEHLER {nid[:8]}: {exc}")
            continue
        if hub.match_sha1(sha1):
            dups += 1
            continue
        lieferant = r.get("lieferant") or "Agentur"
        hub.add(
            phash=phash, sha1=sha1,
            note=f"Batch {outdir.name}: {lieferant} auf {r.get('quell_domain', '?')} "
                 f"(Node {nid})",
            source=f"batch:{outdir.name}",
        )
        added += 1
        if i % 25 == 0:
            print(f"  {i}/{len(problems)}")

    print(f"Fertig: {added} neu, {dups} bereits vorhanden, {errors} Fehler. "
          f"Risikospeicher jetzt: {hub.size} Einträge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
