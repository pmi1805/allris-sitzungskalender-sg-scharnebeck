"""Calendar platform für die ALLRIS Sitzungskalender Scharnebeck Integration."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from .allris_client import Meeting
from .const import DOMAIN


def _to_calendar_event(meeting: Meeting) -> CalendarEvent:
    description = "Quelle: ALLRIS Samtgemeinde Scharnebeck"
    if meeting.url:
        description += f"\n{meeting.url}"
    return CalendarEvent(
        start=meeting.start,
        end=meeting.end,
        summary=meeting.title,
        description=description,
        location=meeting.location or None,
        uid=f"allris-scharnebeck-{meeting.meeting_id}@scharnebeck",
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AllrisCalendarEntity(coordinator, entry)])


class AllrisCalendarEntity(CoordinatorEntity, CalendarEntity):
    """Kalender-Entity, die die Sitzungen der ausgewählten Körperschaften bündelt."""

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_name = entry.title
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="ALLRIS / Samtgemeinde Scharnebeck (inoffiziell)",
            model="Sitzungskalender",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def event(self) -> CalendarEvent | None:
        meetings: list[Meeting] = self.coordinator.data or []
        now = dt_util.now()
        upcoming = sorted(
            (m for m in meetings if m.end > now), key=lambda m: m.start
        )
        return _to_calendar_event(upcoming[0]) if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        meetings: list[Meeting] = self.coordinator.data or []
        return [
            _to_calendar_event(m)
            for m in meetings
            if m.start < end_date and m.end > start_date
        ]
