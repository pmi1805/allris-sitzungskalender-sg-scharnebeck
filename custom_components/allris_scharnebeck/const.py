"""Constants for the ALLRIS Sitzungskalender Scharnebeck integration."""
from __future__ import annotations

DOMAIN = "allris_scharnebeck"

BASE_URL = "https://www.scharnebeck.sitzung-online.de/public/si010"
TIMEZONE = "Europe/Berlin"
HTTP_TIMEOUT = 30
USER_AGENT = "HomeAssistant-ALLRIS-Scharnebeck/1.0 (+https://github.com/YOUR_GITHUB_USER/ha-allris-scharnebeck)"

# Config / options keys
CONF_PLACES = "places"
CONF_MONTHS_AHEAD = "months_ahead"
CONF_EVENT_DURATION = "event_duration_minutes"
CONF_UPDATE_INTERVAL_HOURS = "update_interval_hours"

DEFAULT_MONTHS_AHEAD = 12
DEFAULT_EVENT_DURATION = 180
DEFAULT_UPDATE_INTERVAL_HOURS = 24

# Körperschaften ("Gemeinden" + "Samtgemeinde") wie im ALLRIS-Körperschaftsfilter
# der Samtgemeinde Scharnebeck. Jeder Eintrag definiert, wie ein Sitzungstitel
# dieser Körperschaft zugeordnet wird:
#   - include: mindestens eines dieser (kleingeschriebenen) Stichworte muss im
#     (kleingeschriebenen) Sitzungstitel vorkommen
#   - exclude: kommt eines dieser Stichworte vor, gilt der Titel NICHT als
#     Treffer für diese Körperschaft (wichtig für "Scharnebeck", da sowohl die
#     Samtgemeinde als auch die gleichnamige Mitgliedsgemeinde "Scharnebeck"
#     heißen)
#
# Reihenfolge entspricht der Körperschafts-Auswahlliste auf der ALLRIS-Seite.
PLACES: dict[str, dict] = {
    "samtgemeinde": {
        "label": "Samtgemeinde Scharnebeck (Rat & Ausschüsse)",
        "include": ["samtgemeinde scharnebeck"],
        "exclude": [],
    },
    "artlenburg": {
        "label": "Flecken Artlenburg",
        "include": ["artlenburg"],
        "exclude": [],
    },
    "brietlingen": {
        "label": "Gemeinde Brietlingen",
        "include": ["brietlingen"],
        "exclude": [],
    },
    "echem": {
        "label": "Gemeinde Echem",
        "include": ["echem"],
        "exclude": [],
    },
    "hittbergen": {
        "label": "Gemeinde Hittbergen",
        "include": ["hittbergen"],
        "exclude": [],
    },
    "hohnstorf": {
        "label": "Gemeinde Hohnstorf (Elbe)",
        "include": ["hohnstorf"],
        "exclude": [],
    },
    "luedersburg": {
        "label": "Gemeinde Lüdersburg",
        "include": ["lüdersburg", "luedersburg"],
        "exclude": [],
    },
    "rullstorf": {
        "label": "Gemeinde Rullstorf",
        "include": ["rullstorf"],
        "exclude": [],
    },
    "scharnebeck": {
        "label": "Gemeinde Scharnebeck",
        "include": ["scharnebeck"],
        # Verhindert Verwechslung mit der übergeordneten "Samtgemeinde Scharnebeck".
        "exclude": ["samtgemeinde scharnebeck"],
    },
}
