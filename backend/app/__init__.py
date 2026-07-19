"""Bild-Lizenz-Check — FastAPI-Prüfdienst zur Erkennung problematischer
Bildlizenzen / Urheberrechtsprobleme.

Der Dienst ist modular aufgebaut: jeder Prüfschritt (``checks/``) ist ein
eigenständiges Plugin mit einheitlichem Ergebnis-Contract, sodass die
Prüf-Pipeline später als eigenständiger Service nachnutzbar ist.
"""

__version__ = "0.1.0"
