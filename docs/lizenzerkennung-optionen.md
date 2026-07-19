# Erkennung lizenzpflichtiger Bilder vor der Vorschau-Auslieferung — Technische Optionen

> **Status:** Entwurf · **Stand:** 19. Juli 2026 · **Scope:** Ingestion (Crawler/Upload) + Preview-Endpoint (`preview?nodeId=`) · **Messstand:** Praxistest v4 (5000 Inhalte)

**Inhalt:** [Testcode](#testcode--reproduktion) · [Zusammenfassung](#zusammenfassung) · [Praxistest 5000](#praxistest-5000-inhalte-v4) · [Optionen 1–14](#optionen-1–14) · [Datenfelder](#datenfelder) · [API-Design](#api-design) · [Tools & Kosten](#tools--kosten) · [Rechtlicher Kontext](#rechtlicher-kontext) · [Empfehlung: Wann & womit prüfen](#empfehlung--wann--mit-welchen-methoden-prüfen) · [Stufenplan](#stufenplan) · [Quellen](#quellen)

---

## Testcode & Reproduktion

Prüfdienst + Testskripte: **`github.com/janschachtschabel/Pic-Guardian`** (FastAPI-Backend, Angular-UI, Docker). Der Praxistest ist reproduzierbar über die `tools/`-Skripte:

| Skript | Zweck |
|---|---|
| `tools/build_sample.py` | 5000er-Zufallsstichprobe aus `data_30k_base.csv` (Seed 20260716) |
| `tools/run_batch.py <workers> <extern:0\|1> <outdir>` | Batch-Lauf über die echte Pipeline (12 Prüfschritte) |
| `tools/aggregate.py <outdir>` | Statistik, Protokoll, CSV |
| `tools/seed_risk_hub.py` · `tools/compare.py` | Risikospeicher-Seeding · Lauf-Vergleich |

Originalbild-Prüfung im Lauf aktivieren: `BILDCHECK_FETCH_ORIGIN=1`.

---

## Zusammenfassung

**Ziel:** verhindern, dass lizenzpflichtige Agenturbilder als Vorschau ausgeliefert werden. **Architekturprinzip: Default-Deny** — Thumbnail nur bei nachgewiesenem `green`-Status, sonst Platzhalter-Icon oder abstraktes KI-Bild (Original nicht als Seed).

**Empirische Kernaussage (Praxistest v4, 5000 WLO-Inhalte):** Bei kuratiertem Material läuft die Verstoß-Erkennung praktisch komplett über **Fundseiten-Content**. ~99 % der Verstöße kamen aus zwei kostenlosen Methoden — sichtbarer Text-Bildnachweis (65 %) und Agentur-Muster in der Bild-URL (32 %).

> **⚠️ Bildmerkmale gehen beim Selbsthosting verloren.** Das re-gehostete WLO-Vorschaubild ist CMS-bereinigt und re-encodiert → EXIF/IPTC/XMP, C2PA und bit-genaue SHA-1 sind weg. Deshalb lieferten die reinen **Datei-Verfahren im Batch null Treffer**. Gegenmaßnahme: das **Originalbild von der Fundseite** laden und dessen Metadaten prüfen (Option 5b) — recovert Metadaten, die die Kopie verloren hat.

**Priorisierung:** Die Fundseite mitzuverarbeiten ist die wichtigste freie Maßnahme. Laut Imatag sind bei ~85 % der online publizierten Bilder die Metadaten entfernt; von den restlichen enthält nur ~1/5 Angaben zu Urheber/Rechten/Quelle. Fundseiten-Signale sind nachträglich nur per Neu-Crawl nachholbar → **beim ersten Ingestion erfassen.**

**Kosten:** Optionen 1–9 sind frei und massentauglich (Basis-Pipeline). Optionen 10–11 (Reverse-Image, Agentur-APIs) sind kostenpflichtig, nur selektiv für strittige High-Traffic-Fälle.

> **Ampel:** `red` = kein Thumbnail (Platzhalter) · `yellow` = Redaktions-Review · `green` = Thumbnail erlaubt · `unchecked` = wie `yellow`.

---

## Praxistest: 5000 Inhalte (v4)

**Versuchsaufbau:** Zufallsstichprobe von 5000 Inhalten aus dem WLO-Redaktions-Buffet (`redaktion.openeduhub.net`), gezogen aus `data_30k_base.csv` (21.277 gültige Node-UUIDs, Seed 20260716). Vollständige freie Pipeline (13 Prüfschritte, Optionen 1–9 **inkl. Originalbild-Metadaten**), Default-Modus, externe Dienste aus, 10 Worker. **Laufzeit 40,2 min.** Fundseite je Inhalt aus `ccm:wwwurl`.

### Gesamtergebnis

| Kategorie | Anzahl | Anteil |
|---|---:|---:|
| 🟢 unproblematisch (Positivnachweis freie Lizenz) | 4015 | 80,3 % |
| 🟡 nicht messbar (kein Signal — Default-Deny) | 740 | 14,8 % |
| 🔴 **problematisch** (Warnsignal ohne Gegenbeleg) | **173** | 3,5 % |
| ⚠ Fehler (technisch nicht prüfbar) | 72 | 1,4 % |

173 mutmaßliche Agenturbilder, im Repo als frei deklariert. Kategorie „zu prüfen" = 0 (jeder Agentur-Fund kippt gegen die widerlegte Selbstauskunft hart auf `problematisch`).

### Erkennung je Methode (überschneidungsfrei)

| Methode | Option | Funde | % der 173 |
|---|---|---:|---:|
| Sichtbarer Text-Bildnachweis (Agentur in Seitentext/Caption) | 2 | 113 | 65,3 % |
| URL-Muster (Agentur-Asset-ID in der Bild-URL) | 2/3 | 55 | 31,8 % |
| **Original-Metadaten der Fundseite (EXIF/IPTC)** | 5b | 4 | 2,3 % |
| schema.org `acquireLicensePage` | 1 | 1 | 0,6 % |

Zwei Fundseiten-Content-Methoden tragen 97 %. Das URL-Muster fängt Agenturbilder **ohne sichtbaren Credit**, deren Original-Dateiname erhalten blieb (Beispiel `…/imago0109043924-banner.jpg`). Die **Original-Metadaten-Methode** fängt unmarkierte Bilder, deren Kopie im Repo gestrippt ist, das Fundseiten-Original aber noch Metadaten trägt.

### Erkannte Agenturen

| Agentur | Funde |
|---|---:|
| picture alliance | 58 |
| imago | 26 |
| iStock | 18 |
| Adobe Stock | 18 |
| Getty Images | 14 |
| Shutterstock | 12 |
| dpa | 9 |
| Fotolia | 7 |
| Reuters · AFP · Zoonar | je 2 |
| ullstein bild · Depositphotos · KNA-Bild | je 1 |

### Fundseiten-Domains der Verstöße

| Domain | Fälle | Träger |
|---|---:|---|
| Deutsche Welle (p.dw.com · www.dw.com) | 36 | öffentl. Sender |
| www.bpb.de | 31 | Bundeszentrale für politische Bildung |
| Deutschlandfunk (nova · .de) | 19 | öffentl. Radio |
| lpb-bw.de · lmz-bw.de | 9 | Landeszentralen BW |
| ekd.de · katholisch.de | 6 | Kirchen |
| bbc.com · ecos-online.de · hanisauland.de | je 3 | Rundfunk / Bildungsportale |
| goethe.de · bundesbank.de · bildungsserver.de · lehrer-online.de | je 2 | Institutionen |

> **ℹ️** Verstöße stecken fast durchweg auf **neutral wirkenden öffentlichen/institutionellen Seiten**, nicht auf offensichtlichen Stock-Domains. Das Tool bewertet den **Seiteninhalt, nicht den Ruf der Domain** — und erwischt die Agenturcredits genau deshalb.

### Selbsthosting-Verlust & Original-Metadaten (neu in v4)

Die WLO-Vorschau ist eine Kopie-der-Kopie. Betroffen ist **nur die Datei-Ebene**, und nicht alles aus demselben Grund:

| Methode | 0 Treffer wegen … | Original-Fetch hilft? |
|---|---|---|
| 5 EXIF/IPTC/XMP | Metadaten beim CMS-Resizing gestrippt | **ja, stark** |
| 6 C2PA | Manifest bei Re-Encoding verloren | ja |
| 9 Commons SHA-1 | Preview re-encodiert → nie bit-identisch | ja |
| 7 Wasserzeichen | *visuell* — übersteht Re-Encoding; Material hat keine | nein |
| 8 pHash-Risikospeicher | pHash robust; Speicher nur leer | nein |

**Option 5b — Original-Metadaten:** lädt das Bild von der Fundseite (Dateiname-Abgleich, sonst `og:image`) und wertet dessen Metadaten aus. Ergebnis v4: **157 Nodes** trugen im Original wieder Metadaten (die die WLO-Kopie verloren hatte); **4 davon Agentur** — u. a. ein imago/Leemage-Bild auf `reportage.wdr.de`, das sonst als **„unproblematisch" ausgeliefert** worden wäre.

> **⚠️ Ehrliche Grenze:** Auch Fundseiten-Originale sind meist gestrippt (~85 % aller Web-Bilder). Zugewinn nur von der metadaten-erhaltenden Minderheit. Für die Ingestion (Download fällt ohnehin an) lohnt es; im Massen-Batch aus.

### Unkritisch eingestufte Fälle mit Urheberangabe

| | Anzahl |
|---|---:|
| Nicht-kritische Bilder **mit** Urheber-/Rechteangabe (gesamt) | 718 |
| davon **mit** freiem Lizenz-Beleg (CC/PD) → Attribution korrekt | 712 |
| davon **ohne** Lizenz-Beleg (Angabe da, kein Freigabe-Nachweis) → Graustufe | 6 |

Die 712 sind **zu Recht** grün: freie Bilder (425× „Gemeinfrei", 86× CC BY-SA 4.0, 73× CC BY-ND, dazu CC BY/-NC-Varianten) — der genannte Urheber ist die vorgeschriebene **Attribution**, kein Problem. Echte Graustufe: nur **6 Bilder** (Angabe vorhanden, kein Lizenz-Beleg, keine Agentur) → stehen auf „nicht messbar" (Default-Deny, keine Auslieferung). Quellen der Angabe (überlappend): sichtbarer Bildnachweis 472 · extrahierter Urheber 167 · Original-Metadaten 157.

### Kontext-Signale (gelb — „Methode aktiv", kein hartes Problem)

| Methode | Signale | Bedeutung |
|---|---:|---|
| declared_license | 746 | „individuell/keine Lizenz" → Kern der 740 nicht messbar |
| page_credit | 518 | Credit gefunden, nicht klassifizierbar |
| domain_filename | 470 | Presse-/Rundfunk-Domain-Hinweis |
| page_structured (schema.org) | 158 | strukturierte Daten da, uneindeutig |
| site_policy | 104 | Nutzungsvorbehalt (robots/TDM) |
| credit_page | 48 | Bildnachweis-Seite erreicht, keine Eskalation |
| origin_metadata | 157 | Original trug Metadaten, nicht agentur-eindeutig |
| embedded_metadata | 1 | fast alle Metadaten gestrippt |

Der Presse-Domain-Hinweis wirkt im Default nur als Kontext; `BILDCHECK_STRICT_NEWS=1` stuft diese 470 ohne Positivbeleg auf „zu prüfen" hoch (Policy-Entscheidung).

### Externe Dienste & schema.org

- **A/B externe Dienste:** Commons SHA-1 = **0 Treffer** (~4928 Nodes), Openverse = 1064 INFO (ohne Ampel-Einfluss), +32 min. Für kuratiertes Material **kein Mehrwert** → im Batch aus.
- **schema.org 0/2 Präzision:** beide `red`-Funde trafen freie Quellen (pixabay via Wayback-URL-Rewrite; PsychArchives-Schwester-Subdomain). `acquireLicensePage` ist Verweis, nicht „unfrei". **Recalibration:** `acquireLicensePage`-extern nur bei Agentur-Ziel → `red`, sonst `yellow`; Wayback-URLs vor Host-Vergleich entpacken.

### Bewertung der Methoden (Fazit)

| Bewertung | Methoden |
|---|---|
| ✅ Tragende Säule (kostenlos, hohe Ausbeute) | Option 2 — sichtbarer Bildnachweis + Agentur-URL-Muster (~99 %) |
| ✅ Positiv-Nachweis (macht 80 % grün) | Option 1/5 — deklarierte/freie Lizenz |
| ✅ Schließt Selbsthosting-Lücke | **Option 5b — Original-Metadaten der Fundseite** (fängt unmarkierte Bilder mit erhaltenem Original) |
| ◐ Kontext / Policy-Schalter | Option 3/4 — Presse-Domain-Hinweis, Site-Policy |
| ◐ Absicherung für andere Eingaben | Option 5/6/7 — Metadaten/C2PA/Wasserzeichen (Direkt-Uploads) |
| ⏳ Multiplikator, erst nach Seeding | Option 8 — Risikospeicher; die Fälle einspeisen |
| ✳ Recalibration nötig | Option 1 — acquireLicensePage-Logik (0/2) |
| ✖ Ohne Mehrwert für kuratiertes Material | Option 9 — Commons/Openverse (0 Treffer) |

### Die zwei erfolgreichsten Methoden — je ein Beispiel

**Methode 1 — Sichtbarer Text-Bildnachweis.** Beispiel Deutsche-Welle-Seite: `<figure><img src=".../klimagipfel.jpg"><figcaption>Bild: picture alliance/dpa | M. Mustermann</figcaption></figure>`. Der Check liest die `<figcaption>` (Marker „Bild:"), prüft wortgrenzen-genau gegen die Agenturliste, trifft „picture alliance" → **rot**. Liest den geschriebenen Bildnachweis (§ 13 UrhG).

**Methode 2 — Agentur-Asset-ID in der Bild-URL.** Beispiel Schulblog ohne Credit: `<img src="https://schule21.blog/media/csm_AdobeStock_512345678_9f7.jpg">`. Kein Credit-Text → Methode 1 greift nicht. Der Check prüft die URL gegen `adobestock…\d{6,}`, trifft die Asset-ID → **rot**. Liest den Herkunfts-Fingerabdruck im Dateinamen.

---

## Optionen 1–14

| # | Option | Ebene | Signalstärke | Kosten | Masse | Ergebnis |
|---|---|---|---|---|---|---|
| 1 | Strukturierte Rechteangaben im HTML (schema.org, ccREL) | Seite | hoch bei Treffer | frei | ja | red / green |
| 2 | Sichtbare Bildnachweise im DOM (Caption/Credit + URL-Muster) | Seite | mittel–hoch | frei | ja | red / yellow |
| 3 | Domain-/CDN-/Dateinamen-Heuristik | Seite | schwach (Soft) | frei | ja | yellow / green |
| 4 | Site-Policy (robots.txt, AGB, TDM-Vorbehalt) | Seite | schwach–mittel | frei | ja | yellow / green |
| 5 | Eingebettete Metadaten (IPTC/EXIF/XMP/PLUS) | Datei | hoch bei Treffer | frei | ja | red / green |
| 5b | **Metadaten des Originalbilds der Fundseite** | Datei/Seite | hoch bei Treffer | frei (Download) | opt-in | red / green |
| 6 | C2PA / Content Credentials | Datei | hoch, selten | frei | ja | green / Info |
| 7 | Sichtbares Wasserzeichen / eingebrannter Credit | Datei | hoch bei Treffer | frei (GPU) | ja | red |
| 8 | Perceptual Hash vs. interner Risikospeicher | Abgleich | hoch bei Treffer | frei | ja | red |
| 9 | Hash-Abgleich vs. freie Referenzbestände | Abgleich | hoch bei Treffer | frei | ja | green |
| 10 | Reverse-Image-Suche (TinEye, Vision, Lens) | Abgleich | hoch | kostenpflichtig | nein | red / yellow / green |
| 11 | Agentur-Katalog-APIs (Shutterstock CV, Getty, Adobe) | Abgleich | hoch | Key/kostenpflichtig | nein | red |
| 12 | Redaktionelle Review-Queue | Prozess | maßgeblich | Personal | nein | red / green |
| 13 | Notice-and-Takedown / Meldeweg | Prozess | reaktiv | Personal | n/a | red |
| 14 | Ersatzdarstellung (Platzhalter / KI-Bild) | Ausspielung | n/a | frei/gering | ja | Fallback |

**Option 1 — Strukturierte Rechteangaben im HTML · Seite · frei.** *Vokabulare:* schema.org `ImageObject` (`contentUrl`, `license`, `acquireLicensePage`, `creditText`, `creator`, `copyrightNotice`) · ccREL (`rel="license"`, `cc:attributionName/URL`, `dc:source/creator`) · Dublin Core · MediaWiki `imageinfo`/`extmetadata`. *Logik:* CC-/PD-URI ⇒ green (URI normalisieren) · `acquireLicensePage` oder Agentur-Kaufseite ⇒ red · `creditText`=Agentur ⇒ red. Zuordnung über `contentUrl` (Flickr-Problem: `rel="license"` gilt formal dem Dokument). *Tooling:* extruct, rdflib+pyRdfa, BeautifulSoup/lxml. *Grenzen:* geringe Verbreitung; bei Konflikt HTML↔IPTC den restriktiveren Wert; acquireLicensePage-Logik neigt zu Fehlalarmen (Praxistest 0/2).

**Option 2 — Sichtbare Bildnachweise im DOM · Seite · frei.** Deutsche Seiten führen den Bildnachweis als Text (§ 13 UrhG). *Fundorte:* `<figcaption>` → `alt`/`title`/`data-credit`/`aria-describedby` → Geschwister/Eltern mit Klassen `caption|credit|copyright|bildnachweis|wp-caption-text|image-source` → Sammelseiten `/bildnachweis`, `/impressum` → Footer. *Muster:* `©|\(c\)|Copyright|Bildrechte|Bildnachweis|Bildquelle|Fotocredit` · `Foto|Bild|Grafik|Quelle|Credit|Photo|Image\s*:`. *Agentur-Wortliste:* Getty, iStock, Shutterstock, Adobe Stock/`stock.adobe.com`, Fotolia, picture alliance, dpa, imago, Reuters, AP, AFP, ddp, Depositphotos, 123RF, Dreamstime, Alamy, Panthermedia, Westend61, plainpicture, laif, Zoonar, KNA-Bild. *Freie-Quellen:* Unsplash, Pexels, Pixabay, Wikimedia Commons, Openverse, Flickr (CC), CC BY, CC0, gemeinfrei. *URL-Muster (im Bild-`src`/`srcset`/`og:image`/`background-image`):* `gettyimages-\d{6,}`, `AdobeStock_?\d{6,}`, `shutterstock_\d{6,}`, `istock…\d{6,}`, `imago\d{7,}`, `depositphotos_\d{6,}`, dpa-NewsML. *Logik:* Agentur (Text oder URL-ID) ⇒ red · CC/PD + Code ⇒ green · Credit nicht klassifizierbar ⇒ yellow. *Grenzen:* Freitext; Galerien/Lazy-Load unsicher; JS-gerenderte Captions brauchen Headless-Rendering (schema.org/og:image liegen server-seitig im `<head>` und überleben).

**Option 3 — Domain-/CDN-/Dateinamen-Heuristik · Seite · frei · Soft.** *Whitelist:* unsplash.com, pexels.com, pixabay.com, upload/commons.wikimedia.org, openverse.org, live.staticflickr.com, nasa.gov, europeana.eu. *Blacklist:* gettyimages.\*, istockphoto.com, shutterstock.com, stock.adobe.com, ftcdn.net, depositphotos.com, 123rf.com, dreamstime.com, alamy.com, picture-alliance.com, imago-images.de. *Grenzen:* Whitelist verlässlicher; Blacklist nur in Kombination mit 1/2/5 hart auf red; Whitelist ≠ automatisch CC.

**Option 4 — Site-Policy · Seite · frei · schwach–mittel.** `robots.txt` Disallow für Bildpfade ⇒ Indikator gegen konkludente Einwilligung (BGH „Vorschaubilder I") · TDM-Vorbehalt (§ 44b Abs. 3 UrhG) ⇒ Soft-yellow · `<meta name="robots" content="noimageindex">` ⇒ red-Indikator. *Grenzen:* seiten-, nicht bildbezogen — nie alleinige Grundlage.

**Option 5 — Eingebettete Metadaten (IPTC/EXIF/XMP/PLUS) · Datei · frei.**

| Feld | Namespace | Aussage |
|---|---|---|
| Copyright Notice | IIM 2:116 / dc:rights / Exif Copyright | Rechteinhaber |
| Creator / By-line | IIM 2:80 / dc:creator / Exif Artist | Urheber |
| Credit Line | IIM 2:110 / photoshop:Credit | Vorgeschriebene Nennung (oft Agentur) |
| Source | IIM 2:115 / photoshop:Source | Lieferkette, häufig Agentur |
| Web Statement of Rights | xmpRights:WebStatement | URL zur Rechteerklärung → „Licensable" |
| Licensor URL/Name | plus:Licensor | Lizenzgeber, Kaufweg → starkes red |
| Image Supplier | plus:ImageSupplier | Agentur/Distributor |
| Digital Source Type | Iptc4xmpExt:DigitalSourceType | u. a. trainedAlgorithmicMedia (KI) |

*Logik:* Credit/Source/Copyright/Licensor\*=Agentur ⇒ red · Licensor/WebStatement auf Kaufseite ⇒ red · WebStatement auf CC-URI ⇒ green · leer ⇒ kein Signal (nicht green). *Tooling:* ExifTool, pyexiftool/IPTCInfo3/piexif, Apache Tika. *Grenzen (Imatag):* ~85 % ohne Metadaten; Redaktionelle Sites ~20 % behalten, ~8 % urheberidentifizierend. **Leere Metadaten ≠ lizenzfrei.**

**Option 5b — Metadaten des Originalbilds der Fundseite · Datei/Seite · frei (Download) · opt-in.** Die WLO-Vorschau ist gestrippt; das Bild auf der Fundseite (`<img src>`) ist eine Stufe näher am Original und trägt häufiger noch Metadaten. Der Check identifiziert es (Dateiname-Abgleich, sonst `og:image`), lädt es (SSRF-geschützt) und wertet es mit derselben Logik wie Option 5 aus. Übersprungen, wenn die Seite schon `red` ist. *Aktivierung:* `BILDCHECK_FETCH_ORIGIN=1` — für Ingestion, nicht Massen-Batch. *Grenzen:* auch Originale meist gestrippt → Zugewinn nur bei metadaten-erhaltender Minderheit (Praxistest: 4 Agentur-Funde / 5000).

**Option 6 — C2PA / Content Credentials · Datei · frei.** Signiertes Manifest (Signer, `c2pa.actions`, KI-Assertions; Hard Binding via SHA-256). *Tooling:* c2pa-rs, c2patool, c2pa-python. *Nutzen:* gültiges Manifest + CC/PD ⇒ green · Agentur-Signer ⇒ red · `trainedAlgorithmicMedia` ⇒ KI-Kennzeichnung (EU AI Act Art. 50). *Grenzen:* Verbreitung gering; Manifeste fälschbar; belegt nur eine Behauptung; Re-Encodes verlieren es.

**Option 7 — Wasserzeichen / eingebrannter Credit · Datei · frei (GPU).** Klassifikator (YOLOv8/MobileViTv2; LAION-Score) · Heuristik (Autokorrelation, Kantendichte) · OCR (Tesseract/PaddleOCR) → „Shutterstock"/„Getty Images"/„Preview" ⇒ red. *Grenzen:* Falsch-Positive bei Schrift/UI-Overlays; nur sichtbare Marken. *Lizenz:* Ultralytics YOLOv8 = AGPL-3.0 — permissive Alternative MobileViTv2 (Apache-2.0).

**Option 8 — Perceptual Hash gegen internen Risikospeicher · Abgleich · frei.**

| Algorithmus | Länge | Schwelle | Lizenz |
|---|---|---|---|
| dHash / aHash | 64 bit | ≤ 4–6 | BSD (imagehash) |
| pHash (DCT) | 64 bit | ≤ 6 | BSD / GPLv3 |
| PDQ (Meta) | 256 bit | ≤ 30 | BSD (ThreatExchange) |

*Empfehlung:* PDQ primär + dHash als Vorfilter. *Risikospeicher:* Bestand bestätigt problematischer Bilder; wächst mit jedem Fall → mittelfristig **der wirksamste Filter**. Index BK-Tree/LSH, bei >10 Mio. FAISS/pgvector. *Grenzen:* erkennt Bild, nicht Lizenz. Praxistest: leer → 0; die Fälle einspeisen.

**Option 9 — Hash-Abgleich gegen freie Referenzbestände · Abgleich · frei.** Commons `aisha1=<SHA1>` → Lizenz via `extmetadata` ⇒ green + Attribution · Openverse (>800 Mio., Token frei) · eigener pHash/PDQ-Index. *Grenzen:* SHA-1 nur bitidentisch (Re-Compression bricht Abgleich); Openverse-Anonym ~100 Req/Tag. Praxistest: 0 Treffer bei kuratiertem Material.

**Option 10 — Reverse-Image-Suche · Abgleich · kostenpflichtig, selektiv.**

| Anbieter | Kosten (2026) |
|---|---|
| TinEye API | ab $200/5.000; 1 Mio.-Bündel ~$10.000 (~$0,01/Suche) |
| TinEye MatchEngine (privater Index) | $200–$1.500/Mon. |
| Google Cloud Vision — Web Detection | $3,50/1.000; 1.000/Mon. frei |
| SerpApi (Lens/Bing Reverse) | ab ~$75/Mon./5.000 |

> Bing Search APIs (inkl. Visual Search) seit **11. Aug. 2025** abgeschaltet (HTTP 410). Ersatz: SerpApi/DataForSEO. *Einsatzregel:* nur High-Risk-Fallback (strittig, ohne Signal 1–9, reichweitenstark). Stock-Kontext ⇒ red, sonst yellow.

**Option 11 — Agentur-Katalog-APIs · Abgleich · Key/kostenpflichtig.** Shutterstock CV (`/v2/cv/images` → `/v2/cv/similar/images`), Getty (Partnervertrag), Adobe Stock (API-Key). Hoher Score ⇒ red. *Grenzen:* „ähnlich" ≠ „identisch"; nur ein Katalog; AGB prüfen.

**Option 12 — Redaktionelle Review-Queue · Prozess.** `yellow`-Knoten priorisiert (Traffic × Auslieferung). Entscheidung setzt `image_license_status`, `image_license_source=manual`. **Jede `red`-Entscheidung schreibt den Hash in den Risikospeicher** → Selbstverstärkung. Bulk pro Domain/Agentur.

**Option 13 — Notice-and-Takedown · Prozess.** Meldeformular + `POST /report` ⇒ sofort `red`, Hash in Speicher, Ticket. *Rechtlich:* Haftungsprivileg greift nur bis zur Kenntnis → Reaktionsgeschwindigkeit ist Compliance. SLA (< 24 h), protokollieren.

**Option 14 — Ersatzdarstellung · Ausspielung.** Icon-Platzhalter (Default) · Dominant-Farbe/Blurhash (rechtlich prüfen — bleibt Bearbeitung) · abstraktes KI-Bild aus Titel/Beschreibung (Original nicht als Seed; Kennzeichnung EU AI Act Art. 50) · Screenshot der Fundseite (ungeeignet — enthält u. U. dasselbe Bild).

---

## Datenfelder

| Feld | Typ | Zweck |
|---|---|---|
| `image_license_status` | enum (red/yellow/green/unchecked) | Ergebnis, steuert Auslieferung |
| `image_license_source` | string | schema_org, dom_credit, iptc, origin_iptc, c2pa, phash_hub, commons_sha1, watermark, domain, tineye, vision_web, shutterstock_cv, manual, report |
| `image_license_confidence` | float 0–1 | Aggregierte Sicherheit |
| `image_license_signals` | json[] | Einzelbefunde `{option,result,evidence,ts}` — Re-Evaluierung ohne Neu-Crawl |
| `image_license_field` | string/null | Ausgelesener Lizenz-/Copyright-Text |
| `image_license_uri` | string/null | Normalisierte Lizenz-URI |
| `image_license_acquire_url` | string/null | acquireLicensePage / plus:LicensorURL — starkes red |
| `image_credit_text` | string/null | Sichtbarer Bildnachweis (Option 2) — Basis für TULLUBA-Attribution |
| `image_creator` | string/null | IPTC Creator/Byline bzw. aus Credit |
| `image_supplier` | string/null | plus:ImageSupplier / erkannte Agentur |
| `image_phash` / `image_pdq` / `image_sha1` | string (hex) | Lizenzprüfung + Dedup / Primärabgleich / Dateiidentität |
| `image_source_domain` / `image_source_page` | string | Herkunfts-Host / Fundstellen-URL (Option 1/2/4 seiten-, nicht dateigebunden) |
| `image_c2pa_status` | enum (valid/invalid/absent) | C2PA-Ergebnis |
| `image_watermark_score` | float/null | Wasserzeichen-Klassifikator |
| `image_checked_at` | timestamp | Re-Check-Steuerung |
| `image_review_flag` / `_by` / `_at` | bool / string / ts | Redaktion + Audit-Trail |

`image_phash`/`image_pdq` doppelt nutzen (Lizenzprüfung + Dedup). Ein Bild kann an mehreren Fundstellen unterschiedliche Angaben tragen → `image_license_signals` als Liste, **restriktivster Wert gewinnt**.

---

## API-Design

`POST /check` · `POST /check/batch` · `POST /extract/page` · `GET /status/{node_id}` · `POST /risk-hub` · `DELETE /risk-hub/{hash}` · `POST /review/{node_id}` · `POST /report` · `POST /recheck`.

```python
def check(image, page):
    s = []                                        # Signalliste
    s += structured_rights(page)                  # 1  schema.org / ccREL / DC
    s += dom_credit(page, image.url)              # 2  Caption + URL-Muster
    s += domain_rules(image.url)                  # 3  Whitelist / Blacklist
    s += site_policy(page)                        # 4  robots.txt / TDM
    s += embedded_metadata(image)                 # 5  IPTC / EXIF / XMP
    s += origin_metadata(page, image.url)         # 5b Metadaten des Originalbilds
    s += c2pa_manifest(image)                     # 6  Content Credentials
    s += watermark(image)                         # 7  Klassifikator + OCR
    s += risk_hub_match(pdq(image))               # 8  interner Risikospeicher
    s += free_corpus_match(sha1(image), phash(image))  # 9  Commons / Openverse
    verdict = aggregate(s)                        # RED > YELLOW > GREEN
    if verdict in (RED, GREEN):
        return verdict
    if high_traffic(page):                        # kostenpflichtig, nur selektiv
        s += reverse_search(image)                # 10 TinEye / Vision
        s += agency_catalog(image)                # 11 Shutterstock CV
        verdict = aggregate(s)
        if verdict is not None:
            return verdict
    return YELLOW                                 # Default-Deny bei Unklarheit
```

**Aggregation:** jedes `red` ≥ 0,8 ⇒ red (kein Overrule) · `green` nur bei ≥ 1 starkem Positivnachweis (1 CC-URI, 5 WebStatement→CC, 9 SHA-1, 6 valides Manifest) und keinem red · Widerspruch ⇒ yellow · kein Signal ⇒ yellow (Default-Deny).

**Integration:** Crawler ruft `/check/batch` bei Ingestion (**Seiten-HTML mitgeben** — Option 1/2/4/5b sonst nur per Neu-Crawl nachholbar) · Preview: nur `green` → Thumbnail, sonst Option 14 · Redaktions-UI: `yellow` in Queue, Bulk pro Domain · Optionen 10/11 in Low-Priority-Queue mit Budget-Cap · Bestandslauf: Risikospeicher retroaktiv gegen `image_pdq`.

---

## Tools & Kosten

| Tool | Zweck | Lizenz | Kosten |
|---|---|---|---|
| ExifTool | IPTC/EXIF/XMP/PLUS lesen | GPL/Artistic | frei |
| pyexiftool / IPTCInfo3 / piexif | Python-Zugriff | OSS | frei |
| Apache Tika | Metadaten (JVM) | Apache-2.0 | frei |
| extruct / rdflib / pyRdfa | schema.org, RDFa, ccREL | BSD/W3C | frei |
| BeautifulSoup / lxml | DOM-/Caption-Extraktion | MIT/BSD | frei |
| spaCy (de_core_news_lg) | NER im Credit-Text | MIT / CC BY-SA | frei |
| imagehash / libpHash | aHash/pHash/dHash | BSD / GPLv3 | frei |
| ThreatExchange PDQ | PDQ 256 bit | BSD | frei |
| FAISS / pgvector | Hash-/Vektor-Index | MIT / PostgreSQL | frei |
| c2pa-rs / c2patool | C2PA lesen/prüfen | MIT-Apache | frei |
| Tesseract / PaddleOCR | OCR Wasserzeichen | Apache-2.0 | frei |
| Ultralytics YOLOv8 | Wasserzeichen-Klassifikator | AGPL-3.0 | frei (Lizenz prüfen) |
| MobileViTv2 / timm | Wasserzeichen-Klassifikator | Apache-2.0/MIT | frei |
| OpenCV | Bildvorverarbeitung | Apache-2.0 | frei |
| Wikimedia Commons API | SHA-1-Lookup, Lizenzen | frei (CC BY-SA) | frei |
| Openverse API | CC-/PD-Bestand | MIT (Client) | frei, Token frei |
| TinEye API / MatchEngine | Reverse-Image / privater Index | proprietär | $200/5.000 · $200–1.500/Mon. |
| Google Cloud Vision (Web Detection) | Reverse-Image | proprietär | $3,50/1.000; 1.000/Mon. frei |
| SerpApi (Lens/Bing Reverse) | Reverse-Image | proprietär | ab ~$75/Mon./5.000 |
| Shutterstock CV API | Agenturkatalog | proprietär | Key + Freischaltung |
| ~~Bing Visual Search API~~ | — | — | abgeschaltet 11. Aug. 2025 |

> **GPL/AGPL:** ExifTool/libpHash sind GPL — ExifTool als externer CLI-Prozess entschärft die Kopplung. Ultralytics (AGPL-3.0) bei Netzwerkdienst prüfen; permissive Alternative bevorzugen.

---

## Rechtlicher Kontext
*Kurzüberblick, keine Rechtsberatung.*

| Entscheidung | Az. | Kernaussage |
|---|---|---|
| BGH „Vorschaubilder I" | I ZR 69/08, 29.04.2010 | Schlichte Einwilligung ohne technische Sperre (robots.txt); Suchmaschine haftet nicht |
| BGH „Vorschaubilder II" | I ZR 140/10, 19.10.2011 | Gilt auch bei unberechtigt eingestellten Bildern |
| BGH „Vorschaubilder III" | I ZR 11/16, 21.09.2017 | Keine Gewinnerzielungs-Vermutung; Haftung ab Kenntnis |
| EuGH „Renckhoff" | C-161/17, 07.08.2018 | Erneutes Hochladen braucht eigene Zustimmung |
| EuGH „VG Bild-Kunst" | C-392/19, 09.03.2021 | Framing unter Umgehung techn. Schutzmaßnahmen = öffentliche Wiedergabe |
| § 13 UrhG | — | Namensnennungspflicht — Grundlage der Bildnachweis-Praxis (Option 2) |
| § 44b Abs. 3 UrhG | — | Maschinenlesbarer TDM-Vorbehalt (Option 4) |
| EU AI Act Art. 50 | — | Kennzeichnungspflicht für KI-Inhalte (Option 14) |

> **Relevanz:** Das Suchmaschinen-Privileg ist nicht ohne Weiteres auf ein Portal übertragbar, das Vorschaubilder selbst speichert. Die Haftungsbegrenzung setzt an der **Kenntnis** an — deshalb sind Option 13 (Meldeweg) und Reaktionszeit Teil der Architektur.

---

## Empfehlung — Wann & mit welchen Methoden prüfen

Der Praxistest zeigt: die verwertbaren Signale sitzen auf der **Fundseite** und im **Originalbild** — beide sind **nur beim Crawlen** verfügbar. Daraus folgt die Staffelung nach Zeitpunkt:

| Zeitpunkt | Zweck | Methoden | Warum hier |
|---|---|---|---|
| **Ingestion / Erschließung** (erster Crawl) | Verstöße aussortieren, bevor Material ins Repo geht | **1** schema.org · **2** Bildnachweis + URL-Muster · **3** Domain · **4** Site-Policy · **5** Datei-Metadaten · **5b** Original-Metadaten (`FETCH_ORIGIN=1`) | Fundseiten-HTML + Originalbild sind später nur per Neu-Crawl nachholbar. Trägt ~99 % der Erkennung |
| **Preview / Auslieferung** | Default-Deny durchsetzen | gespeicherter `image_license_status` · **8** Risikospeicher (pHash) | nur `green` → Thumbnail; kein Crawl, nur Lookup |
| **Massen-Batch / Bestandslauf** | Bestand nachprüfen, Regeländerungen | **1–8** lokal (extern **aus**, Original-Fetch **aus**); **8** retroaktiv gegen `image_pdq` | Kosten/Zeit; externe Dienste & Original-Fetch bringen im Massenlauf zu wenig |
| **Selektiv** (High-Traffic, strittig, ohne Signal) | Restfälle | **10** Reverse-Image · **11** Agentur-APIs | kostenpflichtig → Budget-Cap, eigene Queue |

**Kern:** Der **Ingestion-Zeitpunkt ist entscheidend** — nur dort greifen die zwei tragenden Methoden (Bildnachweis + URL-Muster) und die Original-Metadaten-Prüfung. Datei-/Hash-/externe Verfahren sind Absicherung bzw. Selektiv-Werkzeug, kein Ersatz.

**Nächste Schritte aus dem Test:** (1) bestätigte Fälle in den Risikospeicher einspeisen; (2) `acquireLicensePage`-Logik recalibrieren (nur Agentur-Ziel → red, Wayback entpacken); (3) Original-Metadaten-Prüfung bei Ingestion aktivieren; (4) externe Dienste im Batch aus lassen.

---

## Stufenplan

| Stufe | Inhalt | Aufwand | Nutzen |
|---|---|---|---|
| 1 | Schema-Erweiterung, Default-Deny im Preview, Platzhalter-Icon | S | Sofortige Risikoreduktion |
| 2 | Optionen 5 + 3 + 8 (Metadaten, Domain, Risikospeicher) | M | Eindeutige Fälle |
| 3 | **Optionen 1 + 2 + 5b (Seitenkontext + Originalbild im Crawler)** | M–L | **Größter Zugewinn (99 % der Verstöße)** |
| 4 | Option 9 (Commons/Openverse) | M | Mehr green (bei kuratiertem Material begrenzt) |
| 5 | Optionen 12 + 13 (Review-Queue, Meldeweg) | M | Compliance |
| 6 | Optionen 6 + 7 (C2PA, Wasserzeichen) | M | Ergänzung (Direkt-Uploads) |
| 7 | Optionen 10 + 11 (Reverse Search, Agentur-APIs) selektiv | S (Kosten var.) | Restfälle High-Traffic |
| 8 | Option 14 Variante KI-Bild | M | Bessere UX bei red |

---

## Quellen

- Google Search Central — Image License Metadata: https://developers.google.com/search/docs/appearance/structured-data/image-license-metadata
- IPTC — Quick Guide / Google Images: https://iptc.org/standards/photo-metadata/quick-guide-to-iptc-photo-metadata-and-google-images/
- IPTC Photo Metadata Standard 2025.1: https://www.iptc.org/std/photometadata/specification/IPTC-PhotoMetadata-2025.1.html
- IPTC — Social Media Photo Metadata Test Results: https://www.embeddedmetadata.org/social-media-test-results.php
- Imatag — State of image metadata: https://www.imatag.com/blog/state-of-image-metadata-in-2018
- Creative Commons — ccREL: https://opensource.creativecommons.org/ccrel/ · Marking Works Technical: https://wiki.creativecommons.org/wiki/Marking_Works_Technical
- C2PA Specification 2.x: https://spec.c2pa.org/specifications/specifications/2.4/specs/C2PA_Specification.html · Grenzen: https://www.softwareseni.com/how-c2pa-content-credentials-work-and-what-their-limits-are/
- PDQ Test Drive (Schwelle ≤30): https://arxiv.org/pdf/1912.07745 · Perceptual-Hash-Evasion: https://www.usenix.org/system/files/sec22summer_jain.pdf
- Wikimedia Commons — Tools (SHA-1): https://commons.wikimedia.org/wiki/Commons:Tools
- Openverse — About/API: https://openverse.org/about · https://docs.openverse.org/packages/js/api_client/index.html
- TinEye — API-Pricing: https://blog.tineye.com/new-image-search-pricing/ · MatchEngine: https://help.tineye.com/article/211-matchengine-pricing
- Google Cloud Vision — Pricing: https://cloud.google.com/vision/pricing
- Microsoft — Bing Search APIs Retirement: https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement
- Shutterstock — Computer Vision: https://www.shutterstock.com/developers/documentation/searching
- Wasserzeichen-Detektion (YOLOv8/MobileViTv2): https://arxiv.org/pdf/2511.08637
- Adobe-Stock-CDN ftcdn.net u. a.: https://waxy.org/2022/08/exploring-12-million-of-the-images-used-to-train-stable-diffusions-image-generator/
- BGH Vorschaubilder I: https://medien-internet-und-recht.de/volltext.php?mir_dok_id=2177 · III / EuGH-Kette: https://itmr-legal.de/blog/vorschaubilder-entscheidung-privilegiert-der-bgh-google-rechtsanwalt-andreas-buchholz
