"""Prüfschritt 2 — Domain-/Dateinamen-Heuristik (Option 3).

Soft-Signal: Whitelist-Treffer (freie Quelle) ist verlässlicher als ein
Blacklist-Treffer (Agenturbilder erscheinen auch auf Blogs). Daher moderate
Konfidenz — die Aggregation kombiniert das mit anderen Signalen.
"""

from __future__ import annotations

from urllib.parse import urlparse

from ..config import REPOSITORIES, SETTINGS
from ..schemas import CheckSignal, SignalStatus, Verdict
from ..wordlists import (
    DOMAIN_BLACKLIST,
    DOMAIN_WHITELIST,
    NEWS_PRESS_DOMAINS,
    match_agency_asset,
)
from .base import BaseCheck, CheckContext

_REPO_HOSTS = {urlparse(r.base_url).netloc for r in REPOSITORIES.values()}


def _host_matches(host: str, needles: list[str]) -> str | None:
    # Exakter Host oder echte Subdomain — NICHT bloßer Substring (sonst würde
    # "pexels.com.evil.ru" die Whitelist bzw. Blacklist treffen).
    for n in needles:
        if host == n or host.endswith("." + n):
            return n
    return None


def _image_bound_green(ctx: CheckContext) -> bool:
    """Hat ein früherer Check schon einen bildgebundenen Positivbeleg geliefert?
    (Selbstauskünfte und seitenweite Lizenzangaben zählen nicht.)"""
    for s in ctx.prior_signals:
        if (
            getattr(s, "status", None) == SignalStatus.DONE
            and s.verdict == Verdict.GREEN
            and s.confidence >= 0.7
            and s.id not in ("declared_license", "domain_filename")
            and (s.data or {}).get("license_scope") != "page"
        ):
            return True
    return False


class DomainFilenameCheck(BaseCheck):
    id = "domain_filename"
    label = "Domain- & Dateinamen-Heuristik"
    category = "page"

    def execute(self, ctx: CheckContext) -> CheckSignal:
        img = ctx.image
        hosts: set[str] = set()
        if img.source_domain:
            hosts.add(img.source_domain.lower())
        if img.origin_url:
            h = urlparse(img.origin_url).netloc.lower()
            if h and h not in _REPO_HOSTS:  # edu-sharing-Host ist nicht aussagekräftig
                hosts.add(h)

        evidence: list[str] = []
        filename = img.filename or ""

        # Blacklist-Domain
        for host in hosts:
            hit = _host_matches(host, DOMAIN_BLACKLIST)
            if hit:
                return self.signal(
                    verdict=Verdict.RED,
                    confidence=0.75,
                    summary=f"Bild liegt auf Agentur-/Stock-Domain: {hit}.",
                    evidence=[f"Host: {host}"],
                )

        # Dateiname-Muster: Muster MIT Agentur-Asset-ID (z.B. gettyimages-123456)
        # sind quasi beweisend -> starkes RED; generische Muster bleiben schwach.
        hit_pat = match_agency_asset(filename)
        if hit_pat:
            pat, strong, label = hit_pat
            return self.signal(
                verdict=Verdict.RED,
                confidence=0.8 if strong else 0.7,
                summary=f"Dateiname folgt einem Agentur-Asset-Muster ({label})"
                + (" — mit Asset-ID" if strong else "") + ".",
                evidence=[f"Dateiname: {filename}", f"Muster: {pat.pattern}"],
                data={"supplier": label} if strong else None,
            )

        # Whitelist-Domain
        for host in hosts:
            hit = _host_matches(host, DOMAIN_WHITELIST)
            if hit:
                return self.signal(
                    verdict=Verdict.GREEN,
                    confidence=0.5,
                    summary=f"Bild von bekannter freier Quelle: {hit}. "
                    "Hinweis: Quelle ≠ automatisch CC.",
                    evidence=[f"Host: {host}"],
                )

        # Presse-/Rundfunk-Domain: Fotos dort sind überwiegend Agenturmaterial —
        # auch auf „neutral wirkenden" Seiten (Batch-Evidenz: bpb, DW, dlf).
        # Default: Warnhinweis (YELLOW). Strenger Modus: Verdacht (schwaches RED,
        # das die Aggregation ohne Positivbeleg zu „Verdacht" macht). Entfällt,
        # wenn ein früherer Check bereits einen BILDGEBUNDENEN Positivbeleg fand.
        for host in hosts:
            hit = _host_matches(host, NEWS_PRESS_DOMAINS)
            if hit and not _image_bound_green(ctx):
                strict = SETTINGS.strict_news_domains
                return self.signal(
                    verdict=Verdict.RED if strict else Verdict.YELLOW,
                    confidence=0.5,
                    summary=f"Fundseite ist ein Presse-/Rundfunkangebot ({hit}) — "
                    "Fotos dort sind überwiegend lizenziertes Agenturmaterial; "
                    "kein bildbezogener Beleg vorhanden.",
                    evidence=[f"Host: {host}",
                              "Modus: streng" if strict else "Modus: Hinweis"],
                )

        if hosts or filename:
            evidence = [f"Hosts: {', '.join(sorted(hosts)) or '—'}", f"Dateiname: {filename or '—'}"]
        return self.signal(
            verdict=Verdict.NEUTRAL,
            summary="Kein Domain-/Dateinamen-Signal.",
            evidence=evidence,
        )
