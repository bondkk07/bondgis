import logging

import processing
from qgis.core import QgsVectorLayer, QgsProject, QgsDistanceArea

logger = logging.getLogger(__name__)


def calcular_area_beneficiavel(
    imovel_layer: QgsVectorLayer,
    camadas_restritivas: list,
    estado: str = '',
    apf_layer: QgsVectorLayer = None,
) -> QgsVectorLayer:
    """Calcula a área beneficiável subtraindo camadas restritivas do imóvel.

    Replica a lógica do backend WebGIS (diferenca.py):
      1. fix_geometry em todas as camadas antes de operar
      2. dissolve + diferença com fallback
      3. Para MT: intersecta com APF

    Returns:
        QgsVectorLayer (memory) com a área beneficiável, já adicionada ao projeto.
    """
    resultado = _fix_geometrias(imovel_layer)
    if resultado is None:
        logger.warning('Geometria do imóvel inválida e não recuperável.')
        return None

    if camadas_restritivas:
        restritivas_fixadas = [l for l in (_fix_geometrias(l) for l in camadas_restritivas) if l]
        if restritivas_fixadas:
            uniao = _unir_camadas(restritivas_fixadas)
            resultado = _diferenca(resultado, uniao)
            if resultado is None:
                return None

    if estado.upper() == 'MT' and apf_layer:
        apf_fixada = _fix_geometrias(apf_layer)
        if apf_fixada:
            resultado = _intersecao(resultado, apf_fixada)
            if resultado is None:
                return None

    resultado.setName('Área Beneficiável')
    QgsProject.instance().addMapLayer(resultado)
    return resultado


def calcular_area_ha(layer: QgsVectorLayer) -> float:
    """Área total do layer em hectares (usa elipsoide WGS-84)."""
    da = QgsDistanceArea()
    da.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
    da.setEllipsoid('WGS84')

    total_m2 = 0.0
    for feat in layer.getFeatures():
        geom = feat.geometry()
        if geom and not geom.isEmpty():
            total_m2 += da.measureArea(geom)
    return round(total_m2 / 10_000, 4)


# ---------------------------------------------------------------------------
# Funções internas
# ---------------------------------------------------------------------------

def _fix_geometrias(layer: QgsVectorLayer) -> QgsVectorLayer:
    """Corrige geometrias inválidas usando native:fixgeometries.

    Equivalente ao fix_geometry() + make_valid() + buffer(0) do backend WebGIS.
    Retorna None se a camada ainda estiver inválida após a correção.
    """
    try:
        result = processing.run('native:fixgeometries', {
            'INPUT':  layer,
            'OUTPUT': 'memory:fix_geom',
        })
        fixed = result.get('OUTPUT')
        if fixed and fixed.isValid():
            return fixed
    except Exception as exc:
        logger.warning('fixgeometries falhou para %s: %s', layer.name(), exc)
    return layer   # retorna original como fallback


def _unir_camadas(camadas: list) -> QgsVectorLayer:
    if len(camadas) == 1:
        return camadas[0]

    merged = processing.run('native:mergevectorlayers', {
        'LAYERS': camadas,
        'OUTPUT': 'memory:uniao_restritivas',
    })['OUTPUT']

    dissolved = processing.run('native:dissolve', {
        'INPUT':  merged,
        'FIELD':  [],
        'OUTPUT': 'memory:dissolve_restritivas',
    })['OUTPUT']

    return dissolved


def _diferenca(base: QgsVectorLayer, overlay: QgsVectorLayer) -> QgsVectorLayer:
    """Diferença com fallback: se falhar, aplica fixgeometries extra e tenta novamente."""
    try:
        result = processing.run('native:difference', {
            'INPUT':   base,
            'OVERLAY': overlay,
            'OUTPUT':  'memory:diferenca',
        })
        layer = result.get('OUTPUT')
        if layer and layer.featureCount() > 0:
            return layer
    except Exception as exc:
        logger.warning('native:difference falhou, tentando com geometrias corrigidas: %s', exc)
        try:
            base2    = _fix_geometrias(base)
            overlay2 = _fix_geometrias(overlay)
            result   = processing.run('native:difference', {
                'INPUT':   base2,
                'OVERLAY': overlay2,
                'OUTPUT':  'memory:diferenca_retry',
            })
            layer = result.get('OUTPUT')
            if layer and layer.featureCount() > 0:
                return layer
        except Exception as exc2:
            logger.error('native:difference falhou na segunda tentativa: %s', exc2)
    return None


def _intersecao(base: QgsVectorLayer, overlay: QgsVectorLayer) -> QgsVectorLayer:
    """Intersecção com fallback equivalente ao _diferenca."""
    try:
        result = processing.run('native:intersection', {
            'INPUT':   base,
            'OVERLAY': overlay,
            'OUTPUT':  'memory:intersecao',
        })
        layer = result.get('OUTPUT')
        if layer and layer.featureCount() > 0:
            return layer
    except Exception as exc:
        logger.warning('native:intersection falhou, tentando com geometrias corrigidas: %s', exc)
        try:
            base2    = _fix_geometrias(base)
            overlay2 = _fix_geometrias(overlay)
            result   = processing.run('native:intersection', {
                'INPUT':   base2,
                'OVERLAY': overlay2,
                'OUTPUT':  'memory:intersecao_retry',
            })
            layer = result.get('OUTPUT')
            if layer and layer.featureCount() > 0:
                return layer
        except Exception as exc2:
            logger.error('native:intersection falhou na segunda tentativa: %s', exc2)
    return None
