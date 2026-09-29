"""Análise de cobertura/uso do solo via COGs públicos do MapBiomas.

Lê os arquivos GeoTIFF (COG) do bucket público do Google Cloud Storage
usando GDAL VSICURL — sem armazenamento local de raster.

Fonte: MapBiomas Brasil Coleção 10.1 (1985–2024)
URL:   gs://mapbiomas-public/initiatives/brasil/collection_10/lulc/coverage/
"""
import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

COG_URL_LULC = (
    "https://storage.googleapis.com/mapbiomas-public"
    "/initiatives/brasil/collection_10/lulc/coverage"
    "/brazil_coverage_{ano}.tif"
)

ANO_MINIMO = 1985
ANO_MAXIMO = 2024
PIXEL_AREA_HA_30M = 0.09  # 30 m × 30 m = 900 m² = 0,09 ha


def analisar_cobertura(geom_wkt: str, anos: List[int]) -> Dict[str, Any]:
    """Analisa cobertura do solo para uma geometria e lista de anos.

    Args:
        geom_wkt: Geometria em WKT (EPSG:4326).
        anos:     Lista de anos inteiros (1985–2024).

    Returns:
        Dict com chaves 'lulc' (resultados por ano) e 'meta'.
    """
    try:
        from osgeo import gdal, ogr, osr
        import numpy as np
    except ImportError as exc:
        raise ImportError(
            "GDAL e/ou NumPy não encontrado no ambiente Python do QGIS."
        ) from exc

    from .mapbiomas_classes import CLASSES_LULC

    gdal.UseExceptions()
    gdal.SetConfigOption('GDAL_DISABLE_READDIR_ON_OPEN', 'EMPTY_LIST')
    gdal.SetConfigOption('CPL_VSIL_CURL_ALLOWED_EXTENSIONS', '.tif')
    gdal.SetConfigOption('VSI_CACHE', 'TRUE')
    gdal.SetConfigOption('VSI_CACHE_SIZE', '10000000')
    gdal.SetConfigOption('GDAL_HTTP_CONNECTTIMEOUT', '30')
    gdal.SetConfigOption('GDAL_HTTP_TIMEOUT', '90')

    anos_validos = [int(a) for a in anos if ANO_MINIMO <= int(a) <= ANO_MAXIMO]
    if not anos_validos:
        raise ValueError(f"Nenhum ano válido. Intervalo permitido: {ANO_MINIMO}–{ANO_MAXIMO}.")

    area_total_ha = _area_geodesica_ha(geom_wkt)
    resultados = {}

    for ano in sorted(anos_validos):
        url = COG_URL_LULC.format(ano=ano)
        try:
            contagem, pixel_ha = _contar_pixels(geom_wkt, url)
            if contagem:
                resultados[str(ano)] = _montar_resultado(contagem, pixel_ha, CLASSES_LULC)
            else:
                resultados[str(ano)] = {"aviso": "Nenhum pixel encontrado na geometria."}
        except Exception as exc:
            logger.warning("MapBiomas erro ano=%d: %s", ano, exc)
            resultados[str(ano)] = {"erro": str(exc)}

    return {
        "lulc": resultados,
        "meta": {
            "area_total_ha": area_total_ha,
            "anos": sorted(anos_validos),
            "resolucao_m": 30,
        },
    }


def _contar_pixels(geom_wkt: str, url: str):
    from osgeo import gdal, ogr, osr
    import numpy as np

    vsicurl = f"/vsicurl/{url}"
    ds = gdal.Open(vsicurl)
    if ds is None:
        raise RuntimeError(f"Não foi possível abrir o COG: {url}")

    try:
        gt = ds.GetGeoTransform()
        proj_wkt = ds.GetProjection()

        src_srs = osr.SpatialReference()
        src_srs.ImportFromEPSG(4326)

        dst_srs = osr.SpatialReference()
        dst_srs.ImportFromWkt(proj_wkt)

        geom = ogr.CreateGeometryFromWkt(geom_wkt)
        if geom is None:
            raise ValueError("Geometria WKT inválida.")

        transform = osr.CoordinateTransformation(src_srs, dst_srs)
        geom.Transform(transform)

        env = geom.GetEnvelope()  # (minX, maxX, minY, maxY)
        x_min, x_max, y_min, y_max = env

        px0 = int((x_min - gt[0]) / gt[1])
        px1 = int((x_max - gt[0]) / gt[1]) + 1
        py0 = int((y_max - gt[3]) / gt[5])
        py1 = int((y_min - gt[3]) / gt[5]) + 1

        px0 = max(0, px0)
        py0 = max(0, py0)
        px1 = min(ds.RasterXSize, px1)
        py1 = min(ds.RasterYSize, py1)

        if px1 <= px0 or py1 <= py0:
            return {}, PIXEL_AREA_HA_30M

        band = ds.GetRasterBand(1)
        data = band.ReadAsArray(px0, py0, px1 - px0, py1 - py0)
        if data is None:
            return {}, PIXEL_AREA_HA_30M

        mask = data > 0
        if not mask.any():
            return {}, PIXEL_AREA_HA_30M

        pixel_ha = (
            PIXEL_AREA_HA_30M
            if dst_srs.IsGeographic()
            else abs(gt[1] * gt[5]) / 10_000
        )

        valores, contagens = np.unique(data[mask], return_counts=True)
        return {int(v): int(c) for v, c in zip(valores, contagens)}, pixel_ha

    finally:
        ds = None


def _montar_resultado(contagem: dict, pixel_ha: float, classes: dict) -> dict:
    total_ha = sum(n * pixel_ha for n in contagem.values())
    resultado = {}
    for codigo, n_pixels in sorted(contagem.items()):
        info = classes.get(codigo)
        nome = info["nome"] if info else f"Classe {codigo}"
        cor  = info["cor"]  if info else "#aaaaaa"
        ha   = n_pixels * pixel_ha
        pct  = (ha / total_ha * 100) if total_ha > 0 else 0.0
        resultado[nome] = {
            "ha":     round(ha, 2),
            "pct":    round(pct, 2),
            "pixels": n_pixels,
            "cor":    cor,
            "codigo": codigo,
        }
    return resultado


def _area_geodesica_ha(geom_wkt: str) -> float:
    try:
        from osgeo import ogr
        geom = ogr.CreateGeometryFromWkt(geom_wkt)
        if geom is None:
            return 0.0

        # Projetar para Albers Brasil (EPSG:5641) para área mais precisa
        from osgeo import osr
        src = osr.SpatialReference()
        src.ImportFromEPSG(4326)
        dst = osr.SpatialReference()
        dst.ImportFromEPSG(5641)
        t = osr.CoordinateTransformation(src, dst)
        geom_proj = geom.Clone()
        geom_proj.Transform(t)
        area_m2 = abs(geom_proj.GetArea())
        return round(area_m2 / 10_000, 2)
    except Exception:
        return 0.0
