"""Wortlisten & Muster für die freien Heuristiken (Optionen 2, 3, 5).

Bewusst als Daten (keine Logik) gehalten, damit sie leicht gepflegt und ohne
Code-Änderung erweitert werden können.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

# ---------------------------------------------------------------------------
# Agenturen / kommerzielle Stock-Anbieter  ->  starkes RED-Signal
# ---------------------------------------------------------------------------
AGENCY_TERMS: list[str] = [
    "getty images", "gettyimages", "istock", "istockphoto", "shutterstock",
    "adobe stock", "adobestock", "stock.adobe.com", "fotolia",
    "picture alliance", "picture-alliance",
    "dpa", "imago", "reuters", "associated press", "afp", "ddp",
    "depositphotos", "123rf", "dreamstime", "alamy", "panthermedia", "westend61",
    "plainpicture", "laif", "zoonar", "mauritius images", "action press",
    "ullstein bild", "f1online", "your photo today", "stockfood", "gamma-rapho",
    "sipa", "abaca", "eyeem", "masterfile", "age fotostock", "blend images",
    "kna-bild",
]

# ---------------------------------------------------------------------------
# Freie Quellen / freie Lizenzen  ->  GREEN-Kandidat (Bedingungen dennoch prüfen)
# ---------------------------------------------------------------------------
FREE_SOURCE_TERMS: list[str] = [
    "unsplash", "pexels", "pixabay", "wikimedia commons", "wikimedia",
    "openverse", "flickr", "freepik", "public domain", "gemeinfrei",
    "cc0", "cc-0", "cc by", "cc-by", "creative commons", "creativecommons",
    "nasa", "europeana", "stocksnap", "burst", "kaboompics", "gratisography",
    "picdrop", "public domain mark", "pdm",
]

# ---------------------------------------------------------------------------
# Marker für sichtbare Bildnachweise im DOM / Metadaten (DE + EN)
# ---------------------------------------------------------------------------
CREDIT_MARKERS: list[str] = [
    "©", "(c)", "copyright", "bildrechte", "bildnachweis", "bildquelle",
    "fotocredit", "foto:", "fotos:", "bild:", "grafik:", "illustration:",
    "quelle:", "credit:", "photo:", "image:", "urheber", "fotograf",
]

# ---------------------------------------------------------------------------
# Domains  (Option 3) — Host-Substring-Match
# ---------------------------------------------------------------------------
DOMAIN_WHITELIST: list[str] = [
    "unsplash.com", "images.unsplash.com", "pexels.com", "images.pexels.com",
    "pixabay.com", "cdn.pixabay.com", "upload.wikimedia.org",
    "commons.wikimedia.org", "openverse.org", "live.staticflickr.com",
    "nasa.gov", "images-assets.nasa.gov", "europeana.eu",
]

DOMAIN_BLACKLIST: list[str] = [
    "gettyimages.com", "gettyimages.de", "media.gettyimages.com",
    "istockphoto.com", "media.istockphoto.com", "shutterstock.com",
    "image.shutterstock.com", "stock.adobe.com", "ftcdn.net", "as1.ftcdn.net",
    "as2.ftcdn.net", "t3.ftcdn.net", "t4.ftcdn.net", "depositphotos.com",
    "st.depositphotos.com", "123rf.com", "us.123rf.com", "dreamstime.com",
    "thumbs.dreamstime.com", "alamy.com", "c8.alamy.com", "picture-alliance.com",
    "imago-images.de", "imago-images.com",
]

# Presse-/Rundfunkangebote: Fotos dort sind ÜBERWIEGEND lizenziertes Agentur-
# material (dpa, picture alliance, Getty …), auch wenn die Seite „neutral"
# wirkt — die Batch-Auswertung fand die Agentur-Fälle fast ausschließlich auf
# solchen Seiten (bpb, Deutsche Welle, Deutschlandfunk). Ohne bildbezogenen
# Positivbeleg daher ein Warnhinweis (bzw. Verdacht im strengen Modus).
# Bewusst NICHT enthalten: reine Bildungsangebote der Sender mit Eigen-
# produktionen (z.B. planet-schule.de).
NEWS_PRESS_DOMAINS: list[str] = [
    # öffentlich-rechtlich
    "tagesschau.de", "ard.de", "zdf.de", "zdfheute.de", "dw.com", "3sat.de",
    "arte.tv", "phoenix.de", "deutschlandfunk.de", "deutschlandfunkkultur.de",
    "deutschlandfunknova.de", "br.de", "wdr.de", "ndr.de", "swr.de", "hr.de",
    "mdr.de", "rbb24.de", "radiobremen.de", "sr.de",
    # überregionale Presse
    "spiegel.de", "zeit.de", "faz.net", "sueddeutsche.de", "welt.de", "taz.de",
    "tagesspiegel.de", "handelsblatt.com", "stern.de", "focus.de",
    "t-online.de", "n-tv.de", "rnd.de", "bild.de", "merkur.de", "fr.de",
    # politische Bildung mit nachweislich hohem Agenturbild-Anteil (Batch-Evidenz)
    "bpb.de", "lpb-bw.de",
]

# ---------------------------------------------------------------------------
# Dateiname-/Pfad-Muster typischer Agentur-Assets  (Option 3)
#
# STRONG = Muster mit Agentur-Asset-ID (quasi beweisend, conf 0.8) — sie werden
# auch auf die Bild-URLs der Fundseite angewendet (c09). WEAK = generische
# Namensmuster ohne ID (conf 0.7). Bewusst KEIN Reuters-Muster (RTX/RTS-IDs):
# kollidiert mit Produktnamen wie "RTX4090" in Bildungsinhalten.
# ---------------------------------------------------------------------------
# (Agentur-Label, kompiliertes Muster)
_ASSET_STRONG: list[tuple[str, re.Pattern[str]]] = [
    ("getty images", re.compile(r"gettyimages[-_]\d{6,}", re.I)),
    ("istock", re.compile(r"\bistock(photo)?[-_]?\d{6,}", re.I)),   # iStock-528070276
    ("shutterstock", re.compile(r"shutterstock[-_]\d{6,}", re.I)),
    ("adobe stock", re.compile(r"adobestock[-_]?\d{6,}", re.I)),
    ("depositphotos", re.compile(r"depositphotos[-_]\d{6,}", re.I)),
    ("alamy", re.compile(r"\balamy[-_]?\w*\d{6,}", re.I)),
    ("fotolia", re.compile(r"\bfotolia[-_]\d{6,}", re.I)),
    ("imago", re.compile(r"\bimago[-_]?\d{7,}", re.I)),             # imago images Asset-ID
    ("epa", re.compile(r"\bepa\d{7,}", re.I)),                      # european pressphoto agency
    ("dpa", re.compile(r"urn[:_-]newsml[:_-]dpa\.com", re.I)),      # dpa-NewsML-ID (URL/XMP)
]

_ASSET_WEAK: list[tuple[str, re.Pattern[str]]] = [
    ("stock-foto", re.compile(r"\bstock[-_]photo[-_]", re.I)),
    ("stock-vektor", re.compile(r"\bstock[-_]vector[-_]", re.I)),
    ("123rf", re.compile(r"\b123rf[-_]", re.I)),
    ("dreamstime", re.compile(r"\bdreamstime[-_]", re.I)),
]

FILENAME_PATTERNS_STRONG: list[re.Pattern[str]] = [p for _, p in _ASSET_STRONG]
FILENAME_PATTERNS_WEAK: list[re.Pattern[str]] = [p for _, p in _ASSET_WEAK]
# Rückwärtskompatibel: kombinierte Liste
FILENAME_PATTERNS: list[re.Pattern[str]] = FILENAME_PATTERNS_STRONG + FILENAME_PATTERNS_WEAK


def match_agency_asset(text: str) -> tuple[re.Pattern[str], bool, str] | None:
    """Prüft Dateiname/URL/Metadatum auf Agentur-Asset-Muster.
    Returns (Muster, is_strong, agentur_label) des ersten Treffers oder None."""
    if not text:
        return None
    for label, pat in _ASSET_STRONG:
        if pat.search(text):
            return pat, True, label
    for label, pat in _ASSET_WEAK:
        if pat.search(text):
            return pat, False, label
    return None

# ---------------------------------------------------------------------------
# Watermark-/OCR-Textmarker (Option 7) — eingebrannter Agentur-Text
# ---------------------------------------------------------------------------
WATERMARK_TEXT_MARKERS: list[str] = [
    "shutterstock", "getty images", "gettyimages", "istock", "alamy",
    "stock.adobe.com", "adobe stock", "depositphotos", "123rf", "dreamstime",
    "preview", "sample", "watermark", "demo",
]

# ---------------------------------------------------------------------------
# CC-Lizenz-Erkennung & URI-Normalisierung
# ---------------------------------------------------------------------------
# Erkennt CC-Codes in Freitext, z.B. "CC BY-SA 4.0", "CC-BY 3.0", "CC0".
_CC_CODE = re.compile(
    r"\bCC[\s\-]?(BY(?:[\s\-]?(?:NC|ND|SA)){0,2}|0|zero)\b"
    r"(?:[\s\-]*(\d\.\d))?",
    re.I,
)

_CC_HOSTS = {"creativecommons.org", "www.creativecommons.org"}
_CC_PATH_PREFIXES = ("/licenses/", "/publicdomain/")


def find_cc_license(text: str) -> tuple[str | None, str | None]:
    """Sucht einen CC-Lizenzcode in Freitext.

    Returns (code, uri) — z.B. ("CC BY-SA 4.0",
    "https://creativecommons.org/licenses/by-sa/4.0/") oder (None, None).
    """
    if not text:
        return None, None
    m = _CC_CODE.search(text)
    if not m:
        return None, None
    raw = m.group(1).upper().replace(" ", "").replace("-", "")
    version = m.group(2)  # None, wenn keine Version im Text stand
    if raw in ("0", "ZERO"):
        return "CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/"
    # raw z.B. "BY", "BYSA", "BYNCND"
    parts = ["by"]
    for token in ("NC", "ND", "SA"):
        if token in raw[2:]:
            parts.append(token.lower())
    code_path = "-".join(parts)              # "by-sa"
    code_upper = "-".join(p.upper() for p in parts)  # "BY-SA"
    if version:
        return f"CC {code_upper} {version}", f"https://creativecommons.org/licenses/{code_path}/{version}/"
    # Ohne erkennbare Version keine Version erfinden -> versionslose Deed-URI.
    return f"CC {code_upper}", f"https://creativecommons.org/licenses/{code_path}/"


def normalize_license_uri(url: str) -> str | None:
    """Normalisiert eine CC-/PD-Lizenz-URL. Prüft den ECHTEN Host + Pfad-Präfix
    (nicht per Substring — sonst würde ein Tracking-Wrapper wie
    ``…/r?u=creativecommons.org/licenses/by/4.0/`` fälschlich als freie Lizenz
    normalisiert = False GREEN)."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().rsplit("@", 1)[-1].split(":")[0]
    if host not in _CC_HOSTS or not parts.path.startswith(_CC_PATH_PREFIXES):
        return None
    path = parts.path if parts.path.endswith("/") else parts.path + "/"
    return urlunsplit(("https", "creativecommons.org", path, "", ""))


def _compile_terms(terms: list[str]) -> re.Pattern[str]:
    """Kompiliert Terme zu einer wortgrenzen-gebundenen Alternation. Verhindert
    Substring-Fehltreffer (z. B. 'dpa' in 'Sandpapier', 'nasa' in 'nasal')."""
    cleaned = sorted({t.strip() for t in terms if t.strip()}, key=len, reverse=True)
    pattern = r"(?<!\w)(" + "|".join(re.escape(t) for t in cleaned) + r")(?!\w)"
    return re.compile(pattern, re.I)


_AGENCY_RE = _compile_terms(AGENCY_TERMS)
_FREE_SOURCE_RE = _compile_terms(FREE_SOURCE_TERMS)


def contains_agency(text: str) -> str | None:
    """Gibt den ersten (wortgrenzen-gebundenen) Agentur-Marker zurück (oder None)."""
    if not text:
        return None
    m = _AGENCY_RE.search(text)
    return m.group(1).strip().lower() if m else None


def contains_free_source(text: str) -> str | None:
    """Gibt den ersten (wortgrenzen-gebundenen) Freie-Quelle-Marker zurück (oder None)."""
    if not text:
        return None
    m = _FREE_SOURCE_RE.search(text)
    return m.group(1).strip().lower() if m else None
