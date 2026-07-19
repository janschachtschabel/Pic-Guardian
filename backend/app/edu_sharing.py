"""Minimaler edu-sharing / openeduhub REST-Client.

Nur Lesezugriff: Node-Metadaten holen und die beste Bild-URL bestimmen.
Auth ist optional (öffentliche Nodes sind anonym lesbar); für geschützte
Nodes kann ein Basic-Auth-Header durchgereicht werden.
"""

from __future__ import annotations

import base64
from urllib.parse import quote

import httpx

from .config import Repository, SETTINGS
from .net_guard import BlockedURLError, safe_get


class EduSharingError(Exception):
    """Fehler beim Zugriff auf das Repository."""


def _seg(node_id: str) -> str:
    """URL-sicheres Pfadsegment aus einer Node-/Collection-ID (verhindert
    Pfad-/Query-Injection über manipulierte IDs)."""
    return quote(node_id.strip(), safe="")


def basic_auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def _headers(auth_header: str | None) -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": SETTINGS.user_agent}
    if auth_header:
        headers["Authorization"] = auth_header
    return headers


def fetch_node(repo: Repository, node_id: str, auth_header: str | None = None) -> dict:
    """Holt das Node-Objekt (inkl. properties, preview, downloadUrl)."""
    url = (
        f"{repo.rest_root}/node/v1/nodes/-home-/{_seg(node_id)}"
        "/metadata?propertyFilter=-all-"
    )
    try:
        with httpx.Client(timeout=SETTINGS.http_timeout, follow_redirects=True) as client:
            r = client.get(url, headers=_headers(auth_header))
    except httpx.HTTPError as exc:  # Netzwerk/DNS/Timeout
        raise EduSharingError(f"Repository nicht erreichbar: {exc}") from exc
    if r.status_code == 401:
        raise EduSharingError(
            "Zugriff verweigert (401) — Node evtl. nicht öffentlich. "
            "Basic-Auth angeben."
        )
    if r.status_code == 404:
        raise EduSharingError(f"Node '{node_id}' nicht gefunden (404).")
    if r.status_code >= 400:
        raise EduSharingError(f"Repository-Fehler {r.status_code}.")
    try:
        return r.json()["node"]
    except (KeyError, ValueError) as exc:
        raise EduSharingError("Unerwartete Antwort des Repositoriums.") from exc


def pick_image_url(repo: Repository, node: dict) -> tuple[str | None, str]:
    """Wählt die aussagekräftigste Bild-URL.

    Bevorzugt die Original-Datei (Metadaten intakt), fällt auf content /
    Vorschaubild zurück. Returns (url, kind).
    """
    mimetype = (node.get("mimetype") or "").lower()
    node_id = node.get("ref", {}).get("id")

    if mimetype.startswith("image/"):
        if node.get("downloadUrl"):
            return node["downloadUrl"], "original"
        content_url = (node.get("content") or {}).get("url")
        if content_url:
            return content_url, "content"

    preview_url = (node.get("preview") or {}).get("url")
    if preview_url:
        return preview_url, "preview"

    # letzter Fallback: expliziter Preview-Endpoint
    if node_id:
        return (
            f"{repo.rest_root}/node/v1/nodes/-home-/{node_id}/preview"
            "?storeProtocol=workspace&storeId=SpacesStore",
            "preview",
        )
    return None, "none"


def download_image(url: str, auth_header: str | None = None) -> tuple[bytes, str | None]:
    """Lädt Bild-Bytes von einer (edu-sharing- oder beliebigen) URL."""
    try:
        with httpx.Client(timeout=SETTINGS.http_timeout) as client:
            r = safe_get(
                client, url, headers=_headers(auth_header),
                max_bytes=SETTINGS.max_image_bytes,
            )
    except BlockedURLError as exc:
        raise EduSharingError(f"Bild-URL blockiert: {exc}") from exc
    except httpx.HTTPError as exc:
        raise EduSharingError(f"Bild konnte nicht geladen werden: {exc}") from exc
    if r.status_code >= 400:
        raise EduSharingError(f"Bild-Download fehlgeschlagen ({r.status_code}).")
    content_type = r.headers.get("content-type", "").split(";")[0].strip() or None
    data = r.content
    if len(data) > SETTINGS.max_image_bytes:
        raise EduSharingError("Bild überschreitet die Größenbeschränkung.")
    return data, content_type


# --------------------------------------------------------------------------
# Sammlungen (ccm:map) — für die Batch-Traversierung
# --------------------------------------------------------------------------
def _paginated_list(
    repo: Repository, path: str, list_key: str, auth_header: str | None,
    params: dict | None = None, page_size: int = 100,
) -> list[dict]:
    """Ruft einen paginierten Collection-Children-Endpoint vollständig ab."""
    out: list[dict] = []
    skip = 0
    base = repo.rest_root + path
    try:
        with httpx.Client(timeout=SETTINGS.http_timeout, follow_redirects=True) as client:
            for _ in range(200):  # harte Obergrenze gegen Endlosschleife (max ~20k)
                q = {"maxItems": page_size, "skipCount": skip}
                if params:
                    q.update(params)
                r = client.get(base, params=q, headers=_headers(auth_header))
                if r.status_code == 401:
                    raise EduSharingError("Zugriff verweigert (401) — Basic-Auth angeben.")
                if r.status_code == 404:
                    raise EduSharingError("Sammlung nicht gefunden (404).")
                if r.status_code >= 400:
                    raise EduSharingError(f"Repository-Fehler {r.status_code}.")
                data = r.json()
                chunk = data.get(list_key) or []
                out.extend(chunk)
                total = (data.get("pagination") or {}).get("total")
                skip += len(chunk)
                if not chunk:
                    break
                # Wenn total bekannt ist, allein danach abbrechen — eine kurze
                # (server-gedeckelte) Seite bedeutet NICHT das Ende.
                if total is not None:
                    if skip >= total:
                        break
                elif len(chunk) < page_size:
                    break
    except httpx.HTTPError as exc:
        raise EduSharingError(f"Repository nicht erreichbar: {exc}") from exc
    return out


def list_subcollections(repo: Repository, coll_id: str, auth_header: str | None = None) -> list[dict]:
    """Direkte Untersammlungen (ccm:map) einer Sammlung."""
    return _paginated_list(
        repo,
        f"/collection/v1/collections/-home-/{_seg(coll_id)}/children/collections",
        "collections", auth_header,
    )


def list_collection_references(repo: Repository, coll_id: str, auth_header: str | None = None) -> list[dict]:
    """Referenzierte Inhalte (ccm:io) einer Sammlung."""
    return _paginated_list(
        repo,
        f"/collection/v1/collections/-home-/{_seg(coll_id)}/children/references",
        "references", auth_header, params={"propertyFilter": "-all-"},
    )


def reference_original_id(ref: dict) -> str:
    """Liefert die Original-Node-ID einer Reference (für Dedup + Metadaten)."""
    oid = ref.get("originalId")
    if not oid:
        props = ref.get("properties") or {}
        orig = props.get("ccm:original")
        if isinstance(orig, list) and orig:
            oid = orig[0]
        elif isinstance(orig, str):
            oid = orig
    return oid or (ref.get("ref") or {}).get("id", "")
