# Bild-Lizenz-Check

Prüfdienst zur Erkennung **problematischer Bildlizenzen / Urheberrechtsprobleme**,
bevor ein Bild (z. B. als Vorschau) ausgeliefert wird. Arbeitet nach dem Prinzip
**Default-Deny**: eine Freigabe (grün) nur bei nachgewiesen unkritischem Status,
sonst gelb (Prüfung) oder rot (Warnung).

Drei Eingabewege, ein einheitliches Ergebnis:

1. **Bild-URL** (+ optional Fundseite)
2. **Datei-Upload** (Durchsuchen & Hochladen)
3. **edu-sharing / openeduhub Node-ID** — Repositorien **prod** & **staging** hinterlegt

```
┌──────────────┐   POST /api/check   ┌───────────────────────────────┐
│ Angular UI   │ ──────────────────► │ FastAPI Prüfdienst            │
│ (Material 3) │ ◄────────────────── │  Loader → Checks → Aggregation│
└──────────────┘   CheckReport(JSON) └───────────────────────────────┘
```

Der Prüfdienst (`backend/app/pipeline.py`) ist frei von HTTP-/UI-Details und
damit **direkt als Bibliothek oder Microservice nachnutzbar**.

---

## Prüfschritte

Alle Basis-Checks laufen **lokal & kostenlos** (Open-Source, keine nativen Binaries
zwingend). Externe Dienste sind **Opt-in**, weil sie eine Bild-/Hash-Übertragung
an Dritte bedeuten.

| # | Prüfschritt | Ebene | Extern | Vorlage-Option |
|---|-------------|-------|:---:|:---:|
| 1 | Deklarierte Lizenz (edu-sharing `ccm:commonlicense_key`) | Repository | – | — |
| 2 | Strukturierte Rechteangaben (schema.org / ccREL / Dublin Core) | Seite¹ | – | 1 |
| 3 | Sichtbarer Bildnachweis im DOM (figcaption / Credit / Bild-URL-Muster) | Seite¹ | – | 2 |
| 3b | Zentrale Bildnachweis-Seite der Domain (folgt „Bildquellen"-Links) | Seite¹ | – | 2 |
| 4 | Domain- & Dateinamen-Heuristik (Whitelist/Blacklist/Presse-Prior) | Seite | – | 3 |
| 5 | Site-Policy (robots.txt / Meta-Robots / TDM-Vorbehalt) | Seite¹ | – | 4 |
| 6 | Eingebettete Metadaten (EXIF/IPTC/XMP/PLUS + Herkunfts-ID) — WLO-Vorschau | Datei | – | 5 |
| 6b | Metadaten des **Originalbilds** der Fundseite (opt-in, un-re-gehostet) | Datei | – | 5 |
| 7 | C2PA / Content Credentials | Datei | – | 6 · *optional* |
| 8 | Wasserzeichen / eingebrannter Credit (OCR) | Datei | – | 7 · *optional* |
| 9 | Perceptual Hash (dHash) + interner Risikospeicher | Abgleich | – | 8 |
| 10 | Wikimedia Commons SHA-1-Abgleich (Positivnachweis) | Abgleich | ✔ | 9 |
| 11 | Openverse CC-Katalog-Recherche (INFO-Kontext) | Abgleich | ✔ | 9 |

¹ **Seiten-Checks brauchen die Fundseite:** im URL-Modus das optionale Feld
„Fundseite", im Node-Modus automatisch aus `ccm:wwwurl` des Repository-Inhalts.
Ist die Fundseite tot/umgezogen, greift optional ein **Wayback-Machine-Fallback**
(überträgt nur die URL an archive.org, nie das Bild; `BILDCHECK_WAYBACK=0` schaltet ab).

**Erkennung von Agenturbildern ohne sichtbaren Credit** (aus dem 5000er-Batch
kalibriert): Schritt 3 prüft die Bild-URLs der Fundseite zusätzlich auf
Agentur-Asset-Muster (`gettyimages-123…`, `AdobeStock_…`, `imago…`, dpa-NewsML);
Schritt 6 wertet Herkunfts-IDs (`xmpMM:DocumentID`) aus, die Agentur-Workflows oft
stehen lassen; Schritt 4 stuft Bilder von **Presse-/Rundfunkseiten** ohne
bildbezogenen Positivbeleg zum Hinweis herab (strenger Modus `BILDCHECK_STRICT_NEWS=1`
macht daraus einen Verdacht). Uncredited Agenturbilder mit gestrippten Metadaten auf
neutralen Seiten bleiben ohne kostenpflichtige Reverse-Image-Suche prinzipiell
unentdeckbar — der **Risikospeicher** (bestätigte Fälle per Review-Queue einspeisen)
fängt danach jede Wiederverwendung desselben Bilds per pHash.

*Optional* = nutzt ein Zusatzpaket, das nicht im Kern-Install ist; ohne meldet der
Schritt sauber „nicht verfügbar". Die **kostenpflichtigen** Vorlage-Optionen 10/11
(TinEye, Google Vision, Agentur-APIs) sind bewusst **nicht** enthalten — nur freie
Dienste; Erweiterungspunkt ist ein `BaseCheck` mit `external = True`.

**Externe Dienste — Standardverhalten:**
- **Einzelprüfung:** standardmäßig **an**. Jeder externe Check hat eine **Frist**
  (`BILDCHECK_EXTERNAL_TIMEOUT`, Default 8 s) — antwortet ein Dienst nicht rechtzeitig,
  wird er als „nicht verfügbar" übersprungen, die Prüfung läuft weiter (**kein Abbruch**).
- **Batch:** standardmäßig **aus** — bei kuratierten Repo-Inhalten kaum Mehrwert,
  aber viel Laufzeit + Openverse-Tageslimit (10.000). Pro Lauf zuschaltbar.

### Ampel-Aggregation (restriktivster Wert gewinnt)
- **rot**, wenn ein starkes Warnsignal (Konfidenz ≥ 0,8) **oder** mehrere unabhängige
  Warnsignale vorliegen — und kein starker Positivnachweis.
- **grün** nur bei einem starken Positivnachweis (CC-URI, SHA-1-Treffer, valides
  Manifest, deklarierte freie Lizenz) **und** keinem Warnsignal.
- **gelb** bei Widerspruch, schwachem Einzelsignal oder fehlendem Signal (Default-Deny).

### Ergebnis-Skala (Endnutzer-Sicht, 4-stufig)
Die feine Ampel wird auf vier Kategorien abgebildet (`report.category`):

| Kategorie | Bedeutung | Auslieferung |
|---|---|---|
| 🟢 **Unproblematisch** | Positivnachweis einer freien/unkritischen Lizenz | Freigabe möglich (Attribution beachten) |
| 🟡 **Nicht messbar** | kein belastbares Signal (leere Metadaten, keine Deklaration) | Default-Deny — keine automatische Freigabe |
| 🟠 **Zu prüfen** | Warnhinweis vorhanden, aber nicht eindeutig (Widerspruch, seiten­weiter Agentur-Hinweis) | redaktionell klären |
| 🔴 **Problematisch** | starkes Warnsignal ohne Gegenbeleg | nicht ausliefern |

Regel: `problematisch` = rote Gesamt­ampel · `zu prüfen` = gelb **mit** einem Warn­signal ·
`nicht messbar` = gelb **ohne** Warnsignal · `unproblematisch` = grün.

---

## Schnellstart

### Backend (Python 3.10+)
```bash
cd backend
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt        # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # Linux/macOS
./.venv/Scripts/python -m uvicorn app.main:app --port 8000
```
→ API unter <http://localhost:8000/api>, interaktive Doku unter `/docs`.

Tests (ohne Netzwerk):
```bash
./.venv/Scripts/python -m tests.test_smoke   # Pipeline/Aggregation (Unit)
./.venv/Scripts/python -m tests.test_api     # HTTP-Endpunkte (FastAPI TestClient)
```

### Frontend (Angular 21 · Node 20.19+ / 22.12+)
```bash
cd frontend
npm install
npm start            # ng serve, http://localhost:4200
```
Das UI ruft das Backend über den relativen Pfad `/api` auf. Im Dev proxyt der
Angular-Server `/api` → `http://localhost:8000` (`proxy.conf.json`, in
`angular.json` hinterlegt — `npm start` nutzt es automatisch). In Produktion wird
`/api` per Reverse-Proxy ans Backend geroutet (gleiche Origin, kein CORS, kein
Mixed-Content).

### Optionale Prüfschritte aktivieren
```bash
# C2PA / Content Credentials
./.venv/Scripts/pip install c2pa-python
# Wasserzeichen-OCR (zusätzlich System-Tesseract installieren)
./.venv/Scripts/pip install pytesseract
```

### Docker (Single-Container: Frontend + API in einem Image)
Ein Multi-Stage-Image baut das Angular-Frontend und liefert es zusammen mit der
API über **dieselbe Origin** aus (`/` = UI, `/api` = Backend) — kein separater
Reverse-Proxy nötig.

```bash
docker compose up --build        # -> http://localhost:8000
# oder ohne compose:
docker build -t pic-guardian .
docker run -p 8000:8000 -v pic-guardian-data:/app/data pic-guardian
```

- **Persistenz:** Risikospeicher (`risk_hub.json`) und Batch-Historie liegen unter
  `/app/data` — als Volume mounten, sonst gehen sie beim Neustart verloren.
- **Konfiguration** über Umgebungsvariablen (siehe Tabelle unter *Betrieb &
  Sicherheit*): `BILDCHECK_USER_AGENT`, `BILDCHECK_STRICT_NEWS`,
  `BILDCHECK_EXTERNAL_TIMEOUT`, `BILDCHECK_WAYBACK`, `BILDCHECK_CORS_ORIGINS`.
  Der Pfad zum statischen Frontend steckt in `BILDCHECK_STATIC_DIR` (im Image
  auf `/app/static` gesetzt; leer lassen = API-only für den Dev-Betrieb).

**Automatischer Push zu Docker Hub:** `.github/workflows/docker-publish.yml` baut
und pusht bei jedem Push auf `main` und bei Tags `v*.*.*` das Image
`<user>/pic-guardian`. Voraussetzung sind zwei Repo-Secrets: `DOCKERHUB_USERNAME`
und `DOCKERHUB_TOKEN` (Docker-Hub Access Token).

---

## HTTP-API

| Methode | Pfad | Zweck |
|---|---|---|
| `GET` | `/api/health` | Status + registrierte Checks |
| `GET` | `/api/repositories` | Hinterlegte Repos (prod/staging) fürs UI |
| `POST` | `/api/check` | Prüfung (multipart/form-data) |
| `POST` | `/api/risk-hub` | Hash zum Risikospeicher hinzufügen |
| `DELETE` | `/api/risk-hub/{hash}` | Eintrag entfernen |
| `POST` | `/api/review/confirm-node` | Node als bestätigten Problemfall in den Risikospeicher (SHA-1 + pHash) |
| `POST` | `/api/batch/collection` | Batch über eine Sammlung (rekursiv) starten → `job_id` |
| `POST` | `/api/batch/csv` | Batch über CSV/Liste starten → `job_id` |
| `GET` | `/api/batch/jobs` | Job-Historie (laufende + persistierte Läufe) |
| `GET` | `/api/batch/{job_id}` | Job-Status + Fortschritt + Zählung |
| `GET` | `/api/batch/{job_id}/export.csv` | Ergebnis als CSV (semikolon, Excel-tauglich) |
| `GET` | `/api/batch/{job_id}/export.json` | Ergebnis als JSON |
| `GET` | `/api/batch/{job_id}/report` | Markdown-Bericht |
| `GET` | `/api/batch/template` | Muster-CSV für den Datei-Batch |

`POST /api/check` — Felder (multipart/form-data):

| Feld | Pflicht | Beschreibung |
|---|---|---|
| `mode` | ✔ | `url` \| `upload` \| `node` |
| `image_url` | bei `url` | Bild-URL |
| `source_page` | – | Fundseite für die Seiten-Checks (im Node-Modus automatisch aus `ccm:wwwurl`) |
| `file` | bei `upload` | Bilddatei |
| `node_id` | bei `node` | edu-sharing Node-UUID |
| `repository` | bei `node` | `prod` \| `staging` (Default `prod`) |
| `es_user`,`es_password` | – | Basic-Auth für geschützte Nodes |
| `allow_external` | – | `true` erlaubt externe Dienste (Default `false`) |

Beispiel:
```bash
curl -F mode=upload -F allow_external=false -F file=@foto.jpg \
     http://localhost:8000/api/check
```

Antwort (`CheckReport`, gekürzt):
```jsonc
{
  "verdict": "green",
  "confidence": 0.9,
  "headline": "Unkritisch — Freigabe möglich",
  "recommendation": "✓ Es liegt ein Positivnachweis …",
  "signals": [ { "id": "commons_sha1", "verdict": "green", "summary": "…" } ],
  "fields": { "license_uri": "…", "creator": "…", "sha1": "…", "phash": "…" },
  "source": { "mode": "url", "mime": "image/jpeg", "width": 172 },
  "image_data_uri": "data:image/jpeg;base64,…"
}
```

---

## Batch-Prüfung (Sammlung / CSV)

Für die Massenprüfung von Repository-Inhalten — im UI im Tab **„Batch-Prüfung"**,
komplett auch über `/docs`. Jobs laufen asynchron; Status per `job_id` pollen.

- **Sammlungsbasiert:** Node-ID einer (Wurzel-)Sammlung → alle Untersammlungen und
  referenzierten Inhalte werden rekursiv abgearbeitet (dedupliziert über das
  Original). Tiefen-/Node-Limit als Schutz.
- **Dateibasiert:** CSV mit `node_id;repository` (semikolon; `repository` optional →
  Default). Muster unter `GET /api/batch/template`.

```bash
# Sammlung starten
curl -F node_id=<COLLECTION_UUID> -F repository=prod -F max_nodes=200 \
     http://localhost:8000/api/batch/collection            # -> {"job_id": "..."}
# Status pollen
curl http://localhost:8000/api/batch/<job_id>
# Exporte für die Nachbearbeitung
curl -O http://localhost:8000/api/batch/<job_id>/export.csv   # ; -getrennt
curl    http://localhost:8000/api/batch/<job_id>/report       # Markdown
```

**Datenschutz:** Batch-Ergebnisse enthalten **keine** Bilddaten (kein `image_data_uri`);
es wird nichts auf Disk geschrieben, und die Bild-Bytes werden nach der Prüfung jedes
Nodes sofort freigegeben — **kein Bild bleibt auf dem Prüfserver liegen**.

## Erweitern: neuen Prüfschritt hinzufügen

1. Datei `backend/app/checks/cNN_meincheck.py` anlegen, von `BaseCheck` erben:
   ```python
   class MeinCheck(BaseCheck):
       id = "mein_check"; label = "Mein Check"; category = "file"
       external = False                       # True => Opt-in-Gate
       def applies(self, ctx): return True    # optional
       def execute(self, ctx):
           return self.signal(verdict=Verdict.NEUTRAL, summary="…",
                              data={"creator": "…"})   # data fließt in ExtractedFields
   ```
2. In `backend/app/checks/__init__.py` zu `ALL_CHECKS` hinzufügen.

Framework-Logik (Opt-in, Anwendbarkeit, Fehler, Timing) übernimmt `BaseCheck` —
der Check selbst bleibt klein. Aggregation & UI passen sich automatisch an.

---

## Datenmodell (angelehnt an die Schema-Vorlage)

Die extrahierten Felder (`fields`) folgen dem vorgeschlagenen `image_license_*`-Schema
(Lizenz-URI, Credit-Text, Urheber, Lieferant, pHash, SHA-1, C2PA-Status …) und sind
so die Basis für Attribution **und** Re-Evaluierung ohne Neu-Crawl.

## Betrieb & Sicherheit

- **SSRF-Schutz:** Nutzergesteuerte URLs (Bild-URL, Fundseite, `ccm:wwwurl`)
  werden gegen interne/private Ziele (127.0.0.1, 169.254.169.254 u. a.) geblockt
  (`app/net_guard.py`), inkl. Redirect-Prüfung und Größenlimit.
- **Rate-Limits externer Dienste** (`app/rate_limit.py`, nur bei Opt-in):
  | Dienst | Limit | Umsetzung |
  |---|---|---|
  | Wikimedia Commons | kein hartes Read-Limit, aber **UA-Pflicht** (sonst IP-Block) + seriell | Throttle 0,3 s/Host · `maxlag=5` · UA mit Kontakt (ENV `BILDCHECK_USER_AGENT`) |
  | Openverse | **100/min**, **10.000/Tag** (anonym, IP-geteilt) | Throttle 0,75 s (~80/min) · 429/401 → sauberes „nicht verfügbar" |
  Bei großen **Batches** mit externen Diensten das Tages-Limit von Openverse
  beachten — bei Erschöpfung liefert der Schritt „nicht verfügbar" (kein Abbruch);
  für Dauerbetrieb ein Openverse-Token registrieren oder externe Dienste im Batch
  aus lassen. edu-sharing (prod/staging) hat keine harten Limits, wird aber
  seriell abgefragt.
- **Kein App-internes Auth:** Der Dienst hat bewusst keine eigene Authentifizierung.
  Für den Produktivbetrieb **hinter einem Auth-/Reverse-Proxy und über HTTPS**
  betreiben; optional Rate-Limiting davorsetzen. Sonst sind `/api/check`,
  `/api/batch/*`, `/api/risk-hub` und `/api/review/*` offen erreichbar.
- **Konfiguration (ENV):**
  | Variable | Default | Wirkung |
  |---|---|---|
  | `BILDCHECK_USER_AGENT` | Kontakt-UA | UA für externe Fetches (Wikimedia-Pflicht) |
  | `BILDCHECK_CORS_ORIGINS` | localhost:4200 | erlaubte Frontend-Origins (Komma-getrennt) |
  | `BILDCHECK_STRICT_NEWS` | `0` | `1` = Presse-/Rundfunkbilder ohne Positivbeleg werden Verdacht (statt Hinweis) |
  | `BILDCHECK_WAYBACK` | `1` | `0` = kein Wayback-Fallback für tote Fundseiten |
  | `BILDCHECK_EXTERNAL_TIMEOUT` | `8` | Frist (s) pro externem Check in der Einzelprüfung; danach übersprungen (kein Abbruch) |
  | `BILDCHECK_FETCH_ORIGIN` | `0` | `1` = Originalbild von der Fundseite laden und dessen EXIF/IPTC/XMP prüfen (Metadaten der WLO-Vorschau sind CMS-gestrippt). Ein Download/Node — für Ingestion sinnvoll, im Massen-Batch aus |
- **Batch-Historie:** abgeschlossene Läufe werden als Metadaten-JSON unter
  `backend/data/batch_jobs/` persistiert (keine Bilddaten) und überstehen Neustarts
  (`GET /api/batch/jobs`).
- **Qualität:** Backend-Suiten `tests.test_smoke` (Unit, 55 Assertions inkl.
  Security- + Kalibrierungs-Regression) und `tests.test_api` (HTTP-Endpunkte via
  FastAPI TestClient, netzfrei), `ruff check app/ tests/`, `npm audit` — Details
  im [Code-Audit](docs/audits/2026-07-16-audit.md).

## Lizenzhinweise der genutzten Tools
Alle Kern-Abhängigkeiten sind frei/OSS (FastAPI, Pillow, imagehash/BSD, httpx,
BeautifulSoup, extruct). ExifTool (GPL) wird bewusst **nicht** benötigt — die
Metadaten werden mit Pillow + XMP-Packet-Parsing gelesen. Optionale Pakete
(c2pa, pytesseract) sind separat.

## Rechtlicher Hinweis
Dieses Werkzeug liefert **technische Indizien**, keine Rechtsberatung. Kein einzelnes
Signal ist für sich hinreichend; im Zweifel gilt Default-Deny.
