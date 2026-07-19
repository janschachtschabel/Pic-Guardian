"""Smoke-Tests der Prüf-Pipeline ohne HTTP/Netzwerk.

Erzeugt Testbilder mit Pillow und prüft die aggregierte Ampel. Ausführen:
    ./.venv/Scripts/python -m tests.test_smoke      (im backend/-Verzeichnis)
"""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import image_source  # noqa: E402
from app.pipeline import run_pipeline  # noqa: E402
from app.risk_hub import RiskHub  # noqa: E402


def _jpeg(copyright_text: str | None = None, color=(120, 120, 120)) -> bytes:
    img = Image.new("RGB", (160, 120), color)
    buf = io.BytesIO()
    if copyright_text:
        exif = img.getexif()
        exif[0x8298] = copyright_text  # Copyright
        img.save(buf, format="JPEG", exif=exif)
    else:
        img.save(buf, format="JPEG")
    return buf.getvalue()


def _run(filename: str, data: bytes, allow_external=False, hub=None):
    ctx = image_source.load_from_upload(filename, data)
    return run_pipeline(ctx, allow_external=allow_external, risk_hub=hub)


def main() -> int:
    tmp_hub = RiskHub(Path(tempfile.gettempdir()) / "bildcheck_test_hub.json")
    failures = 0

    def expect(name, actual, want):
        nonlocal failures
        ok = actual == want
        print(f"  [{'OK ' if ok else 'FAIL'}] {name}: verdict={actual} (erwartet {want})")
        if not ok:
            failures += 1

    print("1) Agentur im EXIF-Copyright -> RED")
    r = _run("photo.jpg", _jpeg("© 2024 Getty Images"))
    expect("getty-exif", r.verdict.value, "red")

    print("2) CC-Lizenz im EXIF-Copyright -> GREEN")
    r = _run("photo.jpg", _jpeg("Licensed under CC BY 4.0"))
    expect("cc-exif", r.verdict.value, "green")

    print("3) Sauberes Bild ohne Metadaten -> YELLOW (Default-Deny)")
    r = _run("photo.jpg", _jpeg(None))
    expect("no-signal", r.verdict.value, "yellow")

    print("4) Agentur-Dateinamensmuster MIT Asset-ID (starkes Signal) -> RED")
    # Kalibriert nach 5000er-Batch: eine Agentur-Asset-ID im Dateinamen ist
    # quasi beweisend (conf 0.8) -> hartes RED, nicht nur Verdacht.
    for fn in ("gettyimages-1234567890.jpg", "iStock-528070276.jpg",
               "shutterstock_987654321.jpg", "imago12345678.jpg"):
        r = _run(fn, _jpeg(None))
        sig = next(s for s in r.signals if s.id == "domain_filename")
        expect(f"filename[{fn}]", (r.verdict.value, sig.verdict.value), ("red", "red"))

    print("4b) Generisches Muster ohne ID (schwaches Signal) -> YELLOW")
    r = _run("stock-photo-sunset.jpg", _jpeg(None))
    sig = next(s for s in r.signals if s.id == "domain_filename")
    expect("filename[stock-photo]", (r.verdict.value, sig.verdict.value), ("yellow", "red"))

    print("4c) Kein Fehltreffer bei Produktnamen (RTX4090) -> kein Muster")
    from app.wordlists import match_agency_asset
    expect("no-rtx-fp", match_agency_asset("nvidia-rtx4090-benchmark.jpg"), None)
    hit = match_agency_asset("https://cdn.example.org/img/urn:newsml:dpa.com:20260101:99-123456.jpeg")
    expect("dpa-urn-strong", bool(hit and hit[1]), True)

    print("5) Risikospeicher-Treffer (SHA-1) -> RED")
    import hashlib

    data = _jpeg(None, color=(10, 20, 30))
    tmp_hub.add(sha1=hashlib.sha1(data).hexdigest(), note="Testfall")
    r = _run("x.jpg", data, hub=tmp_hub)
    expect("riskhub-sha1", r.verdict.value, "red")

    # Aggregations-Kombinationsregel direkt (ohne echte Bilder testbar).
    from app.aggregate import aggregate
    from app.schemas import CheckSignal, SignalStatus, Verdict

    def _sig(verdict, conf):
        return CheckSignal(
            id="x", label="X", category="c",
            status=SignalStatus.DONE, verdict=verdict, confidence=conf,
        )

    blank = image_source.load_from_upload("x.jpg", _jpeg(None))

    print("6) Zwei schwache RED-Signale -> RED (Kombination)")
    v, *_ = aggregate([_sig(Verdict.RED, 0.7), _sig(Verdict.RED, 0.6)], blank)
    expect("combine-two-red", v.value, "red")

    print("7) Ein schwaches RED-Signal -> YELLOW")
    v, *_ = aggregate([_sig(Verdict.RED, 0.7)], blank)
    expect("single-weak-red", v.value, "yellow")

    print("8) Starkes RED + starkes GREEN (Widerspruch) -> YELLOW")
    v, *_ = aggregate([_sig(Verdict.RED, 0.9), _sig(Verdict.GREEN, 0.9)], blank)
    expect("conflict", v.value, "yellow")

    # Seiten-Checks (Option 1/2) mit konstruiertem Fundseiten-HTML.
    from app.checks.base import CheckContext
    from app.checks.c08_page_structured import PageStructuredCheck
    from app.checks.c09_page_credit import PageCreditCheck

    def page_ctx(html):
        img = image_source.ImageContext(
            data=b"\xff\xd8\xff", mode="url",
            origin_url="https://x.example/foto.jpg",
            source_page="https://x.example/artikel", page_html=html,
        )
        return CheckContext(image=img, allow_external=False)

    print("9) schema.org acquireLicensePage -> page_structured RED")
    h = '<script type="application/ld+json">{"@type":"ImageObject","acquireLicensePage":"https://gettyimages.de/license/1"}</script>'
    expect("page-acquire", PageStructuredCheck().run(page_ctx(h)).verdict.value, "red")

    print("10) rel=license CC -> page_structured GREEN")
    h = '<a rel="license" href="https://creativecommons.org/licenses/by-sa/4.0/">CC</a>'
    expect("page-ccrel", PageStructuredCheck().run(page_ctx(h)).verdict.value, "green")

    print("11) figcaption Agentur -> page_credit RED")
    h = '<figure><img src="/x/foto.jpg"><figcaption>Foto: Getty Images</figcaption></figure>'
    expect("page-credit-agency", PageCreditCheck().run(page_ctx(h)).verdict.value, "red")

    print("12) PD-Lizenz + Selbstverweis-acquireLicensePage -> page_structured GREEN")
    h = ('<script type="application/ld+json">{"@type":"ImageObject",'
         '"license":"https://x.example/wiki/Help:Public_domain",'
         '"acquireLicensePage":"//x.example/wiki/File:Foto.jpg"}</script>')
    expect("page-pd-selfacquire", PageStructuredCheck().run(page_ctx(h)).verdict.value, "green")

    print("13) acquireLicensePage auf EXTERNE Agentur-Domain -> page_structured RED")
    h = ('<script type="application/ld+json">{"@type":"ImageObject",'
         '"acquireLicensePage":"https://www.gettyimages.de/license/1"}</script>')
    expect("page-ext-acquire", PageStructuredCheck().run(page_ctx(h)).verdict.value, "red")

    # Batch: CSV-Parser + Sammlungs-Traversierung (gemockt).
    from app import batch, edu_sharing
    from app.config import REPOSITORIES

    print("14) CSV-Parser: Header/Repo-Default/Warnung")
    items, warns = batch.parse_csv("node_id;repository\nx1;prod\nx2\nx3;wrong", "staging")
    expect("csv-items", items, [("x1", "prod"), ("x2", "staging"), ("x3", "staging")])
    expect("csv-warn", len(warns), 1)

    print("15) Sammlungs-Traversierung: Rekursion + Dedup + Limit")
    tree = {
        "root": {"subs": ["a"], "refs": [{"originalId": "i1"}, {"originalId": "i2"}]},
        "a": {"subs": [], "refs": [{"originalId": "i2"}, {"originalId": "i3"}]},
    }
    orig_refs, orig_subs = edu_sharing.list_collection_references, edu_sharing.list_subcollections
    edu_sharing.list_collection_references = lambda r, c, a: tree.get(c, {}).get("refs", [])
    edu_sharing.list_subcollections = lambda r, c, a: [{"ref": {"id": s}} for s in tree.get(c, {}).get("subs", [])]
    try:
        ids, trunc = batch.collect_collection_items(REPOSITORIES["prod"], "root", None, 5, 100)
        expect("traverse-dedup", (sorted(ids), trunc), (["i1", "i2", "i3"], False))
        _, trunc2 = batch.collect_collection_items(REPOSITORIES["prod"], "root", None, 5, 2)
        expect("traverse-limit", trunc2, True)
    finally:
        edu_sharing.list_collection_references, edu_sharing.list_subcollections = orig_refs, orig_subs

    # Audit-Fixes als Regression absichern.
    from app.wordlists import contains_agency, find_cc_license
    from app.checks.c02_domain_filename import _host_matches
    from app.net_guard import assert_public_url, BlockedURLError

    print("16) contains_agency: Wortgrenzen (kein Substring-Fehltreffer)")
    expect("agency-no-substr", contains_agency("Sandpapier, Landpartie"), None)
    expect("agency-word", contains_agency("Foto: dpa"), "dpa")

    print("17) Domain-Match: kein Substring-Spoofing")
    expect("host-spoof", _host_matches("pexels.com.evil.ru", ["pexels.com"]), None)
    expect("host-sub", _host_matches("images.pexels.com", ["pexels.com"]), "pexels.com")

    print("18) CC-Label mit Bindestrich + SSRF-Guard")
    expect("cc-label", find_cc_license("CC BY-SA 4.0")[0], "CC BY-SA 4.0")
    for bad in ("http://127.0.0.1/", "http://169.254.169.254/", "file:///etc/passwd"):
        try:
            assert_public_url(bad)
            expect(f"ssrf[{bad}]", "durchgelassen", "blockiert")
        except BlockedURLError:
            expect(f"ssrf[{bad}]", "blockiert", "blockiert")

    # Audit-2-Fixes (Runde 2).
    from app.wordlists import normalize_license_uri
    from app.risk_hub import _hamming_hex

    print("19) normalize_license_uri: Tracking-Wrapper NICHT als CC (kein False-GREEN)")
    expect("norm-wrapper", normalize_license_uri("https://track.x/r?u=https://creativecommons.org/licenses/by/4.0/"), None)
    expect("norm-echt", normalize_license_uri("http://creativecommons.org/licenses/by/4.0/"), "https://creativecommons.org/licenses/by/4.0/")

    print("20) _hamming_hex: nicht-hex kein Crash (RiskHub-Poisoning)")
    expect("hamming-nonhex", _hamming_hex("zzzzzzzzzzzzzzzz", "0000000000000000"), 999)

    print("21) CSV-Template erzeugt keine Phantom-Node")
    tpl_items, _ = batch.parse_csv(batch.csv_template(), "prod")
    expect("csv-tpl-nohdr", [n for n, _ in tpl_items if n.lower() in ("node_id", "nodeid")], [])

    print("22) c08 reihenfolge-unabhängig (Agentur schlägt CC, deterministisch RED)")

    def _pctx(html):
        return CheckContext(image=image_source.ImageContext(
            data=b"\xff\xd8\xff", mode="url", origin_url="https://x/f.jpg",
            source_page="https://x/a", page_html=html), allow_external=False)

    _cc = '<a rel="license" href="https://creativecommons.org/licenses/by/4.0/">CC</a>'
    _gt = '<a rel="license" href="https://gettyimages.de/license/1">Getty</a>'
    v1 = PageStructuredCheck().run(_pctx(_cc + _gt)).verdict.value
    v2 = PageStructuredCheck().run(_pctx(_gt + _cc)).verdict.value
    expect("c08-order", (v1, v2), ("red", "red"))

    print("23) Rangfolge: Repo-Deklaration überstimmt Agentur-Nachweis NICHT")

    def _sigid(cid, verdict, conf):
        return CheckSignal(id=cid, label=cid, category="c",
                           status=SignalStatus.DONE, verdict=verdict, confidence=conf)

    # Agentur-Nachweis (Seite) + freie Repo-Deklaration -> ROT (Deklaration überstimmt)
    v, *_ = aggregate([_sigid("page_credit", Verdict.RED, 0.8),
                       _sigid("declared_license", Verdict.GREEN, 0.7)], blank)
    expect("agentur-vs-deklaration", v.value, "red")
    # Agentur-Nachweis + UNABHÄNGIGER Positivbeleg (Commons) -> echter Widerspruch GELB
    v, *_ = aggregate([_sigid("page_credit", Verdict.RED, 0.8),
                       _sigid("commons_sha1", Verdict.GREEN, 0.9)], blank)
    expect("agentur-vs-commons", v.value, "yellow")

    def _sigdata(cid, verdict, conf, data):
        return CheckSignal(id=cid, label=cid, category="c",
                           status=SignalStatus.DONE, verdict=verdict,
                           confidence=conf, data=data)

    # Agentur-Nachweis + SEITENWEITE freie Lizenz der Fundseite -> ROT
    # (die Seitenlizenz gilt für den Artikeltext, nicht fürs Agenturbild)
    v, *_ = aggregate([_sigid("page_credit", Verdict.RED, 0.8),
                       _sigdata("page_structured", Verdict.GREEN, 0.8,
                                {"license_scope": "page"})], blank)
    expect("agentur-vs-seitenlizenz", v.value, "red")
    # ... aber eine BILDGEBUNDENE Lizenz (ImageObject) bleibt echter Widerspruch
    v, *_ = aggregate([_sigid("page_credit", Verdict.RED, 0.8),
                       _sigdata("page_structured", Verdict.GREEN, 0.8,
                                {"license_scope": "image"})], blank)
    expect("agentur-vs-bildlizenz", v.value, "yellow")

    print("24) page_credit: Agentur-Asset-ID in Bild-URL (ohne Credit-Text) -> RED")
    from app.checks.c09_page_credit import PageCreditCheck
    from app.checks.base import CheckContext as _CC

    def _credit_ctx(html, origin="https://x/foto.jpg"):
        return _CC(image=image_source.ImageContext(
            data=b"\xff\xd8\xff", mode="url", origin_url=origin,
            source_page="https://x/a", source_domain="x", page_html=html),
            allow_external=False)

    # Zielbild trägt Getty-Asset-ID im src, KEIN sichtbarer Bildnachweis-Text
    html_url = '<img src="https://cdn.x/gettyimages-1122334455.jpg">'
    sig = PageCreditCheck().run(_credit_ctx(html_url, "https://cdn.x/gettyimages-1122334455.jpg"))
    expect("c09-url-asset", (sig.verdict.value, round(sig.confidence, 2)), ("red", 0.85))
    # srcset-Variante (anderes Bild der Seite) -> seitenweit, aber weiterhin RED
    html_srcset = '<img src="https://cdn.x/hero.jpg" srcset="https://cdn.x/istockphoto-987654321.jpg 2x">'
    sig = PageCreditCheck().run(_credit_ctx(html_srcset))
    expect("c09-srcset-asset", sig.verdict.value, "red")
    # sauberes Seitenbild ohne Muster/Credit -> NEUTRAL
    sig = PageCreditCheck().run(_credit_ctx('<img src="https://cdn.x/nice-sunset.jpg">'))
    expect("c09-clean", sig.verdict.value, "neutral")
    # <picture><source srcset> mit Agentur-Asset-ID -> RED
    html_src = '<picture><source srcset="https://cdn.x/AdobeStock_40285887.jpg 2x"><img src="https://cdn.x/a.jpg"></picture>'
    sig = PageCreditCheck().run(_credit_ctx(html_src))
    expect("c09-picture-source", sig.verdict.value, "red")
    # CSS background-image url() mit Agentur-Asset-ID -> RED
    html_bg = '<div style="background-image:url(\'https://cdn.x/gettyimages-1122334455.jpg\')"></div>'
    sig = PageCreditCheck().run(_credit_ctx(html_bg))
    expect("c09-bg-image", sig.verdict.value, "red")

    print("25) Presse-/Rundfunk-Domain ohne Positivbeleg -> Hinweis (Default) / Verdacht (streng)")
    from app.checks.c02_domain_filename import DomainFilenameCheck

    def _dom_ctx(domain, origin_host="cdn.example.org"):
        return _CC(image=image_source.ImageContext(
            data=b"\xff\xd8\xff", mode="node", origin_url=f"https://{origin_host}/pic.jpg",
            source_page=f"https://{domain}/artikel", source_domain=domain, page_html=None),
            allow_external=False)

    sig = DomainFilenameCheck().run(_dom_ctx("www.dw.com"))
    expect("news-default-yellow", sig.verdict.value, "yellow")
    # strenger Modus umschalten. SETTINGS ist frozen -> Feld ersetzen; die
    # c02-Modulreferenz patchen (dort per `from ..config import SETTINGS`
    # gebunden — config.SETTINGS zu ersetzen reicht nicht).
    import dataclasses as _dc
    from app.checks import c02_domain_filename as _c02
    _orig_settings = _c02.SETTINGS
    _c02.SETTINGS = _dc.replace(_orig_settings, strict_news_domains=True)
    try:
        sig = DomainFilenameCheck().run(_dom_ctx("www.tagesschau.de"))
        expect("news-strict-red", sig.verdict.value, "red")
    finally:
        _c02.SETTINGS = _orig_settings
    # Nicht-Presse-Domain -> kein News-Signal (neutral)
    sig = DomainFilenameCheck().run(_dom_ctx("serlo.org"))
    expect("non-news-neutral", sig.verdict.value, "neutral")

    print("26) Bildnachweis-Seite: reine Klassifikation (ohne Netz)")
    from app.checks.c12_credit_page import classify_credit_page
    v, _c, _s = classify_credit_page("Alle Bilder: picture alliance / dpa", None)
    expect("creditpage-agency", v.value, "yellow")
    v, _c, _s = classify_credit_page("Bild foto.jpg: picture alliance", "foto.jpg")
    expect("creditpage-agency-named", v.value, "red")
    v, _c, _s = classify_credit_page("Fotos von Unsplash und Pixabay", None)
    expect("creditpage-free", v.value, "yellow")

    print("27) Wayback-Availability-Parser")
    from app.image_source import parse_wayback_availability
    ok = {"archived_snapshots": {"closest": {"available": True,
          "url": "http://web.archive.org/web/20200101/https://x/a", "timestamp": "20200101000000"}}}
    u, ts = parse_wayback_availability(ok)
    expect("wayback-ok", (u.startswith("https://web.archive.org"), ts[:8]), (True, "20200101"))
    expect("wayback-empty", parse_wayback_availability({"archived_snapshots": {}}), (None, None))

    print("28) 4-stufige Ergebnis-Skala (unproblematisch/zu_pruefen/nicht_messbar/problematisch)")
    from app.aggregate import result_category
    # RED -> problematisch
    expect("cat-red", result_category(Verdict.RED, [_sigid("page_credit", Verdict.RED, 0.8)]), "problematisch")
    # GREEN -> unproblematisch
    expect("cat-green", result_category(Verdict.GREEN, [_sigid("commons_sha1", Verdict.GREEN, 0.9)]), "unproblematisch")
    # YELLOW mit rotem Warnsignal -> zu_pruefen
    expect("cat-yellow-warn", result_category(Verdict.YELLOW, [_sigid("domain_filename", Verdict.RED, 0.5)]), "zu_pruefen")
    # YELLOW ohne Warnsignal -> nicht_messbar
    expect("cat-yellow-empty", result_category(Verdict.YELLOW, [_sigid("declared_license", Verdict.YELLOW, 0.3)]), "nicht_messbar")
    # YELLOW mit Urheber-/Rechteangabe ohne entlastende Lizenz -> zu_pruefen
    expect("cat-attr-credit", result_category(
        Verdict.YELLOW, [_sigdata("page_credit", Verdict.YELLOW, 0.5, {"credit_text": "Foto: Max Mustermann"})]),
        "zu_pruefen")
    expect("cat-attr-copyright", result_category(
        Verdict.YELLOW, [_sigdata("declared_license", Verdict.YELLOW, 0.5, {"license_field": "© Alle Rechte vorbehalten"})]),
        "zu_pruefen")
    # „Individuelle Lizenz" (nur Label, keine Rechteangabe) bleibt nicht_messbar
    expect("cat-custom-nichtmessbar", result_category(
        Verdict.YELLOW, [_sigdata("declared_license", Verdict.YELLOW, 0.3, {"license_label": "Individuelle Lizenz"})]),
        "nicht_messbar")
    # Vollständiger Lauf: aggregate liefert die Kategorie als 6. Rückgabewert
    out = aggregate([_sigid("page_credit", Verdict.RED, 0.8),
                     _sigid("declared_license", Verdict.GREEN, 0.7)], blank)
    expect("cat-aggregate-tuple", (len(out), out[5]), (6, "problematisch"))

    print("29) Originalbild-Metadaten (c13): URL-Findung + geteilte Klassifikation")
    from app.checks.c13_origin_metadata import find_origin_url
    from app.checks.c03_embedded_metadata import classify_metadata, extract_metadata
    # exakter Dateiname-Treffer auf der Fundseite -> absolute URL
    _html = '<img src="/x/logo.png"><img src="https://cdn.z/namibia-bild.jpg">'
    expect("origin-exact",
           find_origin_url(_html, "namibia-bild.jpg", "https://www.bpb.de/a"),
           "https://cdn.z/namibia-bild.jpg")
    # kein Treffer, kein og:image -> None
    expect("origin-none", find_origin_url('<img src="/a.png">', "ziel.jpg", "https://x.de"), None)
    # geteilte Klassifikation (c03 == c13): Agentur im Credit -> RED
    v, *_ = classify_metadata({"credit": "Foto: picture alliance"})
    expect("classify-agency", v.value, "red")
    # leere Metadaten -> NEUTRAL (leer != frei)
    expect("classify-empty", classify_metadata({})[0].value, "neutral")
    # extract_metadata auf einem Bild ohne Metadaten -> leeres Dict
    expect("extract-empty", extract_metadata(None, b"\xff\xd8\xff") == {}, True)

    print(f"\nErgebnis: {'ALLE OK' if failures == 0 else str(failures) + ' FEHLGESCHLAGEN'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
