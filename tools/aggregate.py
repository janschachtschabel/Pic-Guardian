"""Wertet ergebnisse.jsonl aus und erzeugt die nachvollziehbaren Ergebnis-Dateien:
  * ergebnisse.csv              — pro Node (Semikolon, für Nachbearbeitung)
  * problematisch_protokoll.csv — nur problematische Nodes mit Begründung
  * statistik.md                — Statistik (Kategorien + welches Problem wie oft)
Kann auch auf Teildaten laufen (Zwischenstand).
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "batch_lauf_5000")
JSONL = OUT / "ergebnisse.jsonl"

# Check-ID -> Problemart (jeder Check steht für eine Problemkategorie)
PROBLEMART = {
    "declared_license": "Deklarierte Lizenz geschützt/Agentur (Repository)",
    "domain_filename": "Agentur-/Stock-Domain oder Dateinamensmuster",
    "embedded_metadata": "Agentur-/Kaufsignal in Bild-Metadaten (EXIF/IPTC/XMP)",
    "page_structured": "Agentur/Kaufseite in schema.org der Fundseite",
    "page_credit": "Agentur im sichtbaren Bildnachweis der Fundseite",
    "credit_page": "Agentur auf zentraler Bildnachweis-Seite der Domain",
    "site_policy": "Nutzungsvorbehalt der Fundseite (robots/TDM)",
    "perceptual_hash": "Treffer im internen Risikospeicher",
    "watermark_ocr": "Sichtbares Agentur-Wasserzeichen",
    "c2pa": "Agentur-C2PA-Manifest",
    "commons_sha1": "Externer Abgleich",
    "openverse": "Externer Abgleich",
}


def load() -> list[dict]:
    if not JSONL.exists():
        return []
    out = []
    for line in JSONL.open(encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def main() -> int:
    rows = load()
    n = len(rows)
    if not n:
        print("Keine Ergebnisse.")
        return 1

    # 4-stufige Ergebnis-Skala (identisch zur App): bevorzugt die im Backend
    # berechnete `category`; Fallback für Altdaten aus verdict/Belegen.
    _CATS = {"unproblematisch", "zu_pruefen", "nicht_messbar", "problematisch"}

    def kat2(r: dict) -> str:
        if r["kategorie"] == "fehler" or r.get("verdict") == "error":
            return "fehler"
        c = r.get("category")
        if c in _CATS:
            return c
        v = r.get("verdict")
        if v == "red":
            return "problematisch"
        if v == "green":
            return "unproblematisch"
        return "zu_pruefen" if r.get("probleme") else "nicht_messbar"

    for r in rows:
        r["_kat"] = kat2(r)
    kat = Counter(r["_kat"] for r in rows)
    probl = [r for r in rows if r["_kat"] == "problematisch"]
    verdacht = [r for r in rows if r["_kat"] == "zu_pruefen"]
    unklar = [r for r in rows if r["_kat"] == "nicht_messbar"]
    fehler = [r for r in rows if r["_kat"] == "fehler"]
    # alle Nodes mit mindestens einem RED-Signal (problematisch + verdacht) —
    # das sind die eigentlich prüfenswerten Fälle fürs Protokoll.
    mit_problem = [r for r in rows if r.get("probleme")]

    # Problem-Häufigkeit (jedes RED-Signal zählt; ein Node kann mehrere haben)
    import re

    def norm(s: str) -> str:
        return re.sub(r":\s*.*$", "", s or "").strip() or "(ohne)"

    # Problem-Signale über ALLE Nodes zählen — auch wenn ein einzelnes schwaches
    # RED die Gesamt-Ampel (noch) nicht auf ROT kippt (Default-Deny -> YELLOW).
    by_check = Counter()       # Prüfschritt -> Anzahl RED-Signale
    by_summary = Counter()     # konkreter Befund -> Anzahl
    by_supplier = Counter()
    nodes_with_problem = 0
    for r in rows:
        probs = r.get("probleme", [])
        if probs:
            nodes_with_problem += 1
        for p in probs:
            by_check[p["check"]] += 1
            by_summary[norm(p["summary"])] += 1
        if r.get("lieferant"):
            by_supplier[r["lieferant"].lower()] += 1

    # Quellseiten (Fundseiten-Domains) der prüfenswerten Fälle (problematisch + zu prüfen)
    by_domain = Counter(
        (r.get("quell_domain") or "(keine Fundseite)")
        for r in rows if r["_kat"] in ("problematisch", "zu_pruefen")
    )

    # "Nicht messbar": dominanter Grund je Node (echte Signal-Zusammenfassung)
    unklar_reasons = Counter()
    for r in unklar:
        us = r.get("unklar", [])
        if not us:
            unklar_reasons["Kein Signal - Default-Deny (keine Metadaten/Lizenz)"] += 1
        else:
            # dominanter Grund = erstes Yellow-Signal (Pipeline-Reihenfolge:
            # deklarierte Lizenz zuerst); voller Text -> © vs. individuell bleibt sichtbar
            unklar_reasons[us[0]["summary"][:90]] += 1

    def fehler_typ(msg: str) -> str:
        m = msg or ""
        if "nicht gefunden" in m:
            return "Node nicht gefunden (404)"
        if "kein darstellbares Bild" in m.lower():
            return "Kein darstellbares Bild im Node"
        if "Bild-Download" in m or "Bild konnte nicht" in m:
            return "Bild-Download fehlgeschlagen"
        if "Größenbeschränkung" in m or "größer als" in m:
            return "Bild zu groß"
        if "401" in m or "verweigert" in m:
            return "Zugriff verweigert (401)"
        return (m.split(":")[0][:45] or "sonstiger Fehler")
    fehler_arten = Counter(fehler_typ(r.get("fehler")) for r in fehler)

    # Externe Befunde (nur im extern-Lauf gefüllt)
    commons_green = sum(1 for r in rows for e in r.get("extern", [])
                        if e["check"] == "commons_sha1" and e["verdict"] == "green")
    openverse_info = sum(1 for r in rows for e in r.get("extern", [])
                         if e["check"] == "openverse" and e["verdict"] == "info")
    extern_used = sum(1 for r in rows if r.get("external_used"))

    # --- ergebnisse.csv (pro Node) ---
    with (OUT / "ergebnisse.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";", lineterminator="\n")
        w.writerow(["node_id", "kategorie", "verdict", "confidence", "headline",
                    "probleme", "lizenz", "lieferant", "urheber", "quelle",
                    "render_url", "fehler"])
        for r in rows:
            probleme = " | ".join(f"{p['check']}: {p['summary']}" for p in r.get("probleme", []))
            w.writerow([r["node_id"], r["_kat"], r.get("verdict", ""),
                        f"{r.get('confidence', 0):.2f}", r.get("headline", ""),
                        probleme, r.get("lizenz", ""), r.get("lieferant", ""),
                        r.get("urheber", ""), r.get("quelle", ""),
                        r.get("render_url", ""), r.get("fehler") or ""])

    # --- problematisch_protokoll.csv ---
    with (OUT / "problematisch_protokoll.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";", lineterminator="\n")
        w.writerow(["node_id", "gesamt_ampel", "render_url", "anzahl_gruende",
                    "gruende", "lieferant", "acquire_url", "deklarierte_lizenz", "fundseite"])
        for r in sorted(mit_problem, key=lambda x: (x["verdict"] != "red", -len(x.get("probleme", [])))):
            gruende = " | ".join(f"[{p['check']}] {p['summary']}" for p in r.get("probleme", []))
            w.writerow([r["node_id"], r["_kat"], r.get("render_url", ""),
                        len(r.get("probleme", [])), gruende, r.get("lieferant", ""),
                        r.get("acquire_url", ""), r.get("lizenz", ""), r.get("quelle", "")])

    # --- statistik.md ---
    def pct(x):
        return f"{100*x/n:.1f}%"

    lines = [
        "# Batch-Prüfstatistik — 5000 Prod-Inhalte",
        "",
        "- **Quelle:** `data_30k_base.csv` (21.277 gültige Node-UUIDs), Zufallsstichprobe **5000** (Seed 20260716)",
        f"- **Repository:** prod (redaktion.openeduhub.net) · **Externe Dienste:** "
        f"{'AN (Commons + Openverse)' if extern_used else 'aus (nur lokale/freie Checks)'}",
        f"- **Geprüft:** {n}",
        "",
        "## 1. Gesamtverteilung (4-stufige Ergebnis-Skala)",
        "",
        "| Kategorie | Anzahl | Anteil |",
        "|---|---:|---:|",
        f"| 🟢 unproblematisch (Positivnachweis freie Lizenz) | {kat.get('unproblematisch',0)} | {pct(kat.get('unproblematisch',0))} |",
        f"| 🟡 nicht messbar (kein Signal — Default-Deny) | {kat.get('nicht_messbar',0)} | {pct(kat.get('nicht_messbar',0))} |",
        f"| 🟠 zu prüfen (Warnhinweis, nicht eindeutig) | {kat.get('zu_pruefen',0)} | {pct(kat.get('zu_pruefen',0))} |",
        f"| 🔴 problematisch (starkes Warnsignal ohne Gegenbeleg) | {kat.get('problematisch',0)} | {pct(kat.get('problematisch',0))} |",
        f"| ⚠ Fehler (nicht prüfbar) | {kat.get('fehler',0)} | {pct(kat.get('fehler',0))} |",
        "",
        f"**Zu prüfen + problematisch: {len(probl)+len(verdacht)}** — "
        f"davon {len(probl)} klar **problematisch** (Agentur ohne Gegenbeleg) und "
        f"{len(verdacht)} **zu prüfen** (überwiegend: Repository deklariert *frei*, "
        f"aber die Fundseite nennt eine **Agentur** → mutmaßlich falsch deklarierte "
        f"Lizenz). Insgesamt {sum(by_check.values())} Problem-Signale.",
        "",
        "## 2. Welches Problem wie oft? (RED-Signale je Prüfschritt, über ALLE Nodes)",
        "",
        "| Prüfschritt / Problemart | Fundzahl |",
        "|---|---:|",
    ]
    for check, cnt in by_check.most_common():
        lines.append(f"| {PROBLEMART.get(check, check)} | {cnt} |")
    if not by_check:
        lines.append("| _keine RED-Signale gefunden_ | 0 |")
    lines += ["", "## 3. Häufigste konkrete Befunde (Top 15)", "",
              "| Befund | Anzahl |", "|---|---:|"]
    for summ, cnt in by_summary.most_common(15):
        lines.append(f"| {summ[:90]} | {cnt} |")
    if by_supplier:
        lines += ["", "## 4. Erkannte Agenturen/Lieferanten (Top 15)", "",
                  "| Lieferant | Anzahl |", "|---|---:|"]
        for sup, cnt in by_supplier.most_common(15):
            lines.append(f"| {sup} | {cnt} |")
    lines += ["", "## 5. Quellseiten der prüfenswerten Fälle (Fundseiten-Domain, Top 20)",
              "", "Domain der Fundseite (`ccm:wwwurl`), von der der Inhalt stammt — "
              "über alle problematischen + zu-prüfenden Nodes.", "",
              "| Fundseiten-Domain | Fälle |", "|---|---:|"]
    for dom, cnt in by_domain.most_common(20):
        lines.append(f"| {dom} | {cnt} |")
    if not by_domain:
        lines.append("| _keine_ | 0 |")
    lines += ["", "## 6. Nicht messbar — Gründe (dominanter Grund je Node)", "",
              "| Grund | Anzahl |", "|---|---:|"]
    for reason, cnt in unklar_reasons.most_common():
        lines.append(f"| {reason[:90]} | {cnt} |")
    if fehler:
        lines += ["", "## 7. Fehler (technisch nicht prüfbar)", "",
                  "| Fehlerart | Anzahl |", "|---|---:|"]
        for art, cnt in fehler_arten.most_common():
            lines.append(f"| {art or '—'} | {cnt} |")
    if extern_used:
        lines += ["", "## 8. Externe Dienste (dieser Lauf)", "",
                  f"- Nodes mit genutztem externen Dienst: **{extern_used}**",
                  f"- Wikimedia-Commons SHA-1-Positivtreffer (GREEN): **{commons_green}**",
                  f"- Openverse-Recherchetreffer (INFO): **{openverse_info}**"]
    lines += ["", "---",
              "**Dateien:** `ergebnisse.csv` (alle Nodes), "
              "`problematisch_protokoll.csv` (Begründungen), "
              "`ergebnisse.jsonl` (Rohdaten), `batch_5000.csv` (Stichprobe).",
              "*Technische Indizien, keine Rechtsberatung. Default-Deny bei Unklarheit.*"]

    (OUT / "statistik.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Ausgewertet: {n} Nodes")
    print("Kategorien:", dict(kat))
    print("Problem je Check:", dict(by_check))
    print(f"Dateien geschrieben in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
