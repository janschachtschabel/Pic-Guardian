"""Aggregation der Einzelsignale zur Gesamt-Ampel + Empfehlung.

Regeln (angelehnt an die Vorlage, Default-Deny):
  * starkes RED (conf >= 0.8) ohne starkes GREEN            -> RED
  * starkes RED UND starkes GREEN (Widerspruch)            -> YELLOW (Review)
  * nur schwaches RED                                       -> YELLOW (Verdacht)
  * starkes GREEN (Positivnachweis) und kein RED           -> GREEN
  * sonst (kein/uneindeutiges Signal)                       -> YELLOW (Default-Deny)
"""

from __future__ import annotations

from .image_source import ImageContext
from .schemas import CheckSignal, ExtractedFields, SignalStatus, Verdict

_STRONG_RED = 0.8
_STRONG_GREEN = 0.7  # entspricht Positivnachweis (CC-URI, SHA-1, Deklaration, Manifest)

# Vier-stufige Ergebnis-Skala (Endnutzer-Sicht), abgeleitet aus der Ampel +
# den Einzelsignalen. Die feinere 5-Wert-Ampel (Verdict) bleibt darunter.
CATEGORY_LABELS: dict[str, str] = {
    "unproblematisch": "Unproblematisch",
    "zu_pruefen": "Zu prüfen",
    "nicht_messbar": "Nicht messbar",
    "problematisch": "Problematisch",
}


# Konkrete Rechte-/Urheberangaben (nicht bloß „keine Lizenz deklariert"): ein
# sichtbarer Credit, ein Copyright-/Urheber-Metadatum oder eine ausdrückliche
# „alle Rechte vorbehalten"-Deklaration. Liegt so etwas vor, aber KEIN entlastender
# Lizenzbeleg, ist der Fall review-würdig (zu prüfen), nicht bloß „nicht messbar".
_RIGHTS_ATTRIBUTION_KEYS = ("credit_text", "creator", "license_field", "acquire_url")


def result_category(verdict: Verdict, signals: list[CheckSignal]) -> str:
    """Bildet die Gesamt-Ampel + Einzelsignale auf die 4-stufige Ergebnis-Skala ab.

    * RED                                        -> problematisch
    * GREEN                                      -> unproblematisch
    * YELLOW mit Warnsignal ODER Rechteangabe    -> zu_pruefen
    * YELLOW ganz ohne Signal (Default-Deny)     -> nicht_messbar
    """
    if verdict == Verdict.RED:
        return "problematisch"
    if verdict == Verdict.GREEN:
        return "unproblematisch"
    done = [s for s in signals if s.status == SignalStatus.DONE]
    if any(s.verdict == Verdict.RED for s in done):
        return "zu_pruefen"
    # Urheber-/Rechteangabe vorhanden, aber keine entlastende Lizenz -> Review.
    has_attribution = any(
        (s.data or {}).get(k) for s in done for k in _RIGHTS_ATTRIBUTION_KEYS
    )
    return "zu_pruefen" if has_attribution else "nicht_messbar"

# GREEN-Quellen, die eine bloße Selbstauskunft sind: die Repo-Deklaration und die
# Domain-Whitelist. Sie dürfen einen starken externen Negativbeleg (z.B. einen
# Agentur-Nachweis auf der Quellseite) NICHT überstimmen — bei gecrawlten Inhalten
# ist die Deklaration häufig genau der Fehler, den das Tool aufdecken soll.
_SELF_REPORT_GREEN = {"declared_license", "domain_filename"}

# Reihenfolge, in der Extraktionsfelder Priorität haben (erster Treffer gewinnt).
_FIELD_KEYS = (
    "license_uri",
    "license_label",
    "license_field",
    "acquire_url",
    "credit_text",
    "creator",
    "supplier",
    "phash",
    "sha1",
    "c2pa_status",
    "watermark_score",
)


def _merge_fields(signals: list[CheckSignal], image: ImageContext) -> ExtractedFields:
    merged: dict[str, object] = {}
    # Nach Beweiskraft (Confidence) absteigend, damit der stärkere Beleg (z.B.
    # Commons SHA-1-Treffer) die Attributionsfelder gewinnt — nicht die
    # Check-Reihenfolge. Hashes (sha1/phash) sind faktisch, Reihenfolge egal.
    for sig in sorted(signals, key=lambda s: s.confidence, reverse=True):
        for key, val in (sig.data or {}).items():
            if key in _FIELD_KEYS and val not in (None, "") and key not in merged:
                merged[key] = val
    fields = ExtractedFields(**merged)  # type: ignore[arg-type]
    fields.source_domain = image.source_domain
    fields.source_page = image.source_page
    return fields


def _done(signals: list[CheckSignal], verdict: Verdict) -> list[CheckSignal]:
    return [s for s in signals if s.status == SignalStatus.DONE and s.verdict == verdict]


def aggregate(
    signals: list[CheckSignal], image: ImageContext
) -> tuple[Verdict, float, str, str, ExtractedFields, str]:
    fields = _merge_fields(signals, image)

    reds = _done(signals, Verdict.RED)
    greens = _done(signals, Verdict.GREEN)
    yellows = _done(signals, Verdict.YELLOW)

    strong_reds = [s for s in reds if s.confidence >= _STRONG_RED]
    strong_greens = [s for s in greens if s.confidence >= _STRONG_GREEN]
    # Nur UNABHÄNGIGE Positivbelege (nicht die Repo-Selbstauskunft) können einen
    # starken Negativbeleg zu einem echten Widerspruch machen. SEITENWEITE
    # Lizenzangaben (license_scope="page", z.B. der CC-Hinweis für den
    # Artikeltext einer Nachrichtenseite) belegen die Bildlizenz ebenso wenig —
    # sie decken eingebettete Agenturbilder gerade nicht ab.
    independent_greens = [
        s for s in strong_greens
        if s.id not in _SELF_REPORT_GREEN
        and (s.data or {}).get("license_scope") != "page"
    ]

    # Ein einzelnes schwaches RED (z.B. nur Domain-/Dateiname-Heuristik) bleibt
    # YELLOW; mehrere unabhängige RED-Signale verhärten sich zu RED
    # ("Blacklist-Treffer nur in Kombination hart auf RED", Option 3).
    hard_red = bool(strong_reds) or len(reds) >= 2

    reasons_red = [f"{s.label}: {s.summary}" for s in reds]
    reasons_green = [f"{s.label}: {s.summary}" for s in greens]

    if hard_red:
        if independent_greens:
            verdict = Verdict.YELLOW
            conf = max(s.confidence for s in reds)
            headline = "Widersprüchliche Signale — Prüfung nötig"
            rec = (
                "Es liegen sowohl ein Warnsignal als auch ein unabhängiger "
                "Positivbeleg vor. Automatische Freigabe ausgeschlossen — "
                "redaktionelle Prüfung. Im Zweifel keine Auslieferung.\n"
                + _bullets(reasons_red + reasons_green)
            )
        else:
            verdict = Verdict.RED
            conf = max(s.confidence for s in reds)
            if strong_greens:  # nur überstimmte Selbstauskunft / Seitenlizenz
                headline = "Lizenzpflichtig / geschützt — Deklaration widersprochen"
                rec = (
                    "Ein starkes Warnsignal (z.B. Agentur-Nachweis auf der Quellseite) "
                    "widerspricht der deklarierten freien Lizenz (Repo-Deklaration bzw. "
                    "seitenweite Lizenzangabe der Fundseite) — sie gilt mutmaßlich "
                    "nicht für dieses Bild. Keine Auslieferung.\n"
                    + _bullets(reasons_red + reasons_green)
                )
                fields.license_status = verdict
                return (verdict, round(conf, 2), headline, rec, fields,
                        result_category(verdict, signals))
            headline = "Lizenzpflichtig / geschützt — Warnung"
            rec = (
                "⚠️ Deutliche Hinweise auf ein lizenzpflichtiges oder "
                "urheberrechtlich geschütztes Bild. Keine Vorschau ausliefern "
                "(Platzhalter verwenden).\n" + _bullets(reasons_red)
            )
    elif reds:  # nur schwache RED-Signale
        verdict = Verdict.YELLOW
        conf = max(s.confidence for s in reds)
        headline = "Verdacht — Prüfung empfohlen"
        rec = (
            "Es gibt schwache Warnhinweise, aber keinen eindeutigen Beleg. "
            "Redaktionelle Prüfung empfohlen; im Zweifel keine Auslieferung.\n"
            + _bullets(reasons_red)
        )
    elif strong_greens:
        verdict = Verdict.GREEN
        conf = max(s.confidence for s in strong_greens)
        headline = "Unkritisch — Freigabe möglich"
        rec = (
            "✓ Es liegt ein Positivnachweis für eine freie/unkritische Lizenz "
            "vor und kein Warnsignal. Vorschau kann ausgeliefert werden. "
            "Attribution beachten (siehe Felder).\n" + _bullets(reasons_green)
        )
    elif yellows or greens:
        verdict = Verdict.YELLOW
        conf = 0.4
        headline = "Unklar — Prüfung empfohlen"
        rec = (
            "Es gibt Teilsignale, aber keinen belastbaren Positiv- oder "
            "Negativnachweis. Redaktionelle Prüfung; Default-Deny bis geklärt.\n"
            + _bullets([f"{s.label}: {s.summary}" for s in yellows + greens])
        )
    else:
        verdict = Verdict.YELLOW
        conf = 0.2
        headline = "Kein Signal — Default-Deny"
        rec = (
            "Keiner der Prüfschritte liefert ein belastbares Signal. Leere "
            "Metadaten bedeuten NICHT lizenzfrei. Ohne Positivnachweis keine "
            "automatische Auslieferung (Default-Deny)."
        )

    fields.license_status = verdict
    return (verdict, round(conf, 2), headline, rec, fields,
            result_category(verdict, signals))


def _bullets(items: list[str]) -> str:
    seen: list[str] = []
    for it in items:
        if it not in seen:
            seen.append(it)
    return "\n".join(f"• {it}" for it in seen)
