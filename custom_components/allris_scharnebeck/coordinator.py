"""DataUpdateCoordinator für die ALLRIS Sitzungskalender Scharnebeck Integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .allris_client import AllrisError, Meeting, build_match_fn, fetch_meetings
from .const import (
    CONF_EVENT_DURATION,
    CONF_MONTHS_AHEAD,
    CONF_PLACES,
    CONF_UPDATE_INTERVAL_HOURS,
    DEFAULT_EVENT_DURATION,
    DEFAULT_MONTHS_AHEAD,
    DEFAULT_UPDATE_INTERVAL_HOURS,
)

_LOGGER = logging.getLogger(__name__)


class AllrisDataUpdateCoordinator(DataUpdateCoordinator[list[Meeting]]):
    """Holt periodisch die Sitzungsliste von ALLRIS."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        interval_hours = entry.options.get(
            CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{entry.title} (ALLRIS Scharnebeck)",
            update_interval=timedelta(hours=interval_hours),
        )

    async def _async_update_data(self) -> list[Meeting]:
        options = self.entry.options
        places: list[str] = options.get(CONF_PLACES, [])
        months_ahead: int = options.get(CONF_MONTHS_AHEAD, DEFAULT_MONTHS_AHEAD)
        duration: int = options.get(CONF_EVENT_DURATION, DEFAULT_EVENT_DURATION)
        match_fn = build_match_fn(places)

        stats: dict = {}
        try:
            meetings = await self.hass.async_add_executor_job(
                fetch_meetings, months_ahead, match_fn, duration, stats
            )
        except AllrisError as err:
            raise UpdateFailed(f"ALLRIS-Abfrage fehlgeschlagen: {err}") from err

        _LOGGER.debug(
            "%s: %d Sitzung(en) gefunden (von insgesamt %d im geprüften Zeitraum)",
            self.entry.title,
            len(meetings),
            stats.get("total", 0),
        )
        return meetings
