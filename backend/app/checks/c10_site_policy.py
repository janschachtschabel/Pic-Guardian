"""Prüfschritt — Site-Policy (Option 4): robots.txt, Meta-Robots, TDM-Vorbehalt.

Nur ein Soft-Signal (seiten-, nicht bildbezogen) — laut Rechtsprechung relevant
für die „schlichte Einwilligung" (BGH Vorschaubilder), aber nie alleinige
Grundlage. Deshalb höchstens YELLOW.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from ..config import SETTINGS
from ..net_guard import BlockedURLError, safe_get
from ..schemas import CheckSignal, Verdict
from .base import BaseCheck, CheckContext

from bs4 import BeautifulSoup


class SitePolicyCheck(BaseCheck):
    id = "site_policy"
    label = "Site-Policy (robots.txt / Meta / TDM)"
    category = "page"

    def applies(self, ctx: CheckContext) -> bool:
        return bool(ctx.image.source_page or ctx.image.page_html)

    def execute(self, ctx: CheckContext) -> CheckSignal:
        evidence: list[str] = []
        hits = 0

        # 1) Meta-Robots im HTML
        if ctx.image.page_html:
            try:
                soup = BeautifulSoup(ctx.image.page_html, "lxml")
                for meta in soup.find_all("meta"):
                    if (meta.get("name") or "").lower() == "robots":
                        content = (meta.get("content") or "").lower()
                        if "noimageindex" in content:
                            evidence.append("meta robots: noimageindex")
                            hits += 1
                        if "noindex" in content:
                            evidence.append("meta robots: noindex")
                            hits += 1
            except Exception:  # noqa: BLE001
                pass

        # 2) robots.txt der Domain — spezifische TDM-/AI-Vorbehaltsmarker.
        #    (Bewusst kein globaler "disallow"-Substring-Test: der wäre nicht der
        #     Googlebot-Image-Stanza zuordenbar und würde falsch anschlagen.)
        if ctx.image.source_page:
            parsed = urlparse(ctx.image.source_page)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            try:
                with httpx.Client(timeout=10.0) as client:
                    r = safe_get(
                        client, robots_url,
                        headers={"User-Agent": SETTINGS.user_agent}, max_bytes=1_000_000,
                    )
                if r.status_code < 400:
                    body = r.text.lower()
                    if "noai" in body or "tdmrep" in body or "text-and-data-mining" in body:
                        evidence.append("robots.txt/ai.txt: TDM-Vorbehalt (§ 44b UrhG)")
                        hits += 1
            except (httpx.HTTPError, BlockedURLError):
                pass

        if hits == 0:
            return self.signal(
                verdict=Verdict.NEUTRAL,
                summary="Keine einschränkende Site-Policy erkennbar.",
                evidence=evidence,
            )
        return self.signal(
            verdict=Verdict.YELLOW,
            confidence=0.35,
            summary="Seite signalisiert Nutzungsvorbehalt (Soft-Signal, nicht "
            "bildbezogen).",
            evidence=evidence,
        )
