"""
ALLRIS Scharnebeck client: liest den öffentlichen Sitzungskalender der
Samtgemeinde Scharnebeck (https://www.scharnebeck.sitzung-online.de/public/si010)
und liefert die gefundenen Sitzungen als Meeting-Objekte zurück.

Reine Python-Standardbibliothek, keine externen Abhängigkeiten. Alle
Netzwerkzugriffe sind synchron (urllib) und werden vom Aufrufer (siehe
coordinator.py) über hass.async_add_executor_job in einem Worker-Thread
ausgeführt, damit der HA-Event-Loop nicht blockiert.

Navigationsstrategie: Direkte Sprünge über die im Kalender-Dropdown
vorhandenen Wicket-AJAX-Callbacks (calNav-years-*-yearlink,
calNav-months-*-monthlink), verankert am echten aktuellen Datum. Siehe
README des Repositories für Hintergrund zu dieser Entscheidung (relative
"nächster Monat"-Klicks haben sich in der Praxis als fehleranfällig
erwiesen).
"""
from __future__ import annotations

import html
import http.cookiejar
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from .const import BASE_URL, HTTP_TIMEOUT, TIMEZONE, USER_AGENT

MatchFn = Callable[[str], bool]


class AllrisError(Exception):
    """Wird bei einem Netzwerk- oder Navigationsfehler gegen ALLRIS geworfen."""


GERMAN_MONTHS = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "maerz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}

# Reihenfolge exakt wie im ALLRIS-Monats-Dropdown (Index 0 = Januar).
MONTH_NAMES_ORDERED = [
    "januar",
    "februar",
    "märz",
    "april",
    "mai",
    "juni",
    "juli",
    "august",
    "september",
    "oktober",
    "november",
    "dezember",
]


def month_add(year: int, month: int, delta: int) -> tuple[int, int]:
    """Addiert `delta` Monate zu (year, month), mit korrektem Jahresübertrag."""
    idx = (year * 12 + (month - 1)) + delta
    return idx // 12, idx % 12 + 1


@dataclass(frozen=True)
class Meeting:
    meeting_id: str
    start: datetime
    end: datetime
    title: str
    location: str
    url: Optional[str] = None


class CalendarTableParser(HTMLParser):
    """Minimaler Parser für die ALLRIS-Kalendertabelle."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_row = False
        self.row_classes = ""
        self.current_cell_class = ""
        self.cell_text: list[str] = []
        self.row: dict = {}
        self.rows: list[dict] = []
        self.current_anchor_id: Optional[str] = None
        self.current_anchor_href: Optional[str] = None
        self.anchor_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "tr":
            self.in_row = True
            self.row_classes = attrs_d.get("class", "")
            self.row = {}
        elif self.in_row and tag == "td":
            self.current_cell_class = attrs_d.get("class", "")
            self.cell_text = []
        elif self.in_row and tag == "a":
            anchor_id = attrs_d.get("id", "")
            if anchor_id.startswith("si_"):
                self.current_anchor_id = anchor_id
                self.current_anchor_href = attrs_d.get("href")
                self.anchor_text = []

    def handle_data(self, data):
        if self.in_row and self.current_cell_class:
            self.cell_text.append(data)
        if self.in_row and self.current_anchor_id:
            self.anchor_text.append(data)

    def handle_endtag(self, tag):
        if not self.in_row:
            return

        if tag == "a" and self.current_anchor_id:
            self.row["meeting_id"] = self.current_anchor_id.removeprefix("si_")
            self.row["title"] = " ".join("".join(self.anchor_text).split())
            self.row["href"] = self.current_anchor_href
            self.current_anchor_id = None
            self.current_anchor_href = None
            self.anchor_text = []

        elif tag == "td" and self.current_cell_class:
            text = " ".join("".join(self.cell_text).split())
            classes = set(self.current_cell_class.split())
            if "nowrapContent" in classes:
                m = re.search(r"\b(\d{1,2})\b", text)
                if m:
                    self.row["day"] = int(m.group(1))
            elif "time" in classes:
                self.row["time"] = text
            elif "raum" in classes:
                self.row["location"] = text

            self.current_cell_class = ""
            self.cell_text = []

        elif tag == "tr":
            if self.row.get("meeting_id") and self.row.get("title"):
                self.row["row_classes"] = self.row_classes
                self.rows.append(dict(self.row))
            self.in_row = False
            self.row_classes = ""
            self.row = {}


class WicketClient:
    def __init__(self, base_url: str, timeout: int = HTTP_TIMEOUT):
        self.base_url = base_url
        self.timeout = timeout
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )

    def _request(self, url: str, ajax: bool = False) -> str:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
            "Referer": self.base_url,
        }
        if ajax:
            headers.update(
                {
                    "X-Requested-With": "XMLHttpRequest",
                    "Wicket-Ajax": "true",
                    "Wicket-Ajax-BaseURL": "si010",
                    "Accept": "application/xml, text/xml, */*; q=0.01",
                }
            )
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            raise AllrisError(f"Netzwerkfehler beim Zugriff auf ALLRIS: {exc}") from exc

    def get_initial_page(self) -> str:
        return self._request(self.base_url, ajax=False)

    def ajax_get(self, callback_url: str) -> str:
        absolute = urllib.parse.urljoin(self.base_url, html.unescape(callback_url))
        return self._request(absolute, ajax=True)


def wicket_callbacks(text: str) -> list[tuple[str, str]]:
    """Liefert [(url, component_id), ...] aus Wicket.Ajax.ajax({...})-Aufrufen."""
    pattern = re.compile(
        r'Wicket\.Ajax\.ajax\(\{[^{}]*?"u"\s*:\s*"([^"]+)"[^{}]*?"c"\s*:\s*"([^"]+)"[^{}]*?\}\)',
        re.S,
    )
    return [(html.unescape(u), c) for u, c in pattern.findall(text)]


def find_callback(text: str, contains: str) -> Optional[str]:
    for url, _component in wicket_callbacks(text):
        if contains in url:
            return url
    return None


def load_calendar_component(client: WicketClient, initial_html: str) -> str:
    """
    Die erste ALLRIS-Seite enthält nur 'Loading...'. Wir probieren die auf der
    Seite registrierten AJAX-Callbacks, bis die Kalender-Tabelle zurückkommt.
    Welcher Monat dabei zuerst angezeigt wird, ist irrelevant — der Aufrufer
    navigiert danach ohnehin gezielt zum gewünschten Zielmonat weiter.
    """
    if 'class="calenderView' in initial_html:
        return initial_html

    callbacks = wicket_callbacks(initial_html)
    preferred = [
        (u, c)
        for u, c in callbacks
        if "calNav-" not in u and "monthlink" not in u and "yearlink" not in u
    ]
    candidates = preferred + [x for x in callbacks if x not in preferred]

    errors: list[str] = []
    for url, _component in candidates:
        try:
            response = client.ajax_get(url)
        except AllrisError as exc:
            errors.append(str(exc))
            continue
        if 'class="calenderView' in response:
            return response

    loose_urls = re.findall(r'["\'](\./si010\?[^"\']+)["\']', initial_html)
    for url in loose_urls:
        if "calNav-" in url:
            continue
        try:
            response = client.ajax_get(url)
        except AllrisError as exc:
            errors.append(str(exc))
            continue
        if 'class="calenderView' in response:
            return response

    detail = "\n".join(errors[-5:])
    raise AllrisError(
        "Kalender-AJAX-Callback konnte nicht automatisch ermittelt werden."
        + (f" Letzte Fehler: {detail}" if detail else "")
    )


def extract_month_year(text: str) -> tuple[int, int]:
    m_month = re.search(
        r'id="selMonth".*?<span[^>]*>\s*([^<]+?)\s*</span>', text, re.I | re.S
    )
    m_year = re.search(
        r'id="selYear".*?<span[^>]*>\s*(\d{4})\s*</span>', text, re.I | re.S
    )
    if m_month and m_year:
        month_name = html.unescape(m_month.group(1)).strip().lower()
        if month_name in GERMAN_MONTHS:
            return GERMAN_MONTHS[month_name], int(m_year.group(1))

    tooltips = re.findall(
        r'data-simpletooltip-text="[^"]*?(\d{2})\.(\d{2})\.(\d{4})', text, re.I
    )
    if tooltips:
        _day, month, year = tooltips[0]
        return int(month), int(year)

    raise AllrisError("Monat/Jahr konnten aus der ALLRIS-Antwort nicht ermittelt werden.")


def parse_nav_links(*texts: str) -> tuple[dict[str, str], dict[int, str]]:
    """
    Liefert (month_links, year_links) aus dem Kalendernavigations-Dropdown:
      month_links: {monatsname_lowercase: callback_url}
      year_links:  {jahr: callback_url}

    Mehrere Texte können übergeben werden (aktuellste zuerst); nicht jede
    AJAX-Antwort enthält das Navigations-Widget neu gerendert (z. B. die
    allererste Kalender-Antwort nach dem Laden enthält oft nur die Tabelle).
    Ergebnisse aus früher übergebenen Texten haben Vorrang.
    """
    month_links: dict[str, str] = {}
    year_links: dict[int, str] = {}
    for text in texts:
        id_to_url = {component_id: url for url, component_id in wicket_callbacks(text)}
        for m in re.finditer(
            r'<a href="#" id="([^"]+)"[^>]*>\s*<span[^>]*>([^<]+)</span>', text
        ):
            anchor_id, label = m.group(1), html.unescape(m.group(2)).strip()
            url = id_to_url.get(anchor_id)
            if not url:
                continue
            if "monthlink" in url:
                month_name = label.lower()
                if month_name in GERMAN_MONTHS:
                    month_links.setdefault(month_name, url)
            elif "yearlink" in url:
                if label.isdigit():
                    year_links.setdefault(int(label), url)
    return month_links, year_links


def parse_meetings(
    text: str,
    month: int,
    year: int,
    duration_minutes: int,
    match_fn: MatchFn,
    tzinfo: ZoneInfo,
    stats: Optional[dict] = None,
) -> list[Meeting]:
    meetings: list[Meeting] = []
    current_day: Optional[int] = None

    row_pattern = re.compile(r"<tr\b[^>]*>.*?</tr>", re.I | re.S)
    for row_html in row_pattern.findall(text):
        row_parser = CalendarTableParser()
        row_parser.feed(row_html)
        if not row_parser.rows:
            day_m = re.search(r'class="dom"[^>]*>\s*(\d{1,2})\s*<', row_html, re.I)
            if day_m:
                current_day = int(day_m.group(1))
            continue

        row = row_parser.rows[0]
        day_m = re.search(r'class="dom"[^>]*>\s*(\d{1,2})\s*<', row_html, re.I)
        if day_m:
            current_day = int(day_m.group(1))

        if current_day is None:
            continue

        title = row.get("title", "").strip()
        if stats is not None and title:
            stats["total"] = stats.get("total", 0) + 1
            sample = stats.setdefault("sample_titles", [])
            if len(sample) < 25 and title not in sample:
                sample.append(title)

        if not match_fn(title):
            continue

        time_text = row.get("time", "").strip()
        tm = re.fullmatch(r"(\d{1,2}):(\d{2})", time_text)
        if not tm:
            continue

        hour, minute = map(int, tm.groups())
        start = datetime(year, month, current_day, hour, minute, tzinfo=tzinfo)
        end = start + timedelta(minutes=duration_minutes)

        href = row.get("href")
        absolute_url = None
        if href:
            absolute_url = urllib.parse.urljoin(BASE_URL, html.unescape(href))

        meetings.append(
            Meeting(
                meeting_id=row["meeting_id"],
                start=start,
                end=end,
                title=title,
                location=row.get("location", "").strip(),
                url=absolute_url,
            )
        )
    return meetings


def fetch_meetings(
    months_ahead: int,
    match_fn: MatchFn,
    duration_minutes: int,
    stats: Optional[dict] = None,
) -> list[Meeting]:
    """
    Liest den ALLRIS-Kalender ab dem echten aktuellen Monat für
    `months_ahead` weitere Monate (also insgesamt months_ahead + 1 Monate)
    und liefert alle Sitzungen, für die `match_fn(titel)` True ergibt.

    Wirft AllrisError bei Netzwerk- oder Navigationsfehlern.
    """
    tzinfo = ZoneInfo(TIMEZONE)
    client = WicketClient(BASE_URL)
    initial = client.get_initial_page()
    current_response = load_calendar_component(client, initial)

    now = datetime.now(tzinfo)
    target_year, target_month = now.year, now.month

    all_meetings: dict[str, Meeting] = {}
    last_year: Optional[int] = None

    for idx in range(months_ahead + 1):
        month_links, year_links = parse_nav_links(current_response, initial)

        if target_year != last_year:
            year_url = year_links.get(target_year)
            if not year_url:
                raise AllrisError(
                    f"Kein Jahres-Link für {target_year} in der ALLRIS-Navigation "
                    f"gefunden (verfügbare Jahre: {sorted(year_links)})."
                )
            current_response = client.ajax_get(year_url)
            last_year = target_year
            month_links, _ = parse_nav_links(current_response, initial)

        month_name = MONTH_NAMES_ORDERED[target_month - 1]
        month_url = month_links.get(month_name)
        if not month_url:
            raise AllrisError(
                f"Kein Monats-Link für '{month_name}' {target_year} in der "
                f"ALLRIS-Navigation gefunden (verfügbare Monate: {sorted(month_links)})."
            )
        current_response = client.ajax_get(month_url)

        try:
            actual_month, actual_year = extract_month_year(current_response)
        except AllrisError:
            actual_month, actual_year = target_month, target_year
        if (actual_month, actual_year) != (target_month, target_year):
            raise AllrisError(
                f"Navigationsfehler: erwartet {target_month:02d}/{target_year}, "
                f"aber Antwort zeigt {actual_month:02d}/{actual_year}."
            )

        for meeting in parse_meetings(
            current_response,
            target_month,
            target_year,
            duration_minutes,
            match_fn,
            tzinfo,
            stats=stats,
        ):
            all_meetings[meeting.meeting_id] = meeting

        if idx >= months_ahead:
            break

        target_year, target_month = month_add(target_year, target_month, 1)
        time.sleep(0.25)

    return sorted(all_meetings.values(), key=lambda m: (m.start, m.meeting_id))


def build_match_fn(place_ids: list[str]) -> MatchFn:
    """Baut aus einer Liste ausgewählter Körperschafts-IDs (siehe const.PLACES)
    eine Funktion, die für einen Sitzungstitel prüft, ob er zu mindestens
    einer der ausgewählten Körperschaften gehört."""
    from .const import PLACES  # lokal importiert, um Zirkularität zu vermeiden

    selected = [PLACES[p] for p in place_ids if p in PLACES]

    def match(title: str) -> bool:
        title_l = title.lower()
        for place in selected:
            if any(inc in title_l for inc in place["include"]) and not any(
                exc in title_l for exc in place["exclude"]
            ):
                return True
        return False

    return match
