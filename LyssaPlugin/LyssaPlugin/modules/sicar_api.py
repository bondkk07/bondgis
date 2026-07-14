"""
Busca de dados do CAR usando os mesmos serviços que o WebGIS LiroGis.

Fontes idênticas ao WebGIS:
  Área do imóvel → https://geoserver.car.gov.br/geoserver/sicar/ows
    TypeName: sicar:sicar_imoveis_{uf}  (UF em minúsculas)
    Versão:   WFS 1.0.0

  Camadas subsidiárias → https://consulta.car.gov.br/geoserver/ows
    Namespace: consulta_publica
    Versão:    WFS 2.0.0

Arquitetura:
  - `buscar_area_imovel()`:   usa QgsVectorLayer WFS (Qt TLS) – chame da thread principal
  - `buscar_camadas_consulta()`: usa urllib + SSL permissivo – pode rodar em QThread
  - `carregar_no_qgis()`:    adiciona ao projeto – sempre na thread principal
"""

import json
import logging
import os
import re
import ssl
import tempfile
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

SICAR_AREA_WFS_URL     = 'https://geoserver.car.gov.br/geoserver/sicar/ows'
SICAR_CONSULTA_WFS_URL = 'https://consulta.car.gov.br/geoserver/ows'

_TIMEOUT = 60

# Subconjunto curado das camadas subsidiárias (espelha consultaCarLayers.js)
CAMADAS_CONSULTA = [
    {'typeName': 'consulta_publica:ast',
     'rotulo': 'Área do Imóvel (AST)', 'grupo': 'AREA_IMOVEL'},
    {'typeName': 'consulta_publica:vegetacao_nativa',
     'rotulo': 'Vegetação Nativa', 'grupo': 'VEGETACAO_NATIVA'},
    {'typeName': 'consulta_publica:arl_proposta',
     'rotulo': 'Reserva Legal Proposta', 'grupo': 'RESERVA_LEGAL'},
    {'typeName': 'consulta_publica:arl_averbada',
     'rotulo': 'Reserva Legal Averbada', 'grupo': 'RESERVA_LEGAL'},
    {'typeName': 'consulta_publica:arl_aprovada_nao_averbada',
     'rotulo': 'Reserva Legal Aprovada (não averbada)', 'grupo': 'RESERVA_LEGAL'},
    {'typeName': 'consulta_publica:app_rio_ate_10',
     'rotulo': 'APP – Rio até 10 m', 'grupo': 'APP'},
    {'typeName': 'consulta_publica:app_rio_10_a_50',
     'rotulo': 'APP – Rio 10 a 50 m', 'grupo': 'APP'},
    {'typeName': 'consulta_publica:app_rio_50_a_200',
     'rotulo': 'APP – Rio 50 a 200 m', 'grupo': 'APP'},
    {'typeName': 'consulta_publica:app_rio_200_a_600',
     'rotulo': 'APP – Rio 200 a 600 m', 'grupo': 'APP'},
    {'typeName': 'consulta_publica:app_rio_acima_600',
     'rotulo': 'APP – Rio acima de 600 m', 'grupo': 'APP'},
    {'typeName': 'consulta_publica:app_nascente_olho_dagua',
     'rotulo': 'APP – Nascente / olho d\'água', 'grupo': 'APP'},
    {'typeName': 'consulta_publica:app_lago_natural',
     'rotulo': 'APP – Lago natural', 'grupo': 'APP'},
    {'typeName': 'consulta_publica:app_borda_chapada',
     'rotulo': 'APP – Borda de chapada', 'grupo': 'APP'},
    {'typeName': 'consulta_publica:app_area_declividade_maior_45',
     'rotulo': 'APP – Declividade > 45°', 'grupo': 'APP'},
    {'typeName': 'consulta_publica:app_area_topo_morro',
     'rotulo': 'APP – Topo de morro', 'grupo': 'APP'},
    {'typeName': 'consulta_publica:area_uso_restrito_declividade_25_a_45',
     'rotulo': 'Uso Restrito – Declividade 25–45°', 'grupo': 'USO_RESTRITO'},
    {'typeName': 'consulta_publica:area_uso_restrito_pantaneira',
     'rotulo': 'Uso Restrito – Pantaneira', 'grupo': 'USO_RESTRITO'},
    {'typeName': 'consulta_publica:area_consolidada',
     'rotulo': 'Área Consolidada', 'grupo': 'OUTRO'},
    {'typeName': 'consulta_publica:area_embargada',
     'rotulo': 'Área Embargada', 'grupo': 'OUTRO'},
    {'typeName': 'consulta_publica:area_servidao_administrativa_total',
     'rotulo': 'Servidão Administrativa', 'grupo': 'OUTRO'},
]


# ===========================================================================
# API PÚBLICA — usada pelo worker e pela aba
# ===========================================================================

def buscar_area_imovel(codigo_car: str) -> dict:
    """Busca a área do imóvel via urllib + SSL permissivo (mesmo mecanismo das subsidiárias).

    Pode ser chamado em QThread (não usa Qt Network).

    Args:
        codigo_car: Código CAR completo.

    Returns:
        {'nome': str, 'rotulo': str, 'geojson': dict, 'grupo': str}

    Raises:
        RuntimeError: Se a área não for encontrada ou a conexão falhar.
    """
    codigo_car = codigo_car.strip().upper()
    uf = _extrair_uf(codigo_car)
    if not uf:
        raise ValueError(f'Código CAR inválido: "{codigo_car}"')

    type_name = f'sicar:sicar_imoveis_{uf}'

    try:
        geojson = _wfs_urllib(SICAR_AREA_WFS_URL, type_name, '1.0.0', codigo_car)
    except Exception as exc:
        raise RuntimeError(
            f'Falha ao conectar ao GeoServer SICAR:\n{exc}\n\n'
            'Verifique sua conexão com a internet.'
        ) from exc

    if not geojson.get('features'):
        raise RuntimeError(
            f'Imóvel não encontrado no GeoServer SICAR:\n{codigo_car}\n\n'
            'Verifique o código CAR e tente novamente.'
        )

    return {
        'nome':   'AREA_IMOVEL',
        'rotulo': 'Área do Imóvel',
        'geojson': geojson,
        'grupo':  'AREA_IMOVEL',
    }


def buscar_camadas_consulta(codigo_car: str, callback=None) -> list:
    """Busca as camadas subsidiárias via urllib (pode rodar em QThread).

    Usa SSL permissivo para contornar restrições do Python/OpenSSL no Windows.

    Args:
        codigo_car: Código CAR completo.
        callback:   callable(msg: str) para atualizar UI.

    Returns:
        Lista de {'nome', 'rotulo', 'geojson', 'grupo'}.
    """
    codigo_car = codigo_car.strip().upper()
    resultados = []
    total      = len(CAMADAS_CONSULTA)

    for i, camada in enumerate(CAMADAS_CONSULTA, 1):
        type_name = camada['typeName']
        rotulo    = camada['rotulo']
        grupo     = camada['grupo']
        nome      = type_name.split(':')[-1]

        if callback:
            callback(f'[{i}/{total}] {rotulo}...')

        try:
            geojson  = _wfs_urllib(SICAR_CONSULTA_WFS_URL, type_name, '2.0.0', codigo_car)
            features = geojson.get('features', [])
            if features:
                resultados.append({'nome': nome, 'rotulo': rotulo, 'geojson': geojson, 'grupo': grupo})
        except Exception as exc:
            logger.warning('Camada %s: %s', type_name, exc)

    return resultados


def carregar_no_qgis(resultados: list) -> list:
    """Carrega resultados como camadas no projeto QGIS.

    DEVE ser chamado na thread PRINCIPAL.

    Args:
        resultados: Lista de dicts com 'path' (shapefile) ou 'geojson'.

    Returns:
        Lista de nomes das camadas adicionadas.
    """
    from qgis.core import QgsVectorLayer, QgsProject

    nomes = []
    for item in resultados:
        rotulo = item.get('rotulo', item.get('nome', 'CAR'))
        path   = item.get('path', '')
        geojson = item.get('geojson')

        if path and os.path.isfile(path):
            layer = QgsVectorLayer(path, f'CAR_{rotulo}', 'ogr')
        elif geojson and geojson.get('features'):
            tmp = tempfile.NamedTemporaryFile(
                mode='w', suffix='.geojson',
                prefix=f'lyssa_sicar_{item.get("nome","layer")}_',
                delete=False, encoding='utf-8',
            )
            json.dump(geojson, tmp, ensure_ascii=False)
            tmp.close()
            layer = QgsVectorLayer(tmp.name, f'CAR_{rotulo}', 'ogr')
        else:
            continue

        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            nomes.append(f'CAR_{rotulo}')

    return nomes


# ===========================================================================
# Internos
# ===========================================================================

def _wfs_urllib(url, type_name, version, codigo_car):
    """Faz requisição WFS com urllib e SSL permissivo."""
    car_safe   = codigo_car.replace("'", "''")
    type_param = 'typenames' if version.startswith('2.') else 'typeName'

    params = {
        'service':       'WFS',
        'version':       version,
        'request':       'GetFeature',
        type_param:      type_name,
        'outputFormat':  'application/json',
        'srsName':       'EPSG:4326',
        'CQL_FILTER':    f"cod_imovel='{car_safe}'",
    }
    full_url = f'{url}?{urllib.parse.urlencode(params)}'
    raw      = _http_get(full_url)

    if raw.lstrip().startswith('<'):
        raise ValueError(f'XML inesperado para {type_name}')
    return json.loads(raw)


def _http_get(url: str) -> str:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    try:
        ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
    except Exception:
        pass

    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (QGIS LyssaPlugin/1.0)',
            'Accept':     'application/json, */*',
        }
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
        return resp.read().decode('utf-8')


def _extrair_uf(codigo_car: str):
    m = re.match(r'^([A-Z]{2})-\d{7}-', codigo_car)
    return m.group(1).lower() if m else None
