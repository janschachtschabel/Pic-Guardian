"""Zentrale Konfiguration: Repository-Registry (prod/staging) und Settings."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Repository:
    """Ein edu-sharing / openeduhub Repository."""

    id: str
    label: str
    base_url: str  # ohne abschließenden Slash, z.B. https://redaktion.openeduhub.net

    @property
    def rest_root(self) -> str:
        return f"{self.base_url}/edu-sharing/rest"

    @property
    def render_url_template(self) -> str:
        return f"{self.base_url}/edu-sharing/components/render/{{node_id}}"


# Hinterlegte Repositorien für die Node-ID-Eingabe.
REPOSITORIES: dict[str, Repository] = {
    "prod": Repository(
        id="prod",
        label="Produktion — redaktion.openeduhub.net",
        base_url="https://redaktion.openeduhub.net",
    ),
    "staging": Repository(
        id="staging",
        label="Staging — repository.staging.openeduhub.net",
        base_url="https://repository.staging.openeduhub.net",
    ),
}

DEFAULT_REPOSITORY = "prod"


@dataclass(frozen=True)
class Settings:
    # Netzwerk. User-Agent: Wikimedia verlangt einen aussagekräftigen UA MIT
    # Kontaktinfo (sonst IP-Block). Für den Produktivbetrieb via ENV
    # BILDCHECK_USER_AGENT eine echte Kontakt-URL/-Mail setzen.
    http_timeout: float = 30.0
    user_agent: str = "bild-check/0.1 (+https://openeduhub.net; kontakt@openeduhub.net)"
    # Upload-/Download-Limits
    max_image_bytes: int = 25 * 1024 * 1024  # 25 MB
    # Anzeige-Thumbnail (data-URI im Response) — begrenzt die Response-Größe
    preview_max_edge: int = 900
    # Externe Dienste (Bildübertragung!): in der EINZELPRÜFUNG standardmäßig aktiv,
    # aber mit Frist (s.u.); im BATCH standardmäßig aus (Masse + Rate-Limits).
    external_default_single: bool = True
    external_default_batch: bool = False
    # Frist pro externem Check (Sekunden). Antwortet der Dienst nicht rechtzeitig,
    # wird er übersprungen (UNAVAILABLE) — die Prüfung wird NICHT abgebrochen.
    external_timeout: float = 8.0
    # Originalbild von der Fundseite laden und dessen Metadaten prüfen (Option 5
    # auf dem un-re-gehosteten Bild). Kostet einen zusätzlichen Download pro Node
    # -> standardmäßig AUS; für die Ingestion/Erschließung sinnvoll einzuschalten.
    fetch_origin_image: bool = False
    # Strenger Modus: Bilder von Presse-/Rundfunkseiten OHNE bildbezogenen
    # Positivbeleg werden zum Verdachtsfall abgestuft (schwaches RED-Signal),
    # weil Fotos dort überwiegend Agenturmaterial sind. Default aus, weil die
    # Sender auch Eigenmaterial publizieren (ENV BILDCHECK_STRICT_NEWS=1).
    strict_news_domains: bool = False
    # Wayback-Machine-Fallback für tote/umgezogene Fundseiten. Überträgt nur
    # die Fundseiten-URL an archive.org (nie das Bild). ENV BILDCHECK_WAYBACK=0.
    wayback_fallback: bool = True
    # CORS: erlaubte Frontend-Origins (Komma-getrennt via ENV überschreibbar)
    cors_origins: tuple[str, ...] = (
        "http://localhost:4200",
        "http://127.0.0.1:4200",
    )


def load_settings() -> Settings:
    """Settings aus Umgebungsvariablen (optional) laden."""
    origins_env = os.environ.get("BILDCHECK_CORS_ORIGINS")
    cors = (
        tuple(o.strip() for o in origins_env.split(",") if o.strip())
        if origins_env
        else Settings.cors_origins
    )
    ua = os.environ.get("BILDCHECK_USER_AGENT") or Settings.user_agent
    strict = os.environ.get("BILDCHECK_STRICT_NEWS", "") == "1"
    wayback = os.environ.get("BILDCHECK_WAYBACK", "1") != "0"
    try:
        ext_timeout = float(os.environ.get("BILDCHECK_EXTERNAL_TIMEOUT", "") or Settings.external_timeout)
    except ValueError:
        ext_timeout = Settings.external_timeout
    fetch_origin = os.environ.get("BILDCHECK_FETCH_ORIGIN", "") == "1"
    return Settings(
        cors_origins=cors, user_agent=ua,
        strict_news_domains=strict, wayback_fallback=wayback,
        external_timeout=ext_timeout, fetch_origin_image=fetch_origin,
    )


SETTINGS = load_settings()
