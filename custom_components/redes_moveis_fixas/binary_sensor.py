"""Binary sensors da integração RMF."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MONITOR_ID,
    SUBENTRY_LOCAL,
    SUBENTRY_MONITOR_IOS,
    SUBENTRY_MUNICIPIO,
)
from .entity import RMFEntity, RMFEntryEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    rt = entry.runtime_data
    async_add_entities([StatusApiBinarySensor(rt.health, entry)])

    for subentry in entry.subentries.values():
        sid = subentry.subentry_id
        entities: list[BinarySensorEntity] = []
        if subentry.subentry_type == SUBENTRY_LOCAL:
            entities.append(Disponivel5GBinarySensor(rt.cobertura[sid], subentry))
        elif subentry.subentry_type == SUBENTRY_MUNICIPIO and subentry.data.get(
            CONF_MONITOR_ID
        ):
            entities.append(
                MonitorAtivoBinarySensor(rt.monitores, subentry, "Monitor ativo")
            )
        elif subentry.subentry_type == SUBENTRY_MONITOR_IOS:
            entities.append(
                MonitorAtivoBinarySensor(rt.monitores, subentry, "Monitor ativo")
            )
        if entities:
            async_add_entities(entities, config_subentry_id=sid)


class StatusApiBinarySensor(RMFEntryEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "status", "Status")

    @property
    def is_on(self) -> bool:
        return (
            self.coordinator.last_update_success
            and (self.coordinator.data or {}).get("status") == "ok"
        )


class Disponivel5GBinarySensor(RMFEntity, BinarySensorEntity):
    _attr_icon = "mdi:signal-5g"

    def __init__(self, coordinator, subentry) -> None:
        super().__init__(coordinator, subentry, "5g", "5G disponível")

    @property
    def is_on(self) -> bool:
        for cob in (self.coordinator.data or {}).get("cobertura", []):
            for tec in cob.get("tecnologias_suportadas", []):
                if tec.get("rede") == "5G":
                    return True
        return False


class MonitorAtivoBinarySensor(RMFEntity, BinarySensorEntity):
    _attr_icon = "mdi:webhook"

    def __init__(self, coordinator, subentry, nome: str) -> None:
        super().__init__(coordinator, subentry, "monitor_ativo", nome)
        self._monitor_id = subentry.data.get(CONF_MONITOR_ID)

    def _monitor(self) -> dict | None:
        return (self.coordinator.data or {}).get(self._monitor_id)

    @property
    def is_on(self) -> bool:
        mon = self._monitor()
        return bool(mon and mon.get("ativo"))

    @property
    def extra_state_attributes(self):
        mon = self._monitor() or {}
        return {
            "falhas_seguidas": mon.get("falhas_seguidas"),
            "ultima_entrega": mon.get("ultima_entrega"),
            "ultimo_erro": mon.get("ultimo_erro"),
        }
