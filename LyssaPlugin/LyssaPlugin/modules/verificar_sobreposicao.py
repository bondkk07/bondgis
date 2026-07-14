"""
Verificação de sobreposição geométrica – equivalente ao VerificarSobreposicao.jsx
do WebGIS LiroGis.

Arquitetura thread-safe: este módulo usa apenas osgeo.ogr para geometria,
sem chamar APIs do PyQGIS (evita crashes em QThread).
As funções de preparação (preparar_geom_imovel, preparar_camada_local)
devem ser chamadas na thread principal antes de iniciar o worker.
"""

import json
import logging
import re
import ssl
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_TIMEOUT = 60  # segundos por requisição HTTP

# ---------------------------------------------------------------------------
# Listas MCR / PRODES MMA – 6 biomas
# ---------------------------------------------------------------------------
LISTAS_PRODES_MMA = [
    {"bioma": "Amazônia",
     "url": "https://labdez.mma.gov.br/server/rest/services/Hosted/lista_mcr_amazonia_VF/FeatureServer/0/query"},
    {"bioma": "Mata Atlântica",
     "url": "https://labdez.mma.gov.br/server/rest/services/Hosted/lista_mcr_mata_atlantica_VF/FeatureServer/0/query"},
    {"bioma": "Cerrado",
     "url": "https://labdez.mma.gov.br/server/rest/services/Hosted/lista_mcr_cerrado_VF/FeatureServer/0/query"},
    {"bioma": "Caatinga",
     "url": "https://labdez.mma.gov.br/server/rest/services/Hosted/lista_mcr_caatinga_VF/FeatureServer/0/query"},
    {"bioma": "Pantanal",
     "url": "https://labdez.mma.gov.br/server/rest/services/Hosted/lista_mcr_pantanal_VF/FeatureServer/0/query"},
    {"bioma": "Pampa",
     "url": "https://labdez.mma.gov.br/server/rest/services/Hosted/lista_mcr_pampa_VF/FeatureServer/0/query"},
]

_CAMPOS_PRODES_MMA = [
    "cod_imovel", "uf", "municipio", "area_total_ha", "soma_desmat",
    "dentro_criterio", "criterio_aplicado", "resultados",
    "sobrep_prodes_2019", "sobrep_prodes_2020", "sobrep_prodes_2021",
    "sobrep_prodes_2022", "sobrep_prodes_2023", "sobrep_prodes_2024",
    "sobrep_prodes_2025",
]


# ---------------------------------------------------------------------------
# Ponto de entrada principal
# ---------------------------------------------------------------------------
def verificar_sobreposicao(
    imovel_wkt: str,
    bbox: list,
    codigo_car: str,
    camadas_externas: list,
    camadas_locais: list,
    callback=None,
) -> list:
    """Verifica sobreposição do imóvel com camadas externas e locais.

    Args:
        imovel_wkt:       WKT da geometria unida do imóvel em EPSG:4326.
        bbox:             [xmin, ymin, xmax, ymax] em EPSG:4326 (com buffer).
        codigo_car:       Código CAR do imóvel (ex: "RO-1100015-...").
        camadas_externas: Lista de dicts do catálogo (tipo wfs/arcgis).
        camadas_locais:   Lista de {'nome': str, 'wkts': [str]}.
        callback:         callable(pct: int, msg: str) para progresso.

    Returns:
        Lista de dicts com chaves:
          camada, sobreposicao, erroConsulta, statusTexto, detalhes, count
    """
    from osgeo import ogr

    geom_imovel = ogr.CreateGeometryFromWkt(imovel_wkt)
    resultados  = []
    total       = len(camadas_externas) + len(camadas_locais) + 1  # +1 para PRODES MMA

    for i, info in enumerate(camadas_externas, 1):
        titulo = info.get('titulo', f'Camada {i}')
        _progresso(callback, int(i / total * 80), f'[{i}/{total}] {titulo}')
        resultados.append(_verificar_externa(info, geom_imovel, bbox))

    base = len(camadas_externas)
    for i, local in enumerate(camadas_locais, 1):
        _progresso(callback, int((base + i) / total * 80), f'Local: {local["nome"]}')
        resultados.append(_verificar_local(local, geom_imovel))

    _progresso(callback, 88, 'Consultando Listas MCR/PRODES MMA...')
    resultados.append(_consultar_prodes_mma(codigo_car))

    _progresso(callback, 100, 'Verificação concluída.')
    return resultados


# ---------------------------------------------------------------------------
# Verificação de camada externa (WFS / ArcGIS)
# ---------------------------------------------------------------------------
def _verificar_externa(info, geom_imovel, bbox):
    titulo = info.get('titulo', 'Desconhecida')
    tipo   = info.get('tipo', 'wfs')
    try:
        data     = _get_wfs(info, bbox) if tipo == 'wfs' else _get_arcgis(info, bbox)
        features = (data or {}).get('features', [])

        # Pré-filtro de atributo (ex: categoria EMBRAPA) – antes da interseção
        attr_f = info.get('attr_filter')
        if attr_f:
            features = [f for f in features if _match_attr(f, attr_f)]

        sobrep = [f for f in features if _intersecta(geom_imovel, f)]

        # Pós-filtro de atributo (ex: year PRODES >= 2019) – depois da interseção
        sobrep_f = info.get('sobrep_filter')
        if sobrep_f:
            sobrep = [f for f in sobrep if _match_attr(f, sobrep_f)]
        return {
            'camada':       titulo,
            'sobreposicao': bool(sobrep),
            'erroConsulta': False,
            'statusTexto':  'Consta' if sobrep else 'Não consta',
            'detalhes':    _extrair_detalhes(info, sobrep),
            'count':        len(sobrep),
        }
    except Exception as exc:
        logger.warning('Sobreposição %s: %s', titulo, exc)
        return {
            'camada':       titulo,
            'sobreposicao': False,
            'erroConsulta': True,
            'statusTexto':  'Não verificada',
            'detalhes':    [f'Erro: {exc}'],
            'count':        0,
        }


# ---------------------------------------------------------------------------
# Filtro de atributo client-side
# ---------------------------------------------------------------------------
def _match_attr(feature, attr_f):
    """Retorna True se o feature passa pelo filtro de atributo configurado.

    Suporta:
      campo  (str)  – campo único
      campos (list) – lista de candidatos; usa o primeiro encontrado
      op: eq (padrão) | gte | gt | lte | lt
      Para operadores numéricos, extrai ano de strings de data ("2024-01-01")
      usando regex quando float() falha.
    """
    props = feature.get('properties') or {}
    op    = attr_f.get('op', 'eq')

    # Resolve o valor bruto tentando a lista de campos
    candidates = attr_f.get('campos') or [attr_f.get('campo')]
    raw = None
    for c in (candidates or []):
        if c and c in props:
            raw = props[c]
            break

    if op == 'eq':
        return str(raw).lower() == str(attr_f['valor']).lower()

    # Operadores numéricos ─────────────────────────────────────────────────
    n = float(attr_f['valor'])

    # Tenta parse direto; se falhar, extrai ano com regex (ex: "2024-01-01")
    try:
        v = float(raw)
    except (TypeError, ValueError):
        m = re.search(r'\b(19|20)\d{2}\b', str(raw or ''))
        if not m:
            return False   # campo ausente ou não interpretável → descarta
        v = float(m.group(0))

    if op == 'gte': return v >= n
    if op == 'gt':  return v > n
    if op == 'lte': return v <= n
    if op == 'lt':  return v < n
    return True


# ---------------------------------------------------------------------------
# Verificação de camada local (já em EPSG:4326 como WKT)
# ---------------------------------------------------------------------------
def _verificar_local(local, geom_imovel):
    nome = local['nome']
    try:
        count = sum(1 for wkt in local['wkts'] if wkt and _intersecta_wkt(geom_imovel, wkt))
        return {
            'camada':       nome,
            'sobreposicao': count > 0,
            'erroConsulta': False,
            'statusTexto':  'Consta' if count > 0 else 'Não consta',
            'detalhes':    [],
            'count':        count,
        }
    except Exception as exc:
        logger.warning('Verificar local %s: %s', nome, exc)
        return {
            'camada':       nome,
            'sobreposicao': False,
            'erroConsulta': True,
            'statusTexto':  'Não verificada',
            'detalhes':    [f'Erro: {exc}'],
            'count':        0,
        }


# ---------------------------------------------------------------------------
# Interseção geométrica via OGR (thread-safe, sem PyQGIS)
# ---------------------------------------------------------------------------
def _intersecta(geom_imovel, feature):
    try:
        geom_dict = feature.get('geometry')
        if not geom_dict:
            return False
        return _intersecta_wkt(geom_imovel, _wkt_from_geojson(geom_dict))
    except Exception:
        return False


def _intersecta_wkt(geom_imovel, wkt):
    from osgeo import ogr
    if not wkt or geom_imovel is None:
        return False
    try:
        g = ogr.CreateGeometryFromWkt(wkt)
        if g is None:
            return False
        if not geom_imovel.Intersects(g):
            return False
        inter = geom_imovel.Intersection(g)
        if inter is None or inter.IsEmpty():
            return False
        # Polygon / MultiPolygon: exige área mínima de 1 m² ≈ 1e-10 graus²
        if inter.GetGeometryType() in (3, 6):
            return inter.GetArea() > 1e-10
        return True
    except Exception:
        return False


def _wkt_from_geojson(geom_dict):
    from osgeo import ogr
    try:
        g = ogr.CreateGeometryFromJson(json.dumps(geom_dict))
        return g.ExportToWkt() if g else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Requisições HTTP – WFS e ArcGIS Feature Server
# ---------------------------------------------------------------------------
def _get_wfs(info, bbox):
    url       = info['url']
    type_name = info.get('type_name', '')
    version   = info.get('version', '2.0.0')
    extra     = dict(info.get('params', {}))

    type_param = 'typenames' if version.startswith('2.') else 'typeName'

    params = {
        'service':      'WFS',
        'version':      version,
        'request':      'GetFeature',
        type_param:     type_name,
        'outputFormat': 'application/json',
        'srsName':      'EPSG:4326',
        'bbox':         f'{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]},EPSG:4326',
    }
    params.update(extra)
    return _fetch_json(f'{url}?{urllib.parse.urlencode(params)}')


def _get_arcgis(info, bbox):
    url   = info.get('url', '')
    extra = dict(info.get('params', {}))

    envelope = json.dumps({
        'xmin': bbox[0], 'ymin': bbox[1],
        'xmax': bbox[2], 'ymax': bbox[3],
        'spatialReference': {'wkid': 4326},
    })

    params = {
        'where':          extra.pop('where', '1=1'),
        'returnGeometry': 'true',
        'outFields':      '*',
        'f':              'geojson',
        'geometryType':   'esriGeometryEnvelope',
        'geometry':       envelope,
        'inSR':           '4326',
        'outSR':          '4326',
        'spatialRel':     'esriSpatialRelIntersects',
    }
    params.update(extra)
    return _fetch_json(f'{url}?{urllib.parse.urlencode(params)}')


def _fetch_json(url):
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
        raw = resp.read().decode('utf-8')
    if raw.lstrip().startswith('<'):
        raise ValueError('Servidor retornou XML; verifique a URL/typeName.')
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Extração de detalhes contextuais por tipo de camada
# ---------------------------------------------------------------------------
def _extrair_detalhes(info, features_sobrep):
    if not features_sobrep:
        return []

    titulo_up = info.get('titulo', '').upper()

    if 'PRODES' in titulo_up:
        anos = set()
        for f in features_sobrep:
            props = f.get('properties', {}) or {}
            for campo in ('year', 'YEAR', 'ano', 'ANO', 'year_deforestation'):
                v = props.get(campo)
                if v:
                    m = re.search(r'\b(19|20)\d{2}\b', str(v))
                    if m:
                        anos.add(m.group(0))
        return ([f'Ano(s) de desmatamento: {", ".join(sorted(anos))}']
                if anos else [f'{len(features_sobrep)} polígono(s) sobrepostos.'])

    if 'ZSEE' in titulo_up:
        subzonas = set()
        for f in features_sobrep:
            props = f.get('properties', {}) or {}
            sub   = props.get('SUBZONA') or props.get('subzona', '')
            if sub:
                subzonas.add(str(sub).strip())
        return [f'Subzona(s): {", ".join(sorted(subzonas))}'] if subzonas else []

    if any(x in titulo_up for x in ('ASSENTAMENTO', 'QUILOMBOLA')):
        nomes = []
        for f in features_sobrep[:5]:
            props = f.get('properties', {}) or {}
            for campo in ('nome', 'NOME', 'name', 'Name'):
                v = props.get(campo)
                if v:
                    nomes.append(str(v).strip())
                    break
        return list(dict.fromkeys(nomes))  # deduplica preservando ordem

    return [f'{len(features_sobrep)} feição(ões) sobrepost(as).']


# ---------------------------------------------------------------------------
# Consulta às Listas MCR / PRODES MMA por código CAR
# ---------------------------------------------------------------------------
def _consultar_prodes_mma(codigo_car):
    if not codigo_car:
        return {
            'camada':       'Listas MCR/PRODES MMA',
            'sobreposicao': False,
            'erroConsulta': True,
            'statusTexto':  'Não verificada',
            'detalhes':    ['Código CAR não disponível para consulta.'],
            'count':        0,
        }

    encontrados = []
    falhas      = []

    for lista in LISTAS_PRODES_MMA:
        try:
            car_safe = codigo_car.replace("'", "''")
            params   = {
                'where':             f"cod_imovel='{car_safe}'",
                'outFields':         ','.join(_CAMPOS_PRODES_MMA),
                'returnGeometry':    'false',
                'resultRecordCount': '10',
                'f':                 'json',
            }
            data = _fetch_json(f"{lista['url']}?{urllib.parse.urlencode(params)}")
            for feat in data.get('features', []):
                attrs = feat.get('attributes', feat.get('properties', {}))
                encontrados.append({'bioma': lista['bioma'], 'attrs': attrs})
        except Exception as exc:
            logger.warning('Lista PRODES MMA %s: %s', lista['bioma'], exc)
            falhas.append(lista['bioma'])

    if encontrados:
        detalhes = []
        for item in encontrados:
            a      = item['attrs']
            partes = [f'Bioma: {item["bioma"]}']
            if a.get('municipio'):
                partes.append(f'Município: {a["municipio"]}')
            if a.get('uf'):
                partes.append(f'UF: {a["uf"]}')
            soma = a.get('soma_desmat')
            if soma is not None:
                partes.append(f'Desmatamento acumulado: {float(soma):.2f} ha')
            anos_sobrep = [
                f'{c.replace("sobrep_prodes_", "")}: {float(a[c]):.2f} ha'
                for c in _CAMPOS_PRODES_MMA
                if c.startswith('sobrep_prodes_') and a.get(c) and float(a[c]) > 0
            ]
            if anos_sobrep:
                partes.append('PRODES por ano — ' + ', '.join(anos_sobrep))
            if a.get('resultados'):
                partes.append(f'Resultado: {a["resultados"]}')
            detalhes.append(' | '.join(partes))

        return {
            'camada':       'Listas MCR/PRODES MMA',
            'sobreposicao': True,
            'erroConsulta': False,
            'statusTexto':  'Consta',
            'detalhes':    detalhes,
            'count':        len(encontrados),
        }

    todas_falharam = len(falhas) == len(LISTAS_PRODES_MMA)
    return {
        'camada':       'Listas MCR/PRODES MMA',
        'sobreposicao': False,
        'erroConsulta': todas_falharam,
        'statusTexto':  'Não verificada' if todas_falharam else 'Não consta',
        'detalhes':    (
            [f'Falha ao consultar: {", ".join(falhas)}']
            if todas_falharam
            else ['CAR não localizado nas listas MCR/PRODES MMA.']
            + ([f'Falha parcial em: {", ".join(falhas)}'] if falhas else [])
        ),
        'count': 0,
    }


# ---------------------------------------------------------------------------
# Utilitários para extração de dados na thread principal (com PyQGIS)
# ---------------------------------------------------------------------------
def preparar_geom_imovel(imovel_layer):
    """Retorna (wkt_4326, bbox_4326) para passar ao worker.

    Deve ser chamado na thread principal do QGIS.
    """
    from qgis.core import (
        QgsGeometry, QgsCoordinateTransform,
        QgsCoordinateReferenceSystem, QgsProject,
    )

    geoms = [
        f.geometry()
        for f in imovel_layer.getFeatures()
        if f.geometry() and not f.geometry().isEmpty()
    ]
    if not geoms:
        return None, None

    union    = QgsGeometry.unaryUnion(geoms)
    crs_src  = imovel_layer.crs()
    crs_4326 = QgsCoordinateReferenceSystem('EPSG:4326')

    if crs_src != crs_4326:
        t = QgsCoordinateTransform(crs_src, crs_4326, QgsProject.instance())
        union.transform(t)

    ext  = union.boundingBox()
    buf  = 0.012  # ~1.3 km
    bbox = [
        ext.xMinimum() - buf,
        ext.yMinimum() - buf,
        ext.xMaximum() + buf,
        ext.yMaximum() + buf,
    ]
    return union.asWkt(), bbox


def preparar_camada_local(layer):
    """Extrai WKTs em EPSG:4326 de uma camada local QGIS.

    Deve ser chamado na thread principal do QGIS.
    """
    from qgis.core import (
        QgsCoordinateTransform,
        QgsCoordinateReferenceSystem, QgsProject,
    )

    crs_src  = layer.crs()
    crs_4326 = QgsCoordinateReferenceSystem('EPSG:4326')
    has_tr   = (crs_src != crs_4326)
    t = QgsCoordinateTransform(crs_src, crs_4326, QgsProject.instance()) if has_tr else None

    wkts = []
    for feat in layer.getFeatures():
        g = feat.geometry()
        if not g or g.isEmpty():
            continue
        if has_tr:
            g.transform(t)
        wkts.append(g.asWkt())

    return {'nome': layer.name(), 'wkts': wkts}


def obter_codigo_car(imovel_layer) -> str:
    """Extrai o código CAR do primeiro feature da camada do imóvel."""
    campos_car = [
        'cod_imovel', 'COD_IMOVEL', 'codImovel',
        'inscricao', 'INSCRICAO', 'inscricaocar',
        'codigo', 'CODIGO', 'car', 'CAR',
    ]
    for feat in imovel_layer.getFeatures():
        nomes = feat.fields().names()
        for campo in campos_car:
            if campo in nomes:
                val = feat[campo]
                if val and str(val).strip():
                    return str(val).strip().upper()
        break
    return ''


def _progresso(callback, pct, msg):
    if callback:
        try:
            callback(pct, msg)
        except Exception:
            pass
