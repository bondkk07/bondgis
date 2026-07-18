"""Processamento Sentinel-2 no Google Earth Engine.

Implementa: mÃ¡scara de nuvens, composiÃ§Ãµes (recente/mediana), bandas
B2â€“B12, Ã­ndices espectrais (NDVI, NDRE, NDWI, NDMI, BSI, NBR), classificaÃ§Ã£o
automÃ¡tica baseada em regras e estatÃ­sticas por classe recortadas pela AOI.

Todas as funÃ§Ãµes assumem que ee.Initialize jÃ¡ foi chamado (earth_engine.py).
"""
from typing import Any, Dict, List, Optional, Tuple

import ee

from config import get_settings

# â”€â”€ Bandas Sentinel-2 usadas (nomes na coleÃ§Ã£o S2_SR_HARMONIZED) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# B2 Blue, B3 Green, B4 Red, B5/B6/B7 RedEdge, B8 NIR, B11 SWIR1, B12 SWIR2
S2_BANDS = ["B2", "B3", "B4", "B5", "B6", "B7", "B8", "B11", "B12"]

# â”€â”€ Paletas de visualizaÃ§Ã£o por Ã­ndice â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
PALETTE_NDVI = ["#a50026", "#d73027", "#f46d43", "#fdae61", "#fee08b",
                "#d9ef8b", "#a6d96a", "#66bd63", "#1a9850", "#006837"]
PALETTE_WATER = ["#ffffcc", "#a1dab4", "#41b6c4", "#2c7fb8", "#253494"]
PALETTE_MOIST = ["#8c510a", "#d8b365", "#f6e8c3", "#c7eae5", "#5ab4ac", "#01665e"]
PALETTE_SOIL = ["#004529", "#78c679", "#ffffe5", "#fe9929", "#993404"]
PALETTE_BURN = ["#000000", "#7f0000", "#d7301f", "#fc8d59", "#fdcc8a", "#fef0d9"]

# â”€â”€ ClassificaÃ§Ã£o automÃ¡tica (cÃ³digo â†’ nome, cor) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# ClassificaÃ§Ã£o ÃšNICA do sistema (usada por tiles, anÃ¡lises e auditoria).
# Antes existiam dois classificadores quase idÃªnticos (sentinel.classify e
# auditoria.classify_audit) â€” foram unificados neste.
CLASSES: Dict[int, Tuple[str, str]] = {
    1: ("Ãgua", "#2c7fb8"),
    2: ("Ãrea Ãšmida", "#41b6c4"),
    3: ("Solo Exposto", "#a6611a"),
    4: ("Agricultura", "#fdae61"),
    5: ("Pastagem", "#addd8e"),
    6: ("VegetaÃ§Ã£o SecundÃ¡ria", "#78c679"),
    7: ("Floresta", "#006837"),
    8: ("Ãrea Queimada", "#7f0000"),
    9: ("Infraestrutura", "#969696"),
}
CLASS_PALETTE = [CLASSES[i][1] for i in sorted(CLASSES)]


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  AOI, coleÃ§Ã£o e mÃ¡scara de nuvens
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def geometry_from_geojson(aoi: Dict[str, Any]) -> ee.Geometry:
    """Aceita Geometry, Feature ou FeatureCollection GeoJSON e devolve uma
    Ãºnica ee.Geometry (dissolvida)."""
    t = aoi.get("type")
    if t == "FeatureCollection":
        feats = [ee.Feature(f["geometry"]) for f in aoi.get("features", []) if f.get("geometry")]
        if not feats:
            raise ValueError("FeatureCollection sem geometrias.")
        return ee.FeatureCollection(feats).geometry()
    if t == "Feature":
        if not aoi.get("geometry"):
            raise ValueError("Feature sem geometria.")
        return ee.Geometry(aoi["geometry"])
    if t in ("Polygon", "MultiPolygon", "GeometryCollection"):
        return ee.Geometry(aoi)
    raise ValueError(f"GeoJSON nÃ£o suportado: {t!r}")


def _mask_s2_sr(img: ee.Image) -> ee.Image:
    """MÃ¡scara de nuvens/sombra usando a banda SCL (Scene Classification).
    Remove: 3 sombra, 8 nuvem mÃ©dia, 9 nuvem alta, 10 cirrus, 11 neve."""
    scl = img.select("SCL")
    mask = (scl.neq(3).And(scl.neq(8)).And(scl.neq(9))
            .And(scl.neq(10)).And(scl.neq(11)))
    # ReflectÃ¢ncia SR vem em escala 0â€“10000.
    scaled = img.select(S2_BANDS).divide(10000)
    return scaled.updateMask(mask).copyProperties(img, ["system:time_start", "CLOUDY_PIXEL_PERCENTAGE"])


def build_collection(aoi: ee.Geometry, date_start: str, date_end: str,
                     max_cloud: float) -> ee.ImageCollection:
    s = get_settings()
    return (ee.ImageCollection(s.s2_collection)
            .filterBounds(aoi)
            .filterDate(date_start, date_end)
            .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", max_cloud))
            .map(_mask_s2_sr))


def composite(coll: ee.ImageCollection, mode: str) -> ee.Image:
    """Reduz a coleÃ§Ã£o a uma imagem. 'recent' = imagem mais recente com
    prioridade (mosaic sobre coleÃ§Ã£o ordenada); 'median' = mediana."""
    if mode == "median":
        return coll.median()
    # recent: ordena por data crescente e faz mosaic â†’ pixels mais recentes no topo
    return coll.sort("system:time_start").mosaic()


def latest_date(coll: ee.ImageCollection) -> Optional[str]:
    try:
        n = coll.size().getInfo()
        if not n:
            return None
        img = ee.Image(coll.sort("system:time_start", False).first())
        millis = img.get("system:time_start").getInfo()
        if millis is None:
            return None
        return ee.Date(millis).format("YYYY-MM-dd").getInfo()
    except Exception:
        return None


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  Ãndices espectrais
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def add_indices(img: ee.Image) -> ee.Image:
    ndvi = img.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndre = img.normalizedDifference(["B8", "B5"]).rename("NDRE")
    ndwi = img.normalizedDifference(["B3", "B8"]).rename("NDWI")
    ndmi = img.normalizedDifference(["B8", "B11"]).rename("NDMI")
    nbr = img.normalizedDifference(["B8", "B12"]).rename("NBR")
    # BSI = ((SWIR1+Red) - (NIR+Blue)) / ((SWIR1+Red) + (NIR+Blue))
    bsi = img.expression(
        "((S + R) - (N + B)) / ((S + R) + (N + B))",
        {"S": img.select("B11"), "R": img.select("B4"),
         "N": img.select("B8"), "B": img.select("B2")},
    ).rename("BSI")
    return img.addBands([ndvi, ndre, ndwi, ndmi, nbr, bsi])


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  ClassificaÃ§Ã£o automÃ¡tica baseada em regras (preliminar)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def classify(img: ee.Image) -> ee.Image:
    """ClassificaÃ§Ã£o por limiares de Ã­ndices. Retorna banda inteira 'class'
    (1â€“9). Ordem das regras importa: da mais especÃ­fica para a mais genÃ©rica.
    Limiares sÃ£o heurÃ­sticos e servem como diagnÃ³stico preliminar."""
    ndvi = img.select("NDVI")
    ndwi = img.select("NDWI")
    ndmi = img.select("NDMI")
    nbr = img.select("NBR")
    bsi = img.select("BSI")

    # ComeÃ§a como 0 (nÃ£o classificado) e vai preenchendo por where().
    c = ee.Image(0).rename("class").toInt()

    # 1 Ãgua â€” NDWI alto
    c = c.where(ndwi.gt(0.2), 1)
    # 2 Ãrea Ãšmida â€” Ã¡gua/umidade superficial sem vegetaÃ§Ã£o densa
    c = c.where(c.eq(0).And(ndwi.gt(0.0)).And(ndmi.gt(0.3)).And(ndvi.lt(0.6)), 2)
    # 8 Ãrea Queimada â€” NBR muito baixo em Ã¡rea nÃ£o-Ã¡gua
    c = c.where(c.eq(0).And(nbr.lt(0.05)).And(ndvi.lt(0.35)), 8)
    # 9 Infraestrutura â€” NDVI muito baixo, seco, nÃ£o Ã© solo agrÃ­cola Ãºmido
    c = c.where(c.eq(0).And(ndvi.lt(0.2)).And(ndmi.lt(0.0)).And(bsi.gt(0.0)), 9)
    # 3 Solo Exposto â€” BSI alto e NDVI baixo
    c = c.where(c.eq(0).And(bsi.gt(0.1)).And(ndvi.lt(0.25)), 3)
    # 7 Floresta â€” NDVI muito alto e boa umidade da vegetaÃ§Ã£o (NDMI alto)
    c = c.where(c.eq(0).And(ndvi.gt(0.7)).And(ndmi.gt(0.25)), 7)
    # 6 VegetaÃ§Ã£o SecundÃ¡ria â€” NDVI alto, umidade moderada
    c = c.where(c.eq(0).And(ndvi.gt(0.55)).And(ndmi.gt(0.15)), 6)
    # 4 Agricultura â€” NDVI alto/moderado com solo evidente (BSI nÃ£o desprezÃ­vel)
    c = c.where(c.eq(0).And(ndvi.gt(0.4)).And(bsi.gt(-0.1)), 4)
    # 5 Pastagem â€” NDVI moderado (inclui rasteira remanescente)
    c = c.where(c.eq(0).And(ndvi.gt(0.15)), 5)
    # resto continua 0 (sem dado / nÃ£o classificado) e Ã© mascarado
    return c.updateMask(c.gt(0))


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  VisualizaÃ§Ã£o (getMapId) por camada
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def _vis_for(layer: str) -> Dict[str, Any]:
    if layer == "rgb":
        return {"bands": ["B4", "B3", "B2"], "min": 0.02, "max": 0.3, "gamma": 1.1}
    if layer == "ndvi":
        return {"bands": ["NDVI"], "min": -0.2, "max": 0.9, "palette": PALETTE_NDVI}
    if layer == "ndre":
        return {"bands": ["NDRE"], "min": -0.1, "max": 0.6, "palette": PALETTE_NDVI}
    if layer == "ndwi":
        return {"bands": ["NDWI"], "min": -0.5, "max": 0.6, "palette": PALETTE_WATER}
    if layer == "ndmi":
        return {"bands": ["NDMI"], "min": -0.4, "max": 0.5, "palette": PALETTE_MOIST}
    if layer == "bsi":
        return {"bands": ["BSI"], "min": -0.4, "max": 0.4, "palette": PALETTE_SOIL}
    if layer == "nbr":
        return {"bands": ["NBR"], "min": -0.3, "max": 0.8, "palette": PALETTE_BURN}
    if layer == "classificacao":
        return {"bands": ["class"], "min": 1, "max": 9, "palette": CLASS_PALETTE}
    raise ValueError(f"Camada desconhecida: {layer}")


def _legend_for(layer: str) -> List[Dict[str, str]]:
    if layer == "classificacao":
        return [{"label": CLASSES[i][0], "color": CLASSES[i][1]} for i in sorted(CLASSES)]
    return []


def make_tiles(aoi_geojson: Dict[str, Any], layer: str, date_start: str,
               date_end: str, max_cloud: float, mode: str) -> Dict[str, Any]:
    aoi = geometry_from_geojson(aoi_geojson)
    coll = build_collection(aoi, date_start, date_end, max_cloud)
    n = coll.size().getInfo()
    if not n:
        raise ValueError("Nenhuma imagem Sentinel-2 encontrada para os filtros informados.")

    img = add_indices(composite(coll, mode)).clip(aoi)
    if layer == "classificacao":
        img = classify(img).clip(aoi)

    vis = _vis_for(layer)
    mapid = img.getMapId(vis)
    tile_url = mapid["tile_fetcher"].url_format

    return {
        "layer": layer,
        "tile_url": tile_url,
        "attribution": "Copernicus Sentinel-2 / Google Earth Engine",
        "image_date": latest_date(coll),
        "n_images": n,
        "vis": vis,
        "legend": _legend_for(layer),
    }


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  Datas disponÃ­veis e sÃ©rie temporal
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def list_dates(aoi_geojson: Dict[str, Any], date_start: str, date_end: str,
               max_cloud: float, mode: str) -> Dict[str, Any]:
    aoi = geometry_from_geojson(aoi_geojson)
    s = get_settings()
    coll = (ee.ImageCollection(s.s2_collection)
            .filterBounds(aoi)
            .filterDate(date_start, date_end)
            .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", max_cloud))
            .sort("system:time_start", False))

    def feat(img):
        img = ee.Image(img)
        return ee.Feature(None, {
            "date": ee.Date(img.get("system:time_start")).format("YYYY-MM-dd"),
            "cloud": img.get("CLOUDY_PIXEL_PERCENTAGE"),
        })

    fc = ee.FeatureCollection(coll.map(feat)).limit(300)
    info = fc.getInfo()
    dates = [{"date": f["properties"]["date"], "cloud": f["properties"].get("cloud")}
             for f in info.get("features", [])]
    return {"dates": dates}


def time_series(aoi_geojson: Dict[str, Any], index: str, date_start: str,
                date_end: str, max_cloud: float, mode: str) -> Dict[str, Any]:
    """MÃ©dia do Ã­ndice sobre a AOI por imagem, ao longo do perÃ­odo."""
    s = get_settings()
    aoi = geometry_from_geojson(aoi_geojson)
    coll = build_collection(aoi, date_start, date_end, max_cloud)
    band = {"ndvi": "NDVI", "ndre": "NDRE", "ndwi": "NDWI",
            "ndmi": "NDMI", "nbr": "NBR", "bsi": "BSI"}.get(index, "NDVI")

    def feat(img):
        img = add_indices(ee.Image(img))
        mean = img.select(band).reduceRegion(
            reducer=ee.Reducer.mean(), geometry=aoi,
            scale=s.stats_scale, maxPixels=int(1e13), bestEffort=True,
        ).get(band)
        return ee.Feature(None, {
            "date": ee.Date(img.get("system:time_start")).format("YYYY-MM-dd"),
            "value": mean,
        })

    fc = ee.FeatureCollection(coll.map(feat)).limit(300)
    info = fc.getInfo()
    pts = []
    for f in info.get("features", []):
        p = f["properties"]
        v = p.get("value")
        pts.append({"date": p["date"],
                    "value": round(v, 4) if isinstance(v, (int, float)) else None})
    pts.sort(key=lambda x: x["date"])
    return {"index": index, "points": pts}
