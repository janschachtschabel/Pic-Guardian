"""Prüfschritt 1 — Deklarierte Lizenz aus dem edu-sharing Repository.

Nur im Node-Modus anwendbar. Liest die im Repository gepflegten Lizenz-
Properties. Eine deklarierte freie Lizenz ist ein starkes (aber nicht
technisch bewiesenes) GREEN-Signal; eine Agentur-Nennung ein RED-Signal.
"""

from __future__ import annotations

from ..schemas import CheckSignal, SignalStatus, Verdict
from ..wordlists import contains_agency
from .base import BaseCheck, CheckContext

_V = "{v}"
# edu-sharing ccm:commonlicense_key  ->  (Ampel, Label, URI-Template)
LICENSE_MAP: dict[str, tuple[Verdict, str, str | None]] = {
    "CC_0": (Verdict.GREEN, "CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/"),
    "PDM": (Verdict.GREEN, "Public Domain Mark", "https://creativecommons.org/publicdomain/mark/1.0/"),
    "CC_BY": (Verdict.GREEN, f"CC BY {_V}", f"https://creativecommons.org/licenses/by/{_V}/"),
    "CC_BY_SA": (Verdict.GREEN, f"CC BY-SA {_V}", f"https://creativecommons.org/licenses/by-sa/{_V}/"),
    "CC_BY_ND": (Verdict.GREEN, f"CC BY-ND {_V}", f"https://creativecommons.org/licenses/by-nd/{_V}/"),
    "CC_BY_NC": (Verdict.GREEN, f"CC BY-NC {_V}", f"https://creativecommons.org/licenses/by-nc/{_V}/"),
    "CC_BY_NC_SA": (Verdict.GREEN, f"CC BY-NC-SA {_V}", f"https://creativecommons.org/licenses/by-nc-sa/{_V}/"),
    "CC_BY_NC_ND": (Verdict.GREEN, f"CC BY-NC-ND {_V}", f"https://creativecommons.org/licenses/by-nc-nd/{_V}/"),
    "COPYRIGHT_FREE": (Verdict.GREEN, "Gemeinfrei / copyright-frei", None),
    "SCHULLIZENZ": (Verdict.YELLOW, "Schullizenz", None),
    "NONE": (Verdict.YELLOW, "Keine/individuelle Lizenz", None),
    "COPYRIGHT_LICENSE": (Verdict.YELLOW, "© Alle Rechte vorbehalten", None),
    "CUSTOM": (Verdict.YELLOW, "Individuelle Lizenz", None),
}


def _first(value) -> str | None:
    if isinstance(value, list):
        return value[0] if value else None
    return value or None


class DeclaredLicenseCheck(BaseCheck):
    id = "declared_license"
    label = "Deklarierte Lizenz (Repository)"
    category = "repository"

    def applies(self, ctx: CheckContext) -> bool:
        return ctx.image.mode == "node" and ctx.image.node is not None

    def execute(self, ctx: CheckContext) -> CheckSignal:
        props = ctx.image.node.get("properties") or {}
        key = (_first(props.get("ccm:commonlicense_key")) or "").upper().strip()
        version = _first(props.get("ccm:commonlicense_cc_version"))  # keine Version erfinden
        rights = _first(props.get("cclom:rights_description")) or ""
        author = _first(props.get("ccm:author_freetext")) or ""
        publisher = _first(props.get("ccm:lifecyclecontributer_publisher")) or ""

        evidence: list[str] = []
        if key:
            evidence.append(f"ccm:commonlicense_key = {key}")
        if rights:
            evidence.append(f"Rechtehinweis: {rights[:200]}")
        if author:
            evidence.append(f"Urheber: {author}")

        # Agentur-Nennung im Rechte-/Autortext schlägt alles.
        agency = contains_agency(f"{rights} {author} {publisher}")
        if agency:
            return self.signal(
                verdict=Verdict.RED,
                confidence=0.85,
                summary=f"Agentur im Rechtehinweis genannt: {agency}.",
                evidence=evidence,
            )

        if not key or key in ("", "NONE_LICENSE"):
            return self.signal(
                verdict=Verdict.YELLOW,
                confidence=0.3,
                status=SignalStatus.DONE,
                summary="Keine Lizenz im Repository deklariert.",
                evidence=evidence or ["ccm:commonlicense_key ist leer"],
            )

        mapped = LICENSE_MAP.get(key)
        if not mapped:
            return self.signal(
                verdict=Verdict.YELLOW,
                confidence=0.3,
                summary=f"Unbekannter Lizenzschlüssel '{key}'.",
                evidence=evidence,
            )

        verdict, label, uri_tpl = mapped
        if version:
            label = label.replace(_V, version)
            uri = uri_tpl.replace(_V, version) if uri_tpl else None
        else:
            # Ohne Version: " {v}" aus Label und "{v}/" aus URI entfernen.
            label = label.replace(f" {_V}", "")
            uri = uri_tpl.replace(f"{_V}/", "") if uri_tpl else None
        if uri:
            evidence.append(uri)
        conf = 0.7 if verdict is Verdict.GREEN else 0.5
        data: dict = {"license_label": label}
        if uri:
            data["license_uri"] = uri
        # Ausdrückliche Schutzrechts-Deklaration ist eine konkrete Rechteangabe
        # (nicht bloß „keine Lizenz") -> als license_field führen, damit die
        # Aggregation den Fall auf „zu prüfen" statt „nicht messbar" hebt.
        if key == "COPYRIGHT_LICENSE":
            data["license_field"] = label
        return self.signal(
            verdict=verdict,
            confidence=conf,
            summary=f"Repository deklariert: {label}.",
            evidence=evidence,
            data=data,
        )
