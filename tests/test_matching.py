"""
Offline-Tests für die Körperschafts-Zuordnung (build_match_fn) und das
HTML-Parsing (parse_meetings). Benötigt keine Netzwerkverbindung und keine
installierte Home-Assistant-Umgebung, da allris_client.py bewusst frei von
Home-Assistant-Importen gehalten ist.

Ausführen mit:  python3 -m pytest tests/  (oder einfach: python3 tests/test_matching.py)
"""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

# custom_components/allris_scharnebeck/__init__.py imports `homeassistant`,
# which is not (and should not need to be) installed just to run these pure
# offline parsing/matching tests. We therefore register a lightweight stub
# package in sys.modules pointing at that directory *without* executing its
# real __init__.py, then import const.py / allris_client.py as its
# submodules in the normal way. This keeps `python3 -m pytest tests/`
# runnable with only the Python standard library.
_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "allris_scharnebeck"
)

_stub_pkg = types.ModuleType("allris_scharnebeck")
_stub_pkg.__path__ = [str(_COMPONENT_DIR)]
sys.modules.setdefault("allris_scharnebeck", _stub_pkg)


def _load_submodule(name: str):
    full_name = f"allris_scharnebeck.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(
        full_name, _COMPONENT_DIR / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


_const = _load_submodule("const")
_allris_client = _load_submodule("allris_client")

build_match_fn = _allris_client.build_match_fn
parse_meetings = _allris_client.parse_meetings
PLACES = _const.PLACES

TZ = ZoneInfo("Europe/Berlin")

TITLE_TO_PLACE = {
    "Sitzung Nr. 18 des Rates der Gemeinde Rullstorf": "rullstorf",
    "Sitzung des Ausschusses für Umwelt, Bau, Straßen, Wege und Infrastruktur Brietlingen": "brietlingen",
    "Sitzung des Bau-, Umwelt- und Wegeausschusses der Gemeinde Scharnebeck": "scharnebeck",
    "Sitzung des Rates der Samtgemeinde Scharnebeck": "samtgemeinde",
    "Sitzung des Ausschusses für Nachhaltigkeit, Bauen und Umwelt der Samtgemeinde Scharnebeck": "samtgemeinde",
    "Sitzung des Rates der Gemeinde Echem": "echem",
    "konstiuierede Sitzung des Rates der Gemeinde Hittbergen": "hittbergen",
    "Sitzung des Rates der Gemeinde Hohnstorf (Elbe)": "hohnstorf",
    "Sitzung des Rates der Gemeinde Lüdersburg": "luedersburg",
    "Rat des Flecken Artlenburg": "artlenburg",
}


class TestPlaceMatching(unittest.TestCase):
    def test_each_title_matches_only_its_own_place(self) -> None:
        all_ids = list(PLACES.keys())
        for title, expected in TITLE_TO_PLACE.items():
            with self.subTest(title=title):
                self.assertTrue(build_match_fn([expected])(title))
                for other in all_ids:
                    if other == expected:
                        continue
                    self.assertFalse(
                        build_match_fn([other])(title),
                        f"'{title}' sollte NICHT auf '{other}' matchen",
                    )

    def test_scharnebeck_vs_samtgemeinde_no_crosstalk(self) -> None:
        samtgemeinde_titles = [
            "Sitzung des Rates der Samtgemeinde Scharnebeck",
            "Konstituierende Sitzung des Rates der Samtgemeinde Scharnebeck",
        ]
        gemeinde_scharnebeck_titles = [
            "Sitzung des Rates der Gemeinde Scharnebeck",
            "Bau-, Umwelt- und Wegeausschuss Scharnebeck",
        ]
        match_samtgemeinde = build_match_fn(["samtgemeinde"])
        match_scharnebeck = build_match_fn(["scharnebeck"])

        for title in samtgemeinde_titles:
            self.assertTrue(match_samtgemeinde(title))
            self.assertFalse(match_scharnebeck(title))

        for title in gemeinde_scharnebeck_titles:
            self.assertTrue(match_scharnebeck(title))
            self.assertFalse(match_samtgemeinde(title))

    def test_combined_selection(self) -> None:
        combo = build_match_fn(["samtgemeinde", "brietlingen", "echem"])
        self.assertTrue(combo("Sitzung des Rates der Samtgemeinde Scharnebeck"))
        self.assertTrue(combo("Sitzung des Rates der Gemeinde Echem"))
        self.assertTrue(
            combo(
                "Sitzung des Ausschusses für Umwelt, Bau, Straßen, Wege und "
                "Infrastruktur Brietlingen"
            )
        )
        self.assertFalse(combo("Sitzung des Rates der Gemeinde Scharnebeck"))
        self.assertFalse(combo("Sitzung Nr. 18 des Rates der Gemeinde Rullstorf"))


class TestParseMeetings(unittest.TestCase):
    """Regressionstest gegen eine echte, anonymisiert unveränderte ALLRIS-
    AJAX-Antwort (Kalendertabelle September 2026)."""

    SAMPLE_XML = """
    <table id="idcd" class="calenderView hoverRow stickyHeader">
    <tbody>
    <tr class="tue odd">
    <td class="nowrapContent"><span class="dow">Di.</span><span class="dom">08</span></td>
    <td class="time"><div>19:00</div></td>
    <td class="textCol" data-bordercolor="transparent"><div>
    <a href="./to010?SILFDNR=1001491&amp;refresh=false" id="si_1001491"
       data-simpletooltip-text=" am Di., 08.09.2026 um 19:00 Uhr."
       class="js-simple-tooltip tooltipProvider">Sitzung des Ausschusses für
       Umwelt, Bau, Straßen, Wege und Infrastruktur Brietlingen</a>
    </div></td>
    <td class="raum"><div>Schoolhus</div></td>
    </tr>
    </tbody>
    </table>
    """

    def test_finds_brietlingen_meeting(self) -> None:
        match_fn = build_match_fn(["brietlingen"])
        meetings = parse_meetings(self.SAMPLE_XML, 9, 2026, 180, match_fn, TZ)
        self.assertEqual(len(meetings), 1)
        meeting = meetings[0]
        self.assertEqual(meeting.meeting_id, "1001491")
        self.assertEqual(meeting.start.hour, 19)
        self.assertEqual(meeting.location, "Schoolhus")

    def test_other_place_finds_nothing(self) -> None:
        match_fn = build_match_fn(["echem"])
        meetings = parse_meetings(self.SAMPLE_XML, 9, 2026, 180, match_fn, TZ)
        self.assertEqual(meetings, [])


if __name__ == "__main__":
    unittest.main()
