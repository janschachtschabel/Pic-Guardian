"""SSRF-Schutz für nutzergesteuerte Fetches (Bild-URL, Fundseite, Node-Preview).

Der Dienst lädt bewusst externe URLs — aber niemals interne/private Ziele. Vor
jedem Hop (auch Redirects) wird der Zielhost aufgelöst und gegen private,
loopback-, link-local- und reservierte Adressbereiche geprüft (u. a. gegen
`169.254.169.254` Cloud-Metadata). Zusätzlich wird die Antwortgröße vor dem
vollständigen Laden über Content-Length begrenzt.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

import httpx


class BlockedURLError(Exception):
    """URL zeigt auf ein nicht erlaubtes (internes/privates) Ziel."""


def assert_public_url(url: str) -> None:
    """Wirft BlockedURLError, wenn die URL kein öffentliches http(s)-Ziel ist."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedURLError(f"Schema '{parts.scheme or '—'}' nicht erlaubt.")
    host = parts.hostname
    if not host:
        raise BlockedURLError("URL ohne Host.")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedURLError(f"Host nicht auflösbar: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise BlockedURLError(f"Interne/private Adresse blockiert ({ip}).")


def safe_get(
    client: httpx.Client,
    url: str,
    *,
    headers: dict | None = None,
    max_redirects: int = 5,
    max_bytes: int | None = None,
) -> httpx.Response:
    """GET mit SSRF-Guard vor jedem Hop und optionaler Größenobergrenze.

    Redirects werden manuell verfolgt, damit jedes Ziel neu validiert wird
    (follow_redirects würde die Guard-Prüfung umgehen).
    """
    current = url
    for _ in range(max_redirects + 1):
        assert_public_url(current)
        # Streaming, damit die Größe HART begrenzt werden kann (ein chunked-
        # Response ohne Content-Length würde bei client.get() sonst unbegrenzt
        # in den RAM gepuffert -> OOM).
        req = client.build_request("GET", current, headers=headers)
        resp = client.send(req, stream=True, follow_redirects=False)
        try:
            if resp.is_redirect and resp.headers.get("location"):
                nxt = resp.next_request
                if nxt is None:
                    raise BlockedURLError("Ungültiger Redirect.")
                resp.close()
                current = str(nxt.url)
                continue
            if max_bytes is not None:
                clen = resp.headers.get("content-length")
                if clen and clen.isdigit() and int(clen) > max_bytes:
                    raise BlockedURLError("Antwort überschreitet die Größenbeschränkung.")
            # Body inkrementell lesen und bei Überschreitung sofort abbrechen.
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise BlockedURLError("Antwort überschreitet die Größenbeschränkung.")
                chunks.append(chunk)
            resp._content = b"".join(chunks)  # macht .content/.text/.json() nutzbar
            resp.is_stream_consumed = True
            return resp
        except BaseException:
            resp.close()
            raise
    raise BlockedURLError("Zu viele Redirects.")
