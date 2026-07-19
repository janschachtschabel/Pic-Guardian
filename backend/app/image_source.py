"""ImageContext + Loader für die drei Eingabequellen (URL, Upload, Node-ID).

Alle Checks arbeiten ausschließlich auf dem ImageContext, damit sie von der
Herkunft des Bildes entkoppelt sind (Voraussetzung für die Nachnutzung als
eigenständiger Prüfdienst).
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from PIL import Image

from . import edu_sharing
from .config import Repository, SETTINGS
from .net_guard import BlockedURLError, safe_get

# Schutz gegen Decompression-Bomben: kleine, hochkomprimierte Datei mit riesigen
# Pixel-Dimensionen. Begrenzt die Bitmap-Allokation bei Image.load()/thumbnail().
Image.MAX_IMAGE_PIXELS = 64_000_000  # ~64 MP


class ImageLoadError(Exception):
    """Bild konnte nicht geladen/verarbeitet werden (Nutzerfehler)."""


@dataclass
class ImageContext:
    """Alles, was die Checks über ein Bild wissen müssen."""

    data: bytes
    mode: str  # url | upload | node

    mime: str | None = None
    width: int | None = None
    height: int | None = None
    filename: str | None = None

    origin_url: str | None = None     # URL der eigentlichen Bilddatei
    source_page: str | None = None    # Fundseite (für Seiten-Checks)
    source_domain: str | None = None

    node_id: str | None = None
    repository: str | None = None      # Repository-ID (prod/staging)
    node: dict | None = None           # edu-sharing Node-Objekt

    # Fundseiten-HTML (für Seiten-Checks Option 1/2/4)
    page_html: str | None = None
    page_fetch_note: str | None = None

    # abgeleitet
    load_note: str | None = None
    _pil: Image.Image | None = field(default=None, repr=False)

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    def pil(self) -> Image.Image | None:
        """Lazily geöffnetes PIL-Image (oder None bei nicht-Rasterformaten)."""
        if self._pil is None:
            try:
                img = Image.open(io.BytesIO(self.data))
                img.load()
                self._pil = img
            except Exception:  # noqa: BLE001 — Pillow wirft diverse Typen
                self._pil = None
        return self._pil


def _probe(ctx: ImageContext) -> None:
    """Ergänzt mime/width/height via Pillow, wo möglich."""
    img = ctx.pil()
    if img is not None:
        ctx.width, ctx.height = img.size
        fmt_mime = Image.MIME.get(img.format or "")
        if fmt_mime:
            ctx.mime = fmt_mime
    if ctx.data[:5] == b"<?xml" or ctx.data[:4] == b"<svg":
        ctx.mime = ctx.mime or "image/svg+xml"


def _guard_size(data: bytes) -> None:
    if len(data) == 0:
        raise ImageLoadError("Leere Datei erhalten.")
    if len(data) > SETTINGS.max_image_bytes:
        raise ImageLoadError(
            f"Bild ist größer als das Limit von "
            f"{SETTINGS.max_image_bytes // (1024 * 1024)} MB."
        )


def fetch_page_html(url: str) -> tuple[str | None, str | None]:
    """Lädt das HTML der Fundseite (für die Seiten-Checks). Fehlertolerant:
    Returns (html, note) — html ist None, wenn nicht ladbar/kein HTML.
    Bei toter/umgezogener Seite optionaler Wayback-Machine-Fallback (überträgt
    nur die URL an archive.org, nie das Bild).
    """
    if not url:
        return None, None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None, "Fundseite ist keine http(s)-URL."
    headers = {"User-Agent": SETTINGS.user_agent, "Accept": "text/html,*/*"}
    try:
        with httpx.Client(timeout=SETTINGS.http_timeout) as client:
            r = safe_get(client, url, headers=headers, max_bytes=8_000_000)
    except BlockedURLError as exc:
        return None, f"Fundseite blockiert: {exc}"
    except httpx.HTTPError as exc:
        return _wayback_fallback(url, f"Fundseite nicht erreichbar: {exc}")
    if r.status_code >= 400:
        return _wayback_fallback(url, f"Fundseite lieferte HTTP {r.status_code}.")
    if "html" not in r.headers.get("content-type", "").lower():
        return None, "Fundseite ist kein HTML-Dokument."
    html = r.text
    return (html[:4_000_000], None)  # Größe begrenzen


def parse_wayback_availability(payload: dict) -> tuple[str | None, str | None]:
    """Extrahiert (snapshot_url, timestamp) aus der Availability-API-Antwort."""
    snap = ((payload.get("archived_snapshots") or {}).get("closest")) or {}
    if snap.get("available") and snap.get("url"):
        u = str(snap["url"])
        # https erzwingen — die API liefert historisch http-URLs
        if u.startswith("http://"):
            u = "https://" + u[len("http://"):]
        return u, str(snap.get("timestamp") or "")
    return None, None


def _wayback_fallback(url: str, note: str) -> tuple[str | None, str | None]:
    """Versucht, einen Wayback-Snapshot der toten Fundseite zu laden."""
    if not SETTINGS.wayback_fallback:
        return None, note
    from .rate_limit import throttle  # später Import vermeidet Zyklen beim Start

    headers = {"User-Agent": SETTINGS.user_agent}
    try:
        throttle("https://archive.org/")
        with httpx.Client(timeout=SETTINGS.http_timeout) as client:
            r = client.get(
                "https://archive.org/wayback/available",
                params={"url": url}, headers=headers,
            )
        snap_url, ts = parse_wayback_availability(r.json() if r.status_code == 200 else {})
        if not snap_url:
            return None, note + " Kein Wayback-Snapshot vorhanden."
        throttle(snap_url)
        with httpx.Client(timeout=SETTINGS.http_timeout) as client:
            r2 = safe_get(client, snap_url, headers=headers, max_bytes=8_000_000)
        if r2.status_code >= 400 or "html" not in r2.headers.get("content-type", "").lower():
            return None, note + " Wayback-Snapshot nicht ladbar."
        stamp = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}" if len(ts) >= 8 else ts
        return (
            r2.text[:4_000_000],
            note + f" Seiten-Checks laufen auf Wayback-Snapshot vom {stamp}.",
        )
    except Exception:  # noqa: BLE001 — Fallback darf den Load nie kippen
        return None, note


# --------------------------------------------------------------------------
# Loader
# --------------------------------------------------------------------------
def load_from_url(url: str, source_page: str | None = None) -> ImageContext:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ImageLoadError("Bitte eine gültige http(s)-URL angeben.")
    headers = {"User-Agent": SETTINGS.user_agent, "Accept": "image/*,*/*"}
    try:
        with httpx.Client(timeout=SETTINGS.http_timeout) as client:
            r = safe_get(client, url, headers=headers, max_bytes=SETTINGS.max_image_bytes)
    except BlockedURLError as exc:
        raise ImageLoadError(f"URL blockiert: {exc}") from exc
    except httpx.HTTPError as exc:
        raise ImageLoadError(f"URL nicht erreichbar: {exc}") from exc
    if r.status_code >= 400:
        raise ImageLoadError(f"Download fehlgeschlagen (HTTP {r.status_code}).")
    data = r.content
    _guard_size(data)
    mime = r.headers.get("content-type", "").split(";")[0].strip() or None
    ctx = ImageContext(
        data=data,
        mode="url",
        mime=mime,
        filename=parsed.path.rsplit("/", 1)[-1] or None,
        origin_url=url,
        source_page=source_page,
        source_domain=parsed.netloc.lower() or None,
    )
    _probe(ctx)
    if source_page:
        ctx.page_html, ctx.page_fetch_note = fetch_page_html(source_page)
    return ctx


def load_from_upload(filename: str | None, data: bytes) -> ImageContext:
    _guard_size(data)
    ctx = ImageContext(
        data=data,
        mode="upload",
        filename=filename,
    )
    _probe(ctx)
    return ctx


def load_from_node(
    repo: Repository, node_id: str, auth_header: str | None = None
) -> ImageContext:
    node = edu_sharing.fetch_node(repo, node_id, auth_header)
    img_url, kind = edu_sharing.pick_image_url(repo, node)
    if not img_url:
        raise ImageLoadError("Node enthält kein darstellbares Bild.")
    data, mime = edu_sharing.download_image(img_url, auth_header)
    _guard_size(data)

    # Original-Quellseite des gecrawlten Materials, falls vorhanden.
    props = node.get("properties") or {}
    source_page = _first(props.get("ccm:wwwurl")) or _first(props.get("cclom:location"))
    source_domain = None
    if source_page:
        source_domain = urlparse(source_page).netloc.lower() or None

    ctx = ImageContext(
        data=data,
        mode="node",
        mime=mime,
        filename=node.get("name"),
        origin_url=img_url,
        source_page=source_page,
        source_domain=source_domain,
        node_id=node.get("ref", {}).get("id", node_id),
        repository=repo.id,
        node=node,
        load_note=f"Geladen aus edu-sharing ({kind}).",
    )
    _probe(ctx)
    # Fundseite = ccm:wwwurl des Repository-Inhalts -> Seiten-Checks ermöglichen
    if source_page:
        ctx.page_html, ctx.page_fetch_note = fetch_page_html(source_page)
    return ctx


def _first(value) -> str | None:
    """edu-sharing-Properties sind Listen — ersten Wert holen."""
    if isinstance(value, list):
        return value[0] if value else None
    return value or None


# --------------------------------------------------------------------------
# Anzeige-Thumbnail (base64 data-URI) — begrenzt die Response-Größe und
# umgeht CORS/Auth im Frontend.
# --------------------------------------------------------------------------
def build_preview_data_uri(ctx: ImageContext) -> str | None:
    img = ctx.pil()
    if img is None:
        # Nicht-Raster (z.B. SVG): Originalbytes einbetten, wenn klein genug.
        if ctx.mime and ctx.size_bytes <= 1_500_000:
            b64 = base64.b64encode(ctx.data).decode()
            return f"data:{ctx.mime};base64,{b64}"
        return None
    try:
        preview = img.copy()
        preview.thumbnail(
            (SETTINGS.preview_max_edge, SETTINGS.preview_max_edge)
        )
        buf = io.BytesIO()
        if preview.mode in ("RGBA", "LA", "P"):
            preview = preview.convert("RGBA")
            preview.save(buf, format="PNG")
            mime = "image/png"
        else:
            preview = preview.convert("RGB")
            preview.save(buf, format="JPEG", quality=82)
            mime = "image/jpeg"
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:{mime};base64,{b64}"
    except Exception:  # noqa: BLE001
        return None
