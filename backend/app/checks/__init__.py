"""Check-Registry — Reihenfolge = Anzeigereihenfolge der Prüfschritte.

Gruppiert nach Ebene (Vorlage): Repository → Seite (1–4) → Datei (5–7) →
Abgleich (8–9). Neue Prüfschritte hier ergänzen; die Pipeline iteriert generisch.
"""

from __future__ import annotations

from .base import BaseCheck, CheckContext
from .c01_declared_license import DeclaredLicenseCheck
from .c02_domain_filename import DomainFilenameCheck
from .c03_embedded_metadata import EmbeddedMetadataCheck
from .c04_c2pa import C2paCheck
from .c05_perceptual_hash import PerceptualHashCheck
from .c06_watermark import WatermarkCheck
from .c07_commons import CommonsCheck
from .c08_page_structured import PageStructuredCheck
from .c09_page_credit import PageCreditCheck
from .c10_site_policy import SitePolicyCheck
from .c11_openverse import OpenverseCheck
from .c12_credit_page import CreditPageCheck
from .c13_origin_metadata import OriginMetadataCheck

ALL_CHECKS: list[BaseCheck] = [
    # Repository
    DeclaredLicenseCheck(),      # deklarierte edu-sharing-Lizenz
    # Seite (Fundseiten-HTML)
    PageStructuredCheck(),       # 1  schema.org / ccREL / Dublin Core
    PageCreditCheck(),           # 2  sichtbarer Bildnachweis im DOM
    CreditPageCheck(),           # 2b zentrale Bildnachweis-Seite der Domain
    DomainFilenameCheck(),       # 3  Domain-/Dateinamen-Heuristik
    SitePolicyCheck(),           # 4  robots.txt / Meta / TDM
    # Datei
    EmbeddedMetadataCheck(),     # 5  EXIF / IPTC / XMP / PLUS (WLO-Vorschau)
    OriginMetadataCheck(),       # 5b EXIF/IPTC/XMP des Originalbilds der Fundseite (opt-in)
    C2paCheck(),                 # 6  C2PA / Content Credentials (optional)
    WatermarkCheck(),            # 7  Wasserzeichen / OCR (optional)
    # Abgleich
    PerceptualHashCheck(),       # 8  pHash + interner Risikospeicher
    CommonsCheck(),              # 9a Wikimedia Commons SHA-1 (extern)
    OpenverseCheck(),            # 9b Openverse CC-Recherche (extern)
]

__all__ = ["ALL_CHECKS", "BaseCheck", "CheckContext"]
