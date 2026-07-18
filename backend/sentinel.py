"""Processamento Sentinel-2 no Google Earth Engine.

Implementa: máscara de nuvens, composições (recente/mediana), bandas
B2–B12, índices espectrais (NDVI, NDRE, NDWI, NDMI, BSI, NBR), classificação
automática baseada em regras e estatísticas por classe recortadas pela AOI.

Todas as funções assumem que ee.Initialize já foi chamado (earth_engine.py).
"""
from typing import Any, Dict, List, Optional, Tuple

import ee

from config import get_settings

# ── Bandas Sentinel-2 usadas (nomes na coleção S2_SR_HARMONIZED) ──────────
# B2 Blue, B3 Green, B4 Red, B5/B6/B7 RedEdge, B8 NIR, B11 SWIR1, B12 SWIR2
S2_BANDS = ["B2", "B3", "B4", "B5", "B6", "B7", "B8", "B11", "B12"]

# ── Paletas de visualização por índice ────────────────────────────────────
PALETTE_NDVI = ["#a50026", "#d73027", "#f46d43", "#fdae61", "#fee08b",
                "#d9ef8b", "#a6d96a", "#66bd63", "#1a9850", "#006837"]
PALETTE_WATER = ["#ffffcc", "#a1dab4", "#41b6c4", "#2c7fb8", "#253494"]
PALETTE_MOIST = ["#8c510a", "#d8b365", "#f6e8c3", "#c7eae5", "#5ab4ac", "#01665e"]
PALETTE_SOIL = ["#004529", "#78c679", "#ffffe5", "#fe9929", "#993404"]
PALETTE_BURN = ["#000000", "#7f0000", "#d7301f", "#fc8d59", "#fdcc8a", "#fef0d9"]

# ── Classificação automática (código → nome, cor) ─────────────────────────
CLASSES: Dict[int, Tuple[str, str]] = {
    1: ("Água", "#2c7fb8"),
    2: ("Solo exposto", "#a6611a"),
    3: ("Vegetação rasteira", "#d9ef8b"),
    4: ("Pastagem", "#addd8e"),
    5: ("Agricultura", "#fdae61"),
    6: ("Vegetação arbustiva", "#66bd63"),
    7: ("Floresta", "#006837"),
    8: ("Área queimada", "#7f0000"),
    9: ("Área construída", "#969696"),
}
CLASS_PALETTE = [CLASSES[i][1] for i in sorted(CLASSES)]


# ══════════════════════════════════════════════════════════════════════════
#  AOI, coleção e máscara de nuvens
# ══════════════════════════════════════════════════════════════════════════
def geometry_from_geojson(aoi: Dict[str, Any]) -> ee.Geometry:
    """Aceita Geometry, Feature ou FeatureCollection GeoJSON e devolve uma
    única ee.Geometry (dissolvida)."""
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
    raise ValueError(f"GeoJSON não suportado: {t!r}")


def _mask_s2_sr(img: ee.Image) -> ee.Image:
    """Máscara de nuvens/sombra usando a banda SCL (Scene Classification).
    Remove: 3 sombra, 8 nuvem média, 9 nuvem alta, 10 cirrus, 11 neve."""
    scl = img.select("SCL")
    mask = (scl.neq(3).And(scl.neq(8)).And(scl.neq(9))
            .And(scl.neq(10)).And(scl.neq(11)))
    # Reflectância SR vem em escala 0–10000.
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
    """Reduz a coleção a uma imagem. 'recent' = imagem mais recente com
    prioridade (mosaic sobre coleção ordenada); 'median' = mediana."""
    if mode == "median":
        return coll.median()
    # recent: ordena por data crescente e faz mosaic → pixels mais recentes no topo
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


# ══════════════════════════════════════════════════════════════════════════
#  Índices espectrais
# ══════════════════════════════════════════════════════════════════════════
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


# ══════════════════════════════════════════════════════════════════════════
#  Classificação automática baseada em regras (preliminar)
# ══════════════════════════════════════════════════════════════════════════
def classify(img: ee.Image) -> ee.Image:
    """Classificação por limiares de índices. Retorna banda inteira 'class'
    (1–9). Ordem das regras importa: da mais específica para a mais genérica.
    Limiares são heurísticos e servem como diagnóstico preliminar."""
    ndvi = img.select("NDVI")
    ndwi = img.select("NDWI")
    ndmi = img.select("NDMI")
    nbr = img.select("NBR")
    bsi = img.select("BSI")

    # Começa como 0 (não classificado) e vai preenchendo por where().
    c = ee.Image(0).rename("class").toInt()

    # 1 Água — NDWI alto
    c = c.where(ndwi.gt(0.2), 1)
    # 8 Área queimada — NBR muito baixo em área não-água
    c = c.where(c.eq(0).And(nbr.lt(0.05)).And(ndvi.lt(0.35)), 8)
    # 2 Solo exposto — BSI alto e NDVI baixo
    c = c.where(c.eq(0).And(bsi.gt(0.1)).And(ndvi.lt(0.25)), 2)
    # 9 Área construída — NDVI muito baixo, não é solo agrícola úmido
    c = c.where(c.eq(0).And(ndvi.lt(0.2)).And(ndmi.lt(0.0)).And(bsi.gt(0.0)), 9)
    # 7 Floresta — NDVI muito alto e boa umidade da vegetação (NDMI alto)
    c = c.where(c.eq(0).And(ndvi.gt(0.7)).And(ndmi.gt(0.2)), 7)
    # 6 Vegetação arbustiva — NDVI alto, umidade moderada
    c = c.where(c.eq(0).And(ndvi.gt(0.55)), 6)
    # 5 Agricultura — NDVI alto/moderado com solo evidente (BSI não desprezível)
    c = c.where(c.eq(0).And(ndvi.gt(0.4)).And(bsi.gt(-0.1)), 5)
    # 4 Pastagem — NDVI moderado
    c = c.where(c.eq(0).And(ndvi.gt(0.3)), 4)
    # 3 Vegetação rasteira — NDVI baixo-moderado remanescente
    c = c.where(c.eq(0).And(ndvi.gt(0.15)), 3)
    # resto continua 0 (sem dado / não classificado) e é mascarado
    return c.updateMask(c.gt(0))


# ══════════════════════════════════════════════════════════════════════════
#  Visualização (getMapId) por camada
# ══════════════════════════════════════════════════════════════════════════
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


# ══════════════════════════════════════════════════════════════════════════
#  Estatísticas por classe + médias de índices
# ══════════════════════════════════════════════════════════════════════════
def compute_stats(aoi_geojson: Dict[str, Any], date_start: str, date_end: str,
                  max_cloud: float, mode: str) -> Dict[str, Any]:
    s = get_settings()
    aoi = geometry_from_geojson(aoi_geojson)
    coll = build_collection(aoi, date_start, date_end, max_cloud)
    n = coll.size().getInfo()
    if not n:
        raise ValueError("Nenhuma imagem Sentinel-2 encontrada para os filtros informados.")

    img = add_indices(composite(coll, mode)).clip(aoi)
    classified = classify(img)

    # Área por classe: pixelArea agrupada pela banda 'class'.
    area_img = ee.Image.pixelArea().addBands(classified.select("class"))
    grouped = area_img.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName="class"),
        geometry=aoi, scale=s.stats_scale, maxPixels=int(1e13), bestEffort=True,
    ).getInfo()

    area_por_classe: Dict[int, float] = {}
    for g in grouped.get("groups", []):
        area_por_classe[int(g["class"])] = float(g["sum"])  # m²

    area_total_m2 = aoi.area(maxError=1).getInfo()
    area_total_ha = area_total_m2 / 10_000.0

    classes_out: List[Dict[str, Any]] = []
    for cod in sorted(CLASSES):
        nome, cor = CLASSES[cod]
        m2 = area_por_classe.get(cod, 0.0)
        ha = m2 / 10_000.0
        pct = (m2 / area_total_m2 * 100.0) if area_total_m2 else 0.0
        if ha <= 0:
            continue
        classes_out.append({
            "codigo": cod, "classe": nome, "cor": cor,
            "area_ha": round(ha, 4), "pct": round(pct, 2),
        })

    # Médias dos índices sobre a AOI.
    means = img.select(["NDVI", "NDRE", "NDWI", "NDMI", "NBR", "BSI"]).reduceRegion(
        reducer=ee.Reducer.mean(), geometry=aoi,
        scale=s.stats_scale, maxPixels=int(1e13), bestEffort=True,
    ).getInfo()
    indices = {k: (round(v, 4) if isinstance(v, (int, float)) else None)
               for k, v in means.items()}

    def ha_of(cod: int) -> float:
        return round(area_por_classe.get(cod, 0.0) / 10_000.0, 4)

    resumo = {
        "area_total_ha": round(area_total_ha, 4),
        "agua_ha": ha_of(1),
        "solo_exposto_ha": ha_of(2),
        "floresta_ha": ha_of(7),
        # vegetação = rasteira + pastagem + arbustiva + floresta
        "vegetacao_ha": round(sum(ha_of(c) for c in (3, 4, 6, 7)), 4),
        "agricultura_ha": ha_of(5),
    }

    return {
        "area_total_ha": round(area_total_ha, 4),
        "image_date": latest_date(coll),
        "n_images": n,
        "indices": indices,
        "classes": classes_out,
        "resumo": resumo,
    }


# ══════════════════════════════════════════════════════════════════════════
#  Datas disponíveis e série temporal
# ══════════════════════════════════════════════════════════════════════════
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
    """Média do índice sobre a AOI por imagem, ao longo do período."""
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
