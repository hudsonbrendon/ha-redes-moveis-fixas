# Redes Móveis Fixas

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Integração para o [Home Assistant](https://www.home-assistant.io/) que consulta a
API [redesmoveisfixas.com](https://redesmoveisfixas.com) — cobertura móvel, torres
(ERBs) próximas e estatísticas de município no Brasil — e recebe atualizações em
tempo real via webhook.

## O que a integração faz

- **Cobertura num local** — score de sinal por operadora (2G/3G/4G/5G) para uma
  zona fixa ou para uma pessoa cujo GPS é acompanhado.
- **Torres próximas, incluindo mapa** — ERBs num raio de 5 km do local, com a
  mais próxima em destaque e as N mais próximas plotadas como `geo_location` no
  mapa do Home Assistant.
- **Estatísticas de município** — totais de ERBs/estações por tecnologia para
  um código IBGE, com quebra por operadora.
- **Dois monitores de webhook** — a API RMF avisa em tempo real quando surge uma
  torre nova ou upgrade de tecnologia num município monitorado, e quando um
  bundle de operadora do iOS muda (novo, alterado ou removido). Cada entrega
  também dispara um evento no bus do Home Assistant
  (`redes_moveis_fixas_novidade`), além das entidades `event.*`.

### Requisito para os monitores: URL pública HTTPS

Os monitores de município e de iOS são registrados na API RMF com a URL do
webhook deste Home Assistant. Isso exige um `external_url` público em HTTPS
configurado em **Configurações → Sistema → Rede** (ou Nabu Casa Cloud). Se você
adicionar um município com "monitorar" ativado, ou um monitor de iOS, antes de
ter uma URL pública configurada, a configuração da entrada fica tentando de
novo (`ConfigEntryNotReady`) até que uma URL esteja disponível. Locais sem
monitoramento e monitores já provisionados numa configuração anterior não são
afetados — a integração carrega normalmente sem URL pública nesses casos.

## Instalação

Via [HACS](https://hacs.xyz/) como repositório customizado:

1. HACS → menu (⋮) → **Repositórios customizados**.
2. URL: `https://github.com/hudsonbrendon/ha-redes-moveis-fixas`, categoria
   **Integração**.
3. Instale "Redes Móveis Fixas" e reinicie o Home Assistant.
4. **Configurações → Dispositivos e serviços → Adicionar integração** → "Redes
   Móveis Fixas" → informe o token da API (crie o seu em
   [redesmoveisfixas.com/createapi](https://redesmoveisfixas.com/createapi)).
5. Na entrada criada, use **Adicionar** para incluir subentries de **Local**
   (zona ou pessoa), **Município** (código IBGE) e/ou **Monitor iOS**.

## Entidades

**Device "API RMF"** (nível da entrada):

| Entidade | Descrição |
|---|---|
| `binary_sensor.status_da_api_rmf` | Conectividade, via `/health` |
| `sensor.base_de_cobertura_atualizada_em` | Timestamp da última atualização da base de cobertura |
| `sensor.base_de_estacoes_atualizada_em` | Timestamp da última atualização da base de estações |

**Device por subentry Local** (ex. "Casa"):

| Entidade | Descrição |
|---|---|
| `sensor.cobertura_da_<operadora>_em_casa` | Uma por operadora retornada pela API; state = score de qualidade (%); atributos com classificação e força de sinal por tecnologia |
| `sensor.melhor_cobertura_em_casa` | Operadora com o maior score |
| `binary_sensor.5g_disponivel_em_casa` | Liga se alguma operadora tem 5G disponível |
| `sensor.erbs_por_perto_de_casa` | Total de ERBs num raio de 5 km; atributos com contagem por operadora e por tecnologia |
| `sensor.distancia_da_erb_mais_proxima_de_casa` | Distância (km) até a ERB mais próxima; atributos com operadora, endereço, tecnologias e bandas |
| `geo_location.erb_*` | Até N ERBs mais próximas plotadas no mapa (N = "Máx. de torres no mapa"; 0 desliga) |

**Device por subentry Município** (ex. "São Paulo (SP)"):

| Entidade | Descrição |
|---|---|
| `sensor.erbs_em_<municipio>` | Total de ERBs celulares |
| `sensor.estacoes_em_<municipio>` | Total de estações |
| `sensor.erbs_5g_em_<municipio>` (e 4g/3g/2g) | Total por tecnologia; atributos com quebra por operadora |
| `sensor.base_de_<municipio>_atualizada_em` | Timestamp da última atualização da base |
| `event.novas_torres_em_<municipio>` | Dispara `nova_erb` ou `upgrade_tecnologia` quando o monitor entrega uma novidade |
| `binary_sensor.monitor_de_<municipio>_ativo` | Só existe se "monitorar" estiver ativado; atributos: `falhas_seguidas`, `ultima_entrega`, `ultimo_erro` |

**Device por subentry Monitor iOS**:

| Entidade | Descrição |
|---|---|
| `event.novidades_do_ios` | Dispara `nova`, `alterada` ou `removida` por bundle de operadora Apple |
| `sensor.ultima_novidade_do_ios` | Timestamp da última entrega do monitor |
| `binary_sensor.monitor_ios_ativo` | Atributos: `falhas_seguidas`, `ultima_entrega`, `ultimo_erro` |

> Os sensores de contagem (ERBs/estações do município, por tecnologia) usam
> `state_class: measurement`, não `total` — são totais correntes lidos a cada
> atualização, não um acumulador incremental.

## Actions

Todas retornam dados (`supports_response: only` — chame com "usar resposta"/
`response_variable`, não funcionam como alvo de uma automação que ignora a
resposta).

### `redes_moveis_fixas.consultar_cobertura`

Cobertura por operadora num ponto. Aceita `latitude`/`longitude` **ou**
`entity_id` de uma zona/pessoa (se os dois forem informados, `entity_id` tem
precedência).

```yaml
action: redes_moveis_fixas.consultar_cobertura
data:
  entity_id: zone.home
response_variable: cobertura
```

### `redes_moveis_fixas.buscar_estacoes`

Lista de ERBs num ponto, com filtros opcionais.

```yaml
action: redes_moveis_fixas.buscar_estacoes
data:
  latitude: -5.812757
  longitude: -35.255127
  operadora: "claro,vivo"
  tecnologia: "NR,LTE"
  limite: 50
response_variable: estacoes
```

### `redes_moveis_fixas.resumo_do_municipio`

Resumo de estações de um município pelo código IBGE (7 dígitos).

```yaml
action: redes_moveis_fixas.resumo_do_municipio
data:
  codigo_ibge: 3550308
response_variable: resumo
```

## Limitações conhecidas

- **Operadora nova exige reload.** Os sensores `sensor.cobertura_da_<operadora>_*`
  são criados uma vez, no setup da entrada, a partir das operadoras que a API
  devolveu naquele momento. Se uma operadora passar a atender o local depois
  disso, o sensor dela só aparece depois de um reload da entrada (ou reinício).
- **Local em modo "zona" não acompanha a zona se ela for movida.** As
  coordenadas de um local em modo "zona" são lidas uma única vez no setup. Só o
  modo "pessoa" tem um listener que acompanha o `person.*` em tempo real
  (> 500 m e ≥ 10 min desde a última atualização). Se você mover a zona, recarregue
  a entrada para as coordenadas novas valerem.
- **Monitores de webhook exigem URL pública HTTPS.** Veja a seção acima — sem
  `external_url`/Nabu Casa Cloud, a integração ainda carrega para locais e
  municípios não monitorados, mas não consegue provisionar um monitor novo.

## Cotas da API e intervalos padrão

Cota por token, compartilhada entre todas as subentries da mesma entrada.

| Coordinator | Endpoint | Cota da API | Intervalo padrão | Configurável em |
|---|---|---|---|---|
| Cobertura (por local) | `GET /api/cobertura` | 2.000/dia, 60/min | 30 min | subentry Local |
| ERBs (por local) | `GET /api/estacoes` | 500/dia, 20/min | 6 h | subentry Local |
| Município | `GET /api/municipios/{ibge}/resumo` | 5.000/dia, 120/min | 12 h | subentry Município |
| Health (entrada) | `GET /health` (sem auth) | — | 15 min | fixo |
| Monitores (entrada) | `GET /api/monitorar-*` | 200/dia, 20/min | 6 h | fixo |

Um token expira a cada 90 dias; quando isso acontece, a integração pede reauth
automaticamente.

## Desenvolvimento

```bash
python -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check custom_components/ tests/
.venv/bin/ruff format --check custom_components/ tests/
```
