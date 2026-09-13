"""Config flow für die ALLRIS Sitzungskalender Scharnebeck Integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_EVENT_DURATION,
    CONF_MONTHS_AHEAD,
    CONF_PLACES,
    CONF_UPDATE_INTERVAL_HOURS,
    DEFAULT_EVENT_DURATION,
    DEFAULT_MONTHS_AHEAD,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    PLACES,
)


def _places_selector(default: list[str]) -> tuple[vol.Marker, selector.SelectSelector]:
    """Baut den Multi-Select-Schlüssel + Selector für die Körperschaften-Auswahl."""
    schema = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value=key, label=value["label"])
                for key, value in PLACES.items()
            ],
            multiple=True,
            mode=selector.SelectSelectorMode.LIST,
        )
    )
    return vol.Required(CONF_PLACES, default=default), schema


def _options_schema(defaults: dict[str, Any]) -> vol.Schema:
    places_key, places_selector = _places_selector(defaults.get(CONF_PLACES, []))
    return vol.Schema(
        {
            places_key: places_selector,
            vol.Optional(
                CONF_MONTHS_AHEAD,
                default=defaults.get(CONF_MONTHS_AHEAD, DEFAULT_MONTHS_AHEAD),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
            vol.Optional(
                CONF_EVENT_DURATION,
                default=defaults.get(CONF_EVENT_DURATION, DEFAULT_EVENT_DURATION),
            ): vol.All(vol.Coerce(int), vol.Range(min=15, max=600)),
            vol.Optional(
                CONF_UPDATE_INTERVAL_HOURS,
                default=defaults.get(
                    CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
        }
    )


def _build_title(place_ids: list[str]) -> str:
    # Kurzform ohne den langen Klammerzusatz der Samtgemeinde-Option.
    short = [
        "Samtgemeinde" if p == "samtgemeinde" else PLACES[p]["label"].replace("Gemeinde ", "")
        for p in place_ids
        if p in PLACES
    ]
    return "ALLRIS Sitzungen: " + ", ".join(short) if short else "ALLRIS Sitzungen"


class AllrisConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config Flow: Auswahl der Körperschaften (Gemeinden/Samtgemeinde) + Parameter."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            places = user_input.get(CONF_PLACES) or []
            if not places:
                errors["base"] = "no_places_selected"
            else:
                unique_id = "+".join(sorted(places))
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=_build_title(places),
                    data={},
                    options={
                        CONF_PLACES: places,
                        CONF_MONTHS_AHEAD: user_input[CONF_MONTHS_AHEAD],
                        CONF_EVENT_DURATION: user_input[CONF_EVENT_DURATION],
                        CONF_UPDATE_INTERVAL_HOURS: user_input[CONF_UPDATE_INTERVAL_HOURS],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_options_schema({}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> AllrisOptionsFlow:
        return AllrisOptionsFlow(config_entry)


class AllrisOptionsFlow(config_entries.OptionsFlow):
    """Erlaubt das nachträgliche Ändern der ausgewählten Körperschaften/Parameter."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        current = dict(self.config_entry.options)

        if user_input is not None:
            places = user_input.get(CONF_PLACES) or []
            if not places:
                errors["base"] = "no_places_selected"
            else:
                return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(current),
            errors=errors,
        )
