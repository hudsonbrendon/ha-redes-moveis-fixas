"""Constantes da integração Redes Móveis Fixas."""

from datetime import timedelta

DOMAIN = "redes_moveis_fixas"

BASE_URL = "https://api.redesmoveisfixas.com"

# Config entry
CONF_TOKEN = "token"
CONF_WEBHOOK_ID = "webhook_id"

# Subentry types
SUBENTRY_LOCAL = "local"
SUBENTRY_MUNICIPIO = "municipio"
SUBENTRY_MONITOR_IOS = "monitor_ios"

# Subentry Local
CONF_MODO = "modo"  # "zona" | "pessoa"
CONF_ENTITY_ID = "entity_id"
CONF_INTERVALO_COBERTURA = "intervalo_cobertura"  # minutos
CONF_INTERVALO_ERBS = "intervalo_erbs"  # horas
CONF_MAX_GEO = "max_geo"

DEFAULT_INTERVALO_COBERTURA_MIN = 30
DEFAULT_INTERVALO_ERBS_H = 6
DEFAULT_MAX_GEO = 25

# Subentry Município
CONF_IBGE = "codigo_ibge"
CONF_MONITORAR = "monitorar"
CONF_INTERVALO_MUNICIPIO = "intervalo_municipio"  # horas
DEFAULT_INTERVALO_MUNICIPIO_H = 12

# Subentry Monitor iOS
CONF_PAISES = "paises"
CONF_OPERADORAS = "operadoras"
CONF_INCLUIR_BETA = "incluir_beta"

# Monitor (comum às subentries com webhook)
CONF_MONITOR_ID = "monitor_id"
CONF_MONITOR_SECRET = "monitor_secret"

# Intervalos fixos (entry-level)
INTERVALO_HEALTH = timedelta(minutes=15)
INTERVALO_MONITORES = timedelta(hours=6)

# Person-follow
DISTANCIA_MINIMA_M = 500
INTERVALO_MINIMO_PESSOA = timedelta(minutes=10)

# Webhook
TOLERANCIA_TIMESTAMP_S = 300
EVENTO_CIDADE = "novidades.cidade"
EVENTO_IOS = "novidades.ios"

# Bus / dispatcher
EVENT_NOVIDADE = "redes_moveis_fixas_novidade"
SIGNAL_NOVIDADE = "redes_moveis_fixas_novidade_{}"  # .format(subentry_id)

PLATFORMS = ["binary_sensor", "event", "geo_location", "sensor"]
