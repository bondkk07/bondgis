"""Catálogo de camadas externas e funções para adicioná-las ao QGIS.

Espelha as fontes configuradas no WebGIS (camadas_externas_fallback.py).
"""

CAMADAS_EXTERNAS = [
    # ── Fontes Externas ──────────────────────────────────────────────────
    {
        "titulo": "Embargos IBAMA",
        "grupo":  "Fontes Externas",
        "tipo":   "arcgis",
        "url":    "https://pamgia.ibama.gov.br/server/rest/services/01_Publicacoes_Bases/adm_embargos_ibama_a/MapServer/0/query",
    },
    {
        "titulo":    "Terras Indígenas (FUNAI)",
        "grupo":     "Fontes Externas",
        "tipo":      "wfs",
        "url":       "https://geoserver.funai.gov.br/geoserver/Funai/wfs",
        "type_name": "Funai:tis_poligonais",
        "version":   "2.0.0",
    },
    {
        "titulo":    "Sítios Arqueológicos (IPHAN)",
        "grupo":     "Fontes Externas",
        "tipo":      "wfs",
        "url":       "https://geoserver.iphan.gov.br/geoserver/SICG/ows",
        "type_name": "SICG:sitios",
        "version":   "1.0.0",
    },
    {
        "titulo":               "Malha Municipal IBGE 2020",
        "grupo":                "Fontes Externas",
        "tipo":                 "wfs",
        "url":                  "https://geoservicos.ibge.gov.br/geoserver/ows",
        "type_name":            "CGEO:andb2022_020302",
        "version":              "2.0.0",
        "ignorar_sobreposicao": True,   # usada apenas como referência cartográfica
    },
    {
        "titulo":               "APF Geometria Regular (SEMA-MT)",
        "grupo":                "SEMA-MT",
        "tipo":                 "wfs",
        "url":                  "https://geo.sema.mt.gov.br/geoserver/wfs",
        "type_name":            "Geoportal:MVW_APF_GEOMETRIA_REGULAR",
        "version":              "2.0.0",
        "params":               {"authkey": "541085de-9a2e-454e-bdba-eb3d57a2f492"},
        "ignorar_sobreposicao": True,   # usada no cálculo de área beneficiável (MT)
    },
    {
        "titulo":    "Áreas Embargadas SEMA-MT",
        "grupo":     "SEMA-MT",
        "tipo":      "wfs",
        "url":       "https://geo.sema.mt.gov.br/geoserver/wfs",
        "type_name": "Geoportal:AREAS_EMBARGADAS_SEMA",
        "version":   "2.0.0",
        "params":    {"authkey": "541085de-9a2e-454e-bdba-eb3d57a2f492"},
    },
    {
        "titulo":    "Áreas Embargadas ICMBio",
        "grupo":     "ICMBio",
        "tipo":      "wfs",
        "url":       "https://geoservicos.inde.gov.br/geoserver/ICMBio/wfs",
        "type_name": "ICMBio:embargos_icmbio",
        "version":   "2.0.0",
    },
    {
        "titulo":    "Autos de Infração ICMBio",
        "grupo":     "ICMBio",
        "tipo":      "wfs",
        "url":       "https://geoservicos.inde.gov.br/geoserver/ICMBio/wfs",
        "type_name": "ICMBio:autos_infracao_icmbio",
        "version":   "2.0.0",
    },
    {
        "titulo": "Florestas Públicas Tipo B (CNFP 2024)",
        "grupo":  "Fontes Externas",
        "tipo":   "arcgis",
        "url":    "https://smapas.florestal.gov.br/server/rest/services/Hosted/Cadastro_Nacional_de_Florestas_P%C3%BAblicas_Atualiza%C3%A7%C3%A3o_2024_Retificado/FeatureServer/0/query",
        "params": {"where": "tipo = 'TIPO B'"},
    },
    # ── PRODES desmatamento (MCR: somente anos >= 2019) ─────────────────────
    # sobrep_filter é aplicado APÓS a interseção geométrica.
    # Tenta múltiplos nomes de campo e extrai ano de strings de data.
    {
        "titulo":        "PRODES Amazônia – Desmatamento anual",
        "grupo":         "Alertas / PRODES",
        "tipo":          "wfs",
        "url":           "https://terrabrasilis.dpi.inpe.br/geoserver/prodes-legal-amz/yearly_deforestation/ows",
        "type_name":     "prodes-legal-amz:yearly_deforestation",
        "version":       "2.0.0",
        "sobrep_filter": {"campos": ["year", "YEAR", "view_date", "ano", "ANO", "year_deforestation"], "op": "gte", "valor": 2019},
    },
    {
        "titulo":        "PRODES Cerrado – Desmatamento anual",
        "grupo":         "Alertas / PRODES",
        "tipo":          "wfs",
        "url":           "https://terrabrasilis.dpi.inpe.br/geoserver/prodes-cerrado-nb/yearly_deforestation/ows",
        "type_name":     "prodes-cerrado-nb:yearly_deforestation",
        "version":       "2.0.0",
        "sobrep_filter": {"campos": ["year", "YEAR", "view_date", "ano", "ANO", "year_deforestation"], "op": "gte", "valor": 2019},
    },
    {
        "titulo":        "PRODES Mata Atlântica – Desmatamento anual",
        "grupo":         "Alertas / PRODES",
        "tipo":          "wfs",
        "url":           "https://terrabrasilis.dpi.inpe.br/geoserver/prodes-mata-atlantica-nb/yearly_deforestation/ows",
        "type_name":     "prodes-mata-atlantica-nb:yearly_deforestation",
        "version":       "2.0.0",
        "sobrep_filter": {"campos": ["year", "YEAR", "view_date", "ano", "ANO", "year_deforestation"], "op": "gte", "valor": 2019},
    },
    {
        "titulo":        "PRODES Caatinga – Desmatamento anual",
        "grupo":         "Alertas / PRODES",
        "tipo":          "wfs",
        "url":           "https://terrabrasilis.dpi.inpe.br/geoserver/prodes-caatinga-nb/yearly_deforestation/ows",
        "type_name":     "prodes-caatinga-nb:yearly_deforestation",
        "version":       "2.0.0",
        "sobrep_filter": {"campos": ["year", "YEAR", "view_date", "ano", "ANO", "year_deforestation"], "op": "gte", "valor": 2019},
    },
    {
        "titulo":        "PRODES Pampa – Desmatamento anual",
        "grupo":         "Alertas / PRODES",
        "tipo":          "wfs",
        "url":           "https://terrabrasilis.dpi.inpe.br/geoserver/prodes-pampa-nb/yearly_deforestation/ows",
        "type_name":     "prodes-pampa-nb:yearly_deforestation",
        "version":       "2.0.0",
        "sobrep_filter": {"campos": ["year", "YEAR", "view_date", "ano", "ANO", "year_deforestation"], "op": "gte", "valor": 2019},
    },
    # ── Áreas atribuídas ────────────────────────────────────────────────
    {
        "titulo":      "Assentamentos Rurais – EMBRAPA 2023",
        "grupo":       "Áreas Atribuídas",
        "tipo":        "wfs",
        "url":         "https://geoinfo.dados.embrapa.br/geoserver/wfs",
        "type_name":   "geonode:areasatribuidas2023",
        "version":     "2.0.0",
        "attr_filter": {"campo": "categoria", "valor": "assentamento"},
    },
    {
        "titulo":      "Quilombolas – EMBRAPA 2023",
        "grupo":       "Áreas Atribuídas",
        "tipo":        "wfs",
        "url":         "https://geoinfo.dados.embrapa.br/geoserver/wfs",
        "type_name":   "geonode:areasatribuidas2023",
        "version":     "2.0.0",
        "attr_filter": {"campo": "categoria", "valor": "quilombola"},
    },
    {
        "titulo":      "Unidades de Conservação – EMBRAPA 2023",
        "grupo":       "Áreas Atribuídas",
        "tipo":        "wfs",
        "url":         "https://geoinfo.dados.embrapa.br/geoserver/wfs",
        "type_name":   "geonode:areasatribuidas2023",
        "version":     "2.0.0",
        "attr_filter": {"campo": "categoria", "valor": "unidade de conservacao"},
    },
    # ── Mosaicos ────────────────────────────────────────────────────────
    {
        "titulo": "Sentinel-2 Cloudless 2024 (EOX)",
        "grupo":  "Mosaicos",
        "tipo":   "wms",
        "url":    "https://tiles.maps.eox.at/wms",
        "layers": "s2cloudless-2024_3857",
        "format": "image/jpeg",
    },
    {
        "titulo": "Sentinel-2 Cloudless 2022 (EOX)",
        "grupo":  "Mosaicos",
        "tipo":   "wms",
        "url":    "https://tiles.maps.eox.at/wms",
        "layers": "s2cloudless-2022_3857",
        "format": "image/jpeg",
    },
    {
        "titulo": "Mosaico PRODES Amazônia 2024",
        "grupo":  "Mosaicos",
        "tipo":   "wms",
        "url":    "https://terrabrasilis.dpi.inpe.br/geoserver/prodes-legal-amz/wms",
        "layers": "temporal_mosaic_legal_amazon",
        "params": {"time": "2024-01-01T00:00:00.000Z", "version": "1.3.0"},
    },
    # ── ZSEE Rondônia ───────────────────────────────────────────────────
    {
        "titulo":    "ZSEE Rondônia 2005 (SEDAM)",
        "grupo":     "Fontes Externas / SEDAM-RO",
        "tipo":      "wfs",
        "url":       "https://geoportal.sedam.ro.gov.br/geoserver/ows",
        "type_name": "cogeo:ZSEE_2Aprox_2005_312_SIRGAS2000_4674",
        "version":   "2.0.0",
    },
]


def adicionar_camada_wfs(camada_info: dict) -> None:
    """Adiciona camada WFS ao projeto QGIS."""
    import urllib.parse
    from qgis.core import QgsVectorLayer, QgsProject

    url       = camada_info['url']
    type_name = camada_info.get('type_name', '')
    version   = camada_info.get('version', '2.0.0')
    titulo    = camada_info['titulo']

    # Parâmetros que vão na URL (ex: authkey do GeoServer) vs URI do provider
    extra_params = dict(camada_info.get('params', {}))
    url_params   = {}
    for chave in ('authkey', 'token', 'apikey'):
        if chave in extra_params:
            url_params[chave] = extra_params.pop(chave)

    if url_params:
        sep = '&' if '?' in url else '?'
        url = url + sep + urllib.parse.urlencode(url_params)

    uri = (
        f"pagingEnabled='true' "
        f"preferCoordinatesForWfsT11='false' "
        f"restrictToRequestBBOX='1' "
        f"srsname='EPSG:4326' "
        f"typename='{type_name}' "
        f"url='{url}' "
        f"version='{version}'"
    )

    layer = QgsVectorLayer(uri, titulo, 'WFS')
    if not layer.isValid():
        raise RuntimeError(f"Não foi possível carregar a camada WFS: {titulo}")
    QgsProject.instance().addMapLayer(layer)


def adicionar_camada_wms(camada_info: dict) -> None:
    """Adiciona camada WMS ao projeto QGIS."""
    from qgis.core import QgsRasterLayer, QgsProject

    url    = camada_info['url']
    layers = camada_info.get('layers', '')
    fmt    = camada_info.get('format', 'image/png')
    titulo = camada_info['titulo']

    extra = camada_info.get('params', {})
    extra_str = '&'.join(f"{k}={v}" for k, v in extra.items())

    uri = (
        f"crs=EPSG:4326&dpiMode=7&featureCount=10"
        f"&format={fmt}&layers={layers}&styles=&url={url}"
    )
    if extra_str:
        uri += f"&{extra_str}"

    layer = QgsRasterLayer(uri, titulo, 'wms')
    if not layer.isValid():
        raise RuntimeError(f"Não foi possível carregar a camada WMS: {titulo}")
    QgsProject.instance().addMapLayer(layer)


def adicionar_camada_arcgis(camada_info: dict) -> None:
    """Baixa dados de um ArcGIS Feature Server via GeoJSON e adiciona ao projeto."""
    import json
    import tempfile
    import os
    import urllib.request
    from qgis.core import QgsVectorLayer, QgsProject

    url    = camada_info.get('url', '')
    titulo = camada_info['titulo']
    extra  = camada_info.get('params', {})

    default_params = {'where': '1=1', 'outFields': '*', 'f': 'geojson', 'outSR': '4326'}
    default_params.update(extra)

    from urllib.parse import urlencode
    full_url = f"{url}?{urlencode(default_params)}"

    req = urllib.request.Request(
        full_url,
        headers={'User-Agent': 'QGIS-LyssaPlugin/1.0'},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        geojson_data = resp.read().decode('utf-8')

    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.geojson', delete=False, encoding='utf-8'
    )
    tmp.write(geojson_data)
    tmp_path = tmp.name
    tmp.close()

    layer = QgsVectorLayer(tmp_path, titulo, 'ogr')
    if not layer.isValid():
        os.unlink(tmp_path)
        raise RuntimeError(f"Não foi possível carregar: {titulo}")
    QgsProject.instance().addMapLayer(layer)
