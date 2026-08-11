"""Sensores da integração RMF."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import SUBENTRY_LOCAL, SUBENTRY_MONITOR_IOS, SUBENTRY_MUNICIPIO
from .entity import RMFEntity, RMFEntryEntity

TECNOLOGIAS = ("2G", "3G", "4G", "5G")


def _parse_timestamp(valor: str | None) -> datetime | None:
    """Converte string ISO em datetime aware (UTC se vier sem offset).

    HA exige tz-aware pra sensores TIMESTAMP; sem isto, um valor sem offset
    passa aqui mas explode depois, no `state` property.
    """
    if not valor:
        return None
    dt = dt_util.parse_datetime(valor)
    if dt is None:
        return None
    return dt_util.as_utc(dt) if dt.tzinfo is None else dt


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    rt = entry.runtime_data

    # Device da entry
    async_add_entities(
        [
            BaseAtualizadaEntrySensor(rt.health, entry, dep)
            for dep in ("cobertura", "estacoes")
        ]
    )

    for subentry in entry.subentries.values():
        sid = subentry.subentry_id
        entities: list[SensorEntity] = []
        if subentry.subentry_type == SUBENTRY_LOCAL:
            cob = rt.cobertura[sid]
            provedores = [
                p
                for c in (cob.data or {}).get("cobertura", [])
                if (p := c.get("provedor")) is not None
            ]
            entities += [CoberturaOperadoraSensor(cob, subentry, p) for p in provedores]
            entities.append(MelhorCoberturaSensor(cob, subentry))
            entities.append(ErbsPorPertoSensor(rt.erbs[sid], subentry))
            entities.append(DistanciaErbSensor(rt.erbs[sid], subentry))
        elif subentry.subentry_type == SUBENTRY_MUNICIPIO:
            mun = rt.municipio[sid]
            entities.append(TotalSensor(mun, subentry, "erbs_celular", "ERBs"))
            entities.append(TotalSensor(mun, subentry, "estacoes", "Estações"))
            entities += [
                ErbsTecnologiaSensor(mun, subentry, tec) for tec in TECNOLOGIAS
            ]
            entities.append(BaseMunicipioSensor(mun, subentry))
        elif subentry.subentry_type == SUBENTRY_MONITOR_IOS:
            entities.append(UltimaNovidadeIosSensor(rt.monitores, subentry))
        if entities:
            async_add_entities(entities, config_subentry_id=sid)


class BaseAtualizadaEntrySensor(RMFEntryEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry, dependencia: str) -> None:
        super().__init__(
            coordinator,
            entry,
            f"base_{dependencia}",
            f"Base de {dependencia.capitalize()} atualizada em",
        )
        self._dependencia = dependencia

    @property
    def native_value(self):
        for dep in (self.coordinator.data or {}).get("dependencias", []):
            if dep.get("nome") == self._dependencia:
                return _parse_timestamp(dep.get("atualizado_em"))
        return None


class CoberturaOperadoraSensor(RMFEntity, SensorEntity):
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, subentry, provedor: str) -> None:
        super().__init__(
            coordinator,
            subentry,
            f"cobertura_{provedor.lower()}",
            f"Cobertura da {provedor} em {subentry.title}",
        )
        self._provedor = provedor

    def _item(self) -> dict | None:
        for c in (self.coordinator.data or {}).get("cobertura", []):
            if c.get("provedor") == self._provedor:
                return c
        return None

    @property
    def native_value(self):
        item = self._item()
        if not item:
            return None
        return item.get("qualidade_global", {}).get("score_percentual")

    @property
    def extra_state_attributes(self):
        item = self._item()
        if not item:
            return {}
        attrs = {"classificacao": item.get("qualidade_global", {}).get("classificacao")}
        for tec in item.get("tecnologias_suportadas", []):
            rede = tec.get("rede")
            if rede is not None:
                attrs[rede] = tec.get("forca_sinal")
        return attrs


class MelhorCoberturaSensor(RMFEntity, SensorEntity):
    def __init__(self, coordinator, subentry) -> None:
        super().__init__(
            coordinator, subentry, "melhor", f"Melhor cobertura em {subentry.title}"
        )

    @property
    def native_value(self):
        itens = [
            c
            for c in (self.coordinator.data or {}).get("cobertura", [])
            if c.get("qualidade_global", {}).get("score_percentual") is not None
        ]
        if not itens:
            return None
        melhor = max(itens, key=lambda c: c["qualidade_global"]["score_percentual"])
        return melhor.get("provedor")


class ErbsPorPertoSensor(RMFEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, subentry) -> None:
        super().__init__(
            coordinator, subentry, "erbs_total", f"ERBs por perto de {subentry.title}"
        )

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("total_erbs")

    @property
    def extra_state_attributes(self):
        erbs = (self.coordinator.data or {}).get("erbs", [])
        por_op: dict[str, int] = {}
        por_tec: dict[str, int] = {}
        for erb in erbs:
            if not isinstance(erb, dict):
                continue
            op = erb.get("operadora")
            if op is not None:
                por_op[op] = por_op.get(op, 0) + 1
            for tec in erb.get("tecnologias", []):
                por_tec[tec] = por_tec.get(tec, 0) + 1
        return {"por_operadora": por_op, "por_tecnologia": por_tec}


class DistanciaErbSensor(RMFEntity, SensorEntity):
    _attr_native_unit_of_measurement = "km"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, subentry) -> None:
        super().__init__(
            coordinator,
            subentry,
            "erb_proxima",
            f"Distância da ERB mais próxima de {subentry.title}",
        )

    def _mais_proxima(self) -> dict | None:
        candidatos = [
            e
            for e in (self.coordinator.data or {}).get("erbs", [])
            if isinstance(e, dict) and e.get("distancia_km") is not None
        ]
        return min(candidatos, key=lambda e: e["distancia_km"]) if candidatos else None

    @property
    def native_value(self):
        erb = self._mais_proxima()
        return erb.get("distancia_km") if erb else None

    @property
    def extra_state_attributes(self):
        erb = self._mais_proxima()
        if not erb:
            return {}
        return {
            "operadora": erb.get("operadora"),
            "endereco": erb.get("endereco"),
            "tecnologias": erb.get("tecnologias"),
            "bandas": erb.get("bandas"),
        }


class TotalSensor(RMFEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, subentry, campo: str, rotulo: str) -> None:
        super().__init__(coordinator, subentry, campo, f"{rotulo} em {subentry.title}")
        self._campo = campo

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("totais", {}).get(self._campo)


class ErbsTecnologiaSensor(RMFEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, subentry, tec: str) -> None:
        super().__init__(
            coordinator,
            subentry,
            f"erbs_{tec.lower()}",
            f"ERBs {tec} em {subentry.title}",
        )
        self._tec = tec

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("por_tecnologia", {}).get(self._tec)

    @property
    def extra_state_attributes(self):
        por_op = {}
        for op in (self.coordinator.data or {}).get("por_operadora", []):
            operadora = op.get("operadora")
            if operadora is None:
                continue
            por_op[operadora] = op.get("tecnologias", {}).get(self._tec)
        return {"por_operadora": por_op}


class BaseMunicipioSensor(RMFEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, subentry) -> None:
        super().__init__(
            coordinator,
            subentry,
            "base_atualizada",
            f"Base de {subentry.title} atualizada em",
        )

    @property
    def native_value(self):
        return _parse_timestamp((self.coordinator.data or {}).get("base_atualizada_em"))


class UltimaNovidadeIosSensor(RMFEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, subentry) -> None:
        super().__init__(
            coordinator, subentry, "ultima_novidade", "Última novidade do iOS"
        )
        self._monitor_id = subentry.data.get("monitor_id")

    @property
    def native_value(self):
        mon = (self.coordinator.data or {}).get(self._monitor_id)
        if not mon:
            return None
        return _parse_timestamp(mon.get("ultima_entrega"))
