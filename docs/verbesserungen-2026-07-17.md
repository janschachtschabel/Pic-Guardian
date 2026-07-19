# Verbesserungs-Roadmap Bild-Lizenz-Check

Stand: 2026-07-17 · Grundlage: 5000er-Batch (Seed 20260716, Prod), Läufe A (lokal) und B (mit externen Diensten), zwei Scoring-Nachläufe.

---

## 1. Erkenntnisse aus dem Batch, die ins Scoring eingeflossen sind

1. **Agentur-Nachweis schlägt Selbstauskunft** (`_SELF_REPORT_GREEN` in `aggregate.py`):
   Die Repo-Deklaration („Gemeinfrei / copyright-frei") und die Domain-Whitelist sind
   Selbstauskünfte. Sie können einen starken externen Negativbeleg (Agentur-Credit auf
   der Fundseite) nicht mehr zum „Widerspruch → Gelb" abschwächen → ROT.
2. **Seitenweite Lizenz ≠ Bildlizenz** (`license_scope` in `c08_page_structured.py`):
   Eine seitenweite CC-Angabe (z. B. der CC-BY-NC-ND-Hinweis für den Artikeltext auf
   bpb.de) belegt die Lizenz eines eingebetteten Agenturbilds nicht. Nur eine Lizenz,
   die per schema.org **ImageObject direkt am geprüften Bild** hängt, gilt als
   bildgebundener Positivbeleg und kann einen echten Widerspruch erzeugen.
3. **Host-Reputation ist bewusst KEIN Signal**: Die 114 Agentur-Funde stammen fast
   ausschließlich von „neutral wirkenden" Institutions-/Rundfunkseiten (bpb.de 31×,
   Deutsche Welle 36×, Landeszentralen, Deutschlandfunk, Bundesbank, Goethe-Institut).
   Das Tool bewertet den Seiteninhalt, nicht den Ruf der Domain — genau deshalb werden
   diese Fälle erkannt.

## 2. Verifikation: Was bringen die externen Dienste?

**Versuchsaufbau** (kontrolliertes A/B-Experiment): identische 5000er-Stichprobe,
Lauf A nur lokale Checks, Lauf B zusätzlich Wikimedia Commons (SHA-1) + Openverse.

| Messgröße | Ergebnis |
|---|---|
| Commons-SHA-1-Treffer | **0** von ~4928 abgefragten Nodes |
| Openverse-Treffer | 1064 — alle **INFO** (per Design ohne Ampel-Einfluss) |
| Kategorie-Wechsel A→B | **1** (transienter Netzwerkfehler, kein inhaltlicher) |
| Laufzeit-Mehraufwand | ~32 min (v. a. Openverse-Drosselung 0,75 s/Anfrage) |

**Strukturelle Erklärung** (warum das kein Zufall ist):
- Commons-SHA-1 findet nur **bit-identische** Dateien. WLO-Vorschaubilder sind
  re-encodiert/skaliert → SHA-1 kann prinzipiell nicht treffen. Ein pHash-Abgleich
  gegen Commons wäre der echte Test, wird von der Commons-API aber nicht angeboten.
- Openverse hat **keine Reverse-Image-/Hash-Suche**, nur Textsuche → kann nie das
  konkrete Bild belegen, nur ähnlich betitelte Werke finden.

**Fazit/Empfehlung:** Für kuratierte Repo-Inhalte im Massenlauf: externe Dienste
**standardmäßig aus** (bleiben Opt-in für Einzelprüfungen, wo ein Commons-Treffer
bei Original-Uploads möglich ist). Die Klassifikationsarbeit leisten
`declared_license` + `page_credit`/`page_structured`.

**Weitergehende Verifikation der Gesamtpipeline** (empfohlen): Ground-Truth-Stichprobe
— z. B. 50 grüne + 50 nicht bestimmbare Nodes manuell prüfen → Precision/Recall der
Ampel. Das misst auch die Rate **unentdeckter** Agenturbilder (blinder Fleck), die
kein automatischer Vergleich zweier Läufe sichtbar machen kann.

## 2a. Umsetzungsstand (2026-07-17)

Alle **kostenfreien** Vorschläge sind implementiert. Übersicht:

| Vorschlag | Status | Ort |
|---|---|---|
| #1 Agentur-Asset-Muster auf Fundseiten-Bild-URLs | ✅ | `c09_page_credit.py`, `c02_domain_filename.py` (STRONG/WEAK-Split) |
| #2 Risk-Hub-Seeding + Review-Bestätigung | ✅ | `tools/seed_risk_hub.py`, `POST /api/review/confirm-node`, UI Review-Queue |
| #3 IPTC/XMP-Herkunftsfelder schärfen | ✅ | `c03_embedded_metadata.py` (SpecialInstructions, DocumentID) |
| #4 Presse-/Rundfunk-Domain-Prior (+ strenger Modus) | ✅ | `NEWS_PRESS_DOMAINS`, `BILDCHECK_STRICT_NEWS` |
| #5 srcset/og:image-Auflösung | ✅ | `c09_page_credit.py` (Neufassung) |
| #6 Bildnachweis-Seite folgen | ✅ | `c12_credit_page.py` |
| #7 Wayback-Machine-Fallback | ✅ | `image_source.py` (`BILDCHECK_WAYBACK`) |
| App: Review-Queue (UI) | ✅ | `batch.component.*` |
| App: persistente Batch-Historie | ✅ | `batch.py` (`data/batch_jobs/`), `GET /api/batch/jobs` |
| P4 Reverse-Image-Suche (Google Vision/TinEye) | ⏸ bewusst NICHT | kostenpflichtig — nur als Opt-in dokumentiert |
| P3 #8 Watermark-Template-Matching | ⏸ übersprungen | OCR-Check (c06) deckt den Kern; keine Template-Bibliothek vorhanden |
| P3 #9 CLIP-Bildklassifikator | ⏸ übersprungen | bräuchte torch (~2 GB), widerspricht dem Leichtgewicht-Design; als Ampel-Signal ungeeignet (unscharf, nicht erklärbar) |

Neue/erweiterte Prüfschritte + Regressionstests in `tests/test_smoke.py` (Fälle 24–27).

## 3. Neue Erkennungsmethoden — Vorschläge mit Bewertung (Ausgangslage)

Bewertungsskala: Nutzen/Präzision/Aufwand jeweils hoch–mittel–gering.

### P1 — sofort lohnend (frei, lokal)

| # | Vorschlag | Was es erkennt | Präzision | Aufwand | Bewertung |
|---|---|---|---|---|---|
| 1 | **Agentur-Dateinamen-Muster auf Fundseiten-Bild-URLs ausweiten** | `gettyimages-123…`, `istockphoto-…`, `shutterstock_…`, `AdobeStock_…` etc. im `src` des Ziel-`<img>` auf der Fundseite — nicht nur im Repo-Dateinamen wie bisher (`c02`). Muster ergänzen: dpa `urn:newsml:dpa.com`, `imago\d{8,}`, `picture-alliance`/`pa_`-Pfade, `epa\d{8}`, Reuters `RTX/RTS\w+`. Bei ID-Treffer conf 0.8 (statt 0.7) — eine Getty-Asset-ID ist quasi beweisend. | hoch | gering | **umsetzen** — schließt den Fall „Agenturbild ohne sichtbaren Credit, aber Original-Dateiname erhalten" |
| 2 | **Risk-Hub-Seeding**: pHashes der redaktionell **bestätigten** Agentur-Funde importieren | Wiederverwendung derselben Bilder überall — auch auf Seiten ohne Credit/Metadaten. Das ist die einzige freie Methode, die den „neutralen Seiten"-Blindfleck systematisch verkleinert: einmal identifiziert → überall wiedererkannt (Hamming-Distanz). | hoch | gering (Import-Skript; Infrastruktur existiert) | **umsetzen**, aber nur mit bestätigten Fällen füttern (sonst False-Positive-Propagation) |
| 3 | **IPTC/XMP-Herkunftsfelder schärfen** (`c03`) | Agentur-Terme gezielt in `Credit`, `Source`, `SpecialInstructions` (dpa/Getty schreiben dort Lizenzauflagen), XMP `plus:Licensor`, `xmpRights:WebStatement`, dpa-`DocumentID` (`urn:newsml:dpa.com`) | hoch (wenn Metadaten nicht gestrippt) | gering | **umsetzen** — wirkt v. a. auf Repo-Originale, die noch volle Metadaten tragen |

### P2 — sinnvoll, mit Trade-off

| # | Vorschlag | Was es erkennt | Präzision | Aufwand | Bewertung |
|---|---|---|---|---|---|
| 4 | **News-/Rundfunk-Domain-Prior** (Erweiterung `site_policy`): kuratierte Liste (dw.com, tagesschau.de, br.de, wdr.de, spiegel.de, …) → GELB-Signal „Fundseite ist Presse-/Rundfunkangebot — Fotos dort überwiegend Agenturmaterial" | Uncredited-Agenturbilder auf Presseseiten als *Verdacht* statt still grün/nb | mittel (Sender haben auch Eigenmaterial → nie allein rot) | gering | **als Opt-in-„strenger Modus"**: Im Batch hätten aktuell **241 grüne Nodes** (br.de, dw.com, wdr.de …) nur die Repo-Deklaration als Beleg — der Prior würde sie zu „Verdacht" abstufen. Operativ viel Prüfaufwand, aber ehrlich gegenüber Default-Deny. Entscheidung ist Policy, nicht Technik |
| 5 | **`srcset`/`og:image`-Auflösung** in `c09` | bessere Bild-Bindung (mehr „targeted"-Treffer statt „seitenweit"), weniger Fehlzuordnung bei responsiven Bildern | mittel | gering–mittel | lohnt als Genauigkeits-Upgrade |
| 6 | **Bildnachweis-/Impressum-Seiten folgen** (`/bildnachweis`, „Bildquellen"-Links) | zentrale Credit-Seiten, wie sie Bildungsseiten oft führen | mittel–hoch | mittel | guter zweiter Schritt nach P1 |
| 7 | **Wayback-Machine-Fallback** (Availability API, frei) für tote/veränderte Fundseiten | rettet einen Teil der 73 Fehler-Nodes + Credits von umgebauten Seiten | mittel | mittel | nice-to-have; reduziert „fehler"/„nb" |

### P3 — geringe Priorität

| # | Vorschlag | Bewertung |
|---|---|---|
| 8 | Watermark-Template-Matching (Getty/Shutterstock-Muster zusätzlich zu OCR) | Wasserzeichen-Bilder sind im Repo selten; OCR-Check deckt den Kern ab |
| 9 | Lokaler Bildklassifikator („Pressefoto-Stil" via CLIP) | experimentell, unscharf, erklärungsschwach — nicht als Ampel-Signal geeignet, höchstens als Priorisierungs-Hint für die Review-Queue |

### P4 — externe Dienste, die den blinden Fleck wirklich schließen (Opt-in, teils kostenpflichtig)

Der verbleibende blinde Fleck: Agenturbild **ohne** Credit, **ohne** Metadaten,
**ohne** Original-Dateinamen auf neutraler Seite → kein freies Signal möglich.
Nur Reverse-Image-Suche hilft:

| Dienst | Kosten | Bewertung |
|---|---|---|
| **Google Cloud Vision „Web Detection"** | ~1,50 USD / 1000 Bilder | bester Preis/Leistung: liefert Seiten mit demselben Bild → Treffer auf gettyimages.com & Co. = harter Beleg. Bild geht an Google → strikt Opt-in |
| **TinEye API** | ~200 USD / 5000 Suchen | präziseste Reverse-Suche, aber teuer im Massenlauf |
| **Bing Visual Search** | Azure-Kontingent | Mittelweg, ToS prüfen |
| **Getty/Agentur-Katalog-Bestätigung** (z. B. Getty-oEmbed bei erkannter Asset-ID aus P1-#1) | frei | nur Verifizierer für ID-Treffer, kein Finder |

**Empfohlene Strategie statt Massenlauf:** selektiv — nur Nodes ohne jedes Signal
UND mit Risiko-Prior (News-Domain, fotografischer Inhalt) extern prüfen. Bei ~50–100
Kandidaten pro 5000er-Batch kostet das Cents statt Dollars und bleibt DSGVO-sauber
dokumentierbar (Opt-in-Schalter existiert bereits).

## 4. App-Verbesserungen jenseits der Erkennung

| Vorschlag | Nutzen | Aufwand |
|---|---|---|
| **Review-Queue** (Option 12): Problem-Protokoll in der UI abarbeiten, Bestätigen/Verwerfen; Bestätigte automatisch in den Risk-Hub | operativ der wichtigste Baustein — macht aus Batch-Funden dauerhafte Erkennungsleistung (speist #2) | mittel |
| **Persistente Batch-Historie** (SQLite statt In-Memory-JobStore) | Läufe überleben Neustarts, Vergleiche über Zeit | mittel |
| **Prüfdienst-Endpoint für den Crawler** dokumentieren (Check beim Ingest, bevor falsche Deklaration ins Repo gelangt) | verhindert die Fehlerklasse an der Quelle statt nachträglich | gering (API existiert; Doku + Beispiel) |
| **Prüf-Flag ins Repo zurückschreiben** (eigenes Property/`ccm:editorial_checklist`; via edu-sharing-API, immer aufs Original schreiben + Read-Back) | Redaktion sieht Befund direkt am Node | mittel; Opt-in, Schreibrechte nötig |
| `lizenz`-Feld im Batch-Protokoll vollständig befüllen (zeigt derzeit nicht alle Deklarationsquellen) | kosmetisch, bessere Protokolle | gering |

## 5. Empfohlene Reihenfolge

1. **#1 Dateinamen-Muster auf Fundseiten-URLs** (Stunden, sofortiger Erkennungsgewinn)
2. **Review-Queue + #2 Risk-Hub-Seeding** (macht die 114 Funde dauerhaft wirksam)
3. **#3 IPTC-Schärfung** (Stunden)
4. **#4 strenger Modus / Domain-Prior** als Konfigurationsoption — Policy-Entscheidung
5. **Selektive externe Reverse-Suche** (P4) für die Rest-Fälle ohne Signal — Opt-in
6. Ground-Truth-Stichprobe (§2) zur Messung der tatsächlichen Restfehlerrate
