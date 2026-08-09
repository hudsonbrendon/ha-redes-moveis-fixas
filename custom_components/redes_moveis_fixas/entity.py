"""Entidades base."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RMFCoordinator


class RMFEntity(CoordinatorEntity[RMFCoordinator]):
    """Base: um device por subentry, nome completo em PT-BR."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: RMFCoordinator,
        subentry: ConfigSubentry,
        chave: str,
        nome: str,
    ) -> None:
        super().__init__(coordinator)
        self._subentry = subentry
        self._attr_unique_id = f"{subentry.subentry_id}_{chave}"
        self._attr_name = nome
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Redes Móveis Fixas",
            entry_type=DeviceEntryType.SERVICE,
        )


class RMFEntryEntity(CoordinatorEntity[RMFCoordinator]):
    """Base: device da própria entry ("API RMF")."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: RMFCoordinator,
        entry: ConfigEntry,
        chave: str,
        nome: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{chave}"
        self._attr_name = nome
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="API RMF",
            manufacturer="Redes Móveis Fixas",
            entry_type=DeviceEntryType.SERVICE,
        )
