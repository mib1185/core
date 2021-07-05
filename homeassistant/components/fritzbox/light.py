"""Support for Fritzbox light bulbs."""
from __future__ import annotations

from typing import Any

from pyfritzhome.fritzhomedevice import FritzhomeDevice

from homeassistant.components.binary_sensor import DEVICE_CLASS_LIGHT
from homeassistant.components.fritzbox.model import EntityInfo
from homeassistant.components.light import (
    ATTR_COLOR_TEMP,
    ATTR_HS_COLOR,
    COLOR_MODE_COLOR_TEMP,
    COLOR_MODE_HS,
    COLOR_MODE_ONOFF,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    ATTR_NAME,
    ATTR_UNIT_OF_MEASUREMENT,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.color import (
    color_temperature_kelvin_to_mired,
    color_temperature_mired_to_kelvin,
)

from . import FritzBoxEntity
from .const import CONF_COORDINATOR, DOMAIN as FRITZBOX_DOMAIN
from .model import HsColor


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the FRITZ!SmartHome light platform from ConfigEntry."""
    entities: list[FritzboxLight] = []
    coordinator = hass.data[FRITZBOX_DOMAIN][entry.entry_id][CONF_COORDINATOR]

    for ain, device in coordinator.data.items():
        if not device.has_lightbulb:
            continue

        entities.append(
            FritzboxLight(
                {
                    ATTR_NAME: f"{device.name}",
                    ATTR_ENTITY_ID: f"{device.ain}",
                    ATTR_UNIT_OF_MEASUREMENT: None,
                    ATTR_DEVICE_CLASS: DEVICE_CLASS_LIGHT,
                },
                coordinator,
                ain,
            )
        )

    async_add_entities(entities)


class FritzboxLight(FritzBoxEntity, LightEntity):
    """Representation of a light bulb FRITZ!SmartHome device."""

    def __init__(
        self,
        entity_info: EntityInfo,
        coordinator: DataUpdateCoordinator[dict[str, FritzhomeDevice]],
        ain: str,
    ) -> None:
        """Init FritzboxLight entity."""
        super().__init__(entity_info, coordinator, ain)

        self._supported_colors: list[HsColor] = []
        supported_colors: dict[str, list[HsColor]] = self.device.get_colors()
        for _name, colors in supported_colors.items():
            self._supported_colors.extend(colors)

        self._supported_color_temps: list[int] = self.device.get_color_temps()
        self._min_mireds = 153  # 6500K
        self._max_mireds = 370  # 2700K

        if self.device.supported_color_mode == 1:
            self._supported_color_mode = {COLOR_MODE_COLOR_TEMP}
        elif self.device.supported_color_mode == 4:
            self._supported_color_mode = {COLOR_MODE_HS}
        elif self.device.supported_color_mode == 5:
            self._supported_color_mode = {COLOR_MODE_HS, COLOR_MODE_COLOR_TEMP}
        else:
            self._supported_color_mode = {COLOR_MODE_ONOFF}

    @property
    def is_on(self) -> bool:
        """Return true if light bulb is on."""
        if not self.device.present:
            return False
        return self.device.state  # type: ignore [no-any-return]

    @property
    def brightness(self) -> int | None:
        """Return the brightness of the light."""
        return self.device.level  # type: ignore [no-any-return]

    @property
    def supported_color_modes(self) -> set[str]:
        """Flag supported color modes."""
        return self._supported_color_mode

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the color of the light."""
        if self.device.hue is not None and self.device.saturation is not None:
            return (self.device.hue, self.device.saturation)
        return None

    @property
    def color_temp(self) -> int | None:
        """Return the color temp of the light."""
        if self.device.color_temp is not None:
            return color_temperature_kelvin_to_mired(self.device.color_temp)
        return None

    @property
    def color_mode(self) -> str | None:
        """Return the color mode of the light."""
        if self.device.color_mode == 1:
            return COLOR_MODE_COLOR_TEMP
        elif self.device.color_mode == 4:
            return COLOR_MODE_HS
        return None

    @property
    def min_mireds(self) -> int:
        """Return the coldest color_temp that this light supports."""
        return self._min_mireds

    @property
    def max_mireds(self) -> int:
        """Return the warmest color_temp that this light supports."""
        return self._max_mireds

    def _nearest_supported_color(
        self, hs_color: tuple[float, float]
    ) -> tuple[float, float]:
        """Return nearest matching supported hs color."""
        hue_values = [color[0] for color in self._supported_colors]
        nearest_hue_value = min(hue_values, key=lambda x: abs(x - hs_color[0]))

        sat_values = [
            color[1]
            for color in self._supported_colors
            if color[0] == nearest_hue_value
        ]
        nearest_sat_value = min(sat_values, key=lambda x: abs(x - hs_color[1]))
        return (nearest_hue_value, nearest_sat_value)

    def _nearest_supported_color_temp(self, color_temp: int) -> int:
        """Return nearest matching supported color temperature."""
        return min(self._supported_color_temps, key=lambda x: abs(x - color_temp))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        if ATTR_HS_COLOR in kwargs and self._supported_colors:
            hs_color = self._nearest_supported_color(kwargs[ATTR_HS_COLOR])
            await self.hass.async_add_executor_job(self.device.set_color, hs_color)

        elif ATTR_COLOR_TEMP in kwargs and self._supported_color_temps:
            color_temp = self._nearest_supported_color_temp(
                color_temperature_mired_to_kelvin(kwargs[ATTR_COLOR_TEMP])
            )
            await self.hass.async_add_executor_job(
                self.device.set_color_temp, color_temp
            )

        else:
            await self.hass.async_add_executor_job(self.device.set_state_on)

        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn of the light."""
        await self.hass.async_add_executor_job(self.device.set_state_off)
        await self.coordinator.async_refresh()
