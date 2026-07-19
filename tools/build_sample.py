"""Baut eine reproduzierbare Zufallsstichprobe von 5000 Node-IDs aus
data_30k_base.csv (Spalte 1 = properties.sys:node-uuid) und schreibt eine
Batch-CSV (node_id;repository) für die Prüfung. Repo = prod (alle Nodes stammen
aus redaktion.openeduhub.net).
"""

from __future__ import annotations

import csv
import random
import re
import sys
from pathlib import Path

csv.field_size_limit(50_000_000)  # sehr große Beschreibungsfelder

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data_30k_base.csv"
OUT_DIR = ROOT / "batch_lauf_5000"
OUT_DIR.mkdir(exist_ok=True)
SAMPLE = OUT_DIR / "batch_5000.csv"

SEED = 20260716        # fest -> reproduzierbar/nachvollziehbar
N = 5000
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def main() -> int:
    ids: list[str] = []
    seen: set[str] = set()
    with SRC.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter=";")
        header = next(reader, None)
        if not header or "node-uuid" not in header[0]:
            print("Unerwarteter Header:", header[0] if header else None)
            return 1
        for row in reader:
            if not row:
                continue
            nid = row[0].strip()
            if _UUID.match(nid) and nid not in seen:
                seen.add(nid)
                ids.append(nid)

    print(f"Gültige, eindeutige Node-UUIDs gefunden: {len(ids)}")
    if len(ids) < N:
        print(f"WARNUNG: nur {len(ids)} < {N} verfügbar — nehme alle.")
    rng = random.Random(SEED)
    sample = rng.sample(ids, min(N, len(ids)))

    with SAMPLE.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";", lineterminator="\n")
        w.writerow(["node_id", "repository"])
        for nid in sample:
            w.writerow([nid, "prod"])

    print(f"Stichprobe geschrieben: {SAMPLE} ({len(sample)} Zeilen, Seed={SEED})")
    print("Beispiele:", sample[:3])
    return 0


if __name__ == "__main__":
    sys.exit(main())
