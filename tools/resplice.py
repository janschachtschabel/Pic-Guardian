"""Prüft gezielt die vom Kalibrierungs-Fix betroffenen Nodes (die mit einem
Agentur-/Kaufsignal auf der Fundseite, d.h. non-empty 'probleme') mit dem
korrigierten Code erneut und ersetzt ihre Einträge in ergebnisse.jsonl.
Die übrigen Nodes sind vom Fix nicht betroffen und bleiben unverändert.

Aufruf (aus backend/): python ../tools/resplice.py <outdir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import run_batch  # noqa: E402  (setzt selbst den backend-Pfad)

run_batch.ALLOW_EXTERNAL = len(sys.argv) > 2 and sys.argv[2] == "1"

ROOT = TOOLS.parent
OUT = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "batch_lauf_5000")
JSONL = OUT / "ergebnisse.jsonl"


def main() -> int:
    records = {}
    order = []
    for line in JSONL.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        records[r["node_id"]] = r
        if r["node_id"] not in order:
            order.append(r["node_id"])

    affected = [nid for nid in order if records[nid].get("probleme")]
    print(f"Betroffene Nodes (mit Fundseiten-Problemsignal): {len(affected)}")

    changed = 0
    for i, nid in enumerate(affected, 1):
        repo = records[nid].get("repo", "prod")
        new = run_batch._check(nid, repo)
        if new["verdict"] != records[nid]["verdict"]:
            changed += 1
        records[nid] = new
        if i % 25 == 0:
            print(f"  {i}/{len(affected)}")

    with JSONL.open("w", encoding="utf-8") as fh:
        for nid in order:
            fh.write(json.dumps(records[nid], ensure_ascii=False) + "\n")
    print(f"Neu geschrieben. Verdict geändert bei {changed}/{len(affected)} Nodes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
