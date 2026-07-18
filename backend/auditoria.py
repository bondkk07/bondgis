"""AUDITORIA_CAR — cruzamento automático CAR × Sentinel-2 × MapBiomas.

Compara as camadas do CAR (limite do imóvel, APP, Reserva Legal, uso
consolidado, vegetação nativa) com a cobertura observada pelo Sentinel-2
(classificação por índices) e valida contra o MapBiomas (asset no Earth
Engine), detectando divergências e produzindo indicadores/scores.

Todo o processamento pesado roda no Earth Engine. As heurísticas de
classificação e de divergência são **preliminares** (cena única, limiares) —
servem como triagem, não como laudo oficial.
"""
from typing import Any, Dict, List, Optional

import ee

from config import get_settings
from sentinel import (add_indices, build_collection, composite,
                      geometry_from_geojson, latest_date)

# ── MapBiomas (asset EE, Coleção 10) ──────────────────────────────────────
MAPBIOMAS_ASSET = ("projects/mapbiomas-public/assets/brazil/lulc/collection10/"
                   "mapbiomas_brazil_collection10_integration_v1")
MAPBIOMAS_ANO_MAX = 2024

# Códigos MapBiomas agrupados (Coleção 10)
MB_NATIVA = [1, 3, 4, 5, 6, 49, 10, 11, 12, 32, 29, 50, 13]  # floresta + veg. natural
MB_ANTROPICO = [14, 15, 18, 19, 39, 20, 40, 62, 41, 36, 46, 47, 35, 48,
                9, 21, 22, 23, 24, 30, 25]                    # pasto/agro/urbano/mineração
MB_AGUA = [26, 33, 31]                                        # água + aquicultura
MB_UMIDA = [11]                                               # campo alagado / área úmida

# ── Classificação Sentinel-2 (auditoria — 9 classes) ──────────────────────
AUDIT_CLASSES: Dict[int, tuple] = {
    1: ("Água", "#2c7fb8"),
    2: ("Área Úmida", "#41b6c4"),
    3: ("Solo Exposto", "#a6611a"),
    4: ("Agricultura", "#fdae61"),
    5: ("Pastagem", "#addd8e"),
    6: ("Vegetação Secundária", "#78c679"),
    7: ("Floresta", "#006837"),
    8: ("Área Queimada", "#7f0000"),
    9: ("Infraestrutura", "#969696"),
}
# Agrupamentos das classes Sentinel para as regras de divergência
SENT_VEG = [6, 7]              # vegetação (secundária + floresta)
SENT_ANTROPICO = [3, 4, 5, 8, 9]
SENT_AGUA_UMIDA = [1, 2]


def classify_audit(img: ee.Image) -> ee.Image:
    """Classificação Sentinel-2 em 9 classes da auditoria (banda 'class')."""
    ndvi = img.select("NDVI")
    ndwi = img.select("NDWI")
    ndmi = img.select("NDMI")
    nbr = img.select("NBR")
    bsi = img.select("BSI")

    c = ee.Image(0).rename("class").toInt()
    c = c.where(ndwi.gt(0.2), 1)                                               # Água
    c = c.where(c.eq(0).And(ndwi.gt(0.0)).And(ndmi.gt(0.3)).And(ndvi.lt(0.6)), 2)  # Área Úmida
    c = c.where(c.eq(0).And(nbr.lt(0.05)).And(ndvi.lt(0.35)), 8)               # Área Queimada
    c = c.where(c.eq(0).And(ndvi.lt(0.2)).And(ndmi.lt(0.0)).And(bsi.gt(0.0)), 9)  # Infraestrutura
    c = c.where(c.eq(0).And(bsi.gt(0.1)).And(ndvi.lt(0.25)), 3)                # Solo Exposto
    c = c.where(c.eq(0).And(ndvi.gt(0.7)).And(ndmi.gt(0.25)), 7)               # Floresta
    c = c.where(c.eq(0).And(ndvi.gt(0.55)).And(ndmi.gt(0.15)), 6)              # Veg. Secundária
    c = c.where(c.eq(0).And(ndvi.gt(0.4)).And(bsi.gt(-0.1)), 4)                # Agricultura
    c = c.where(c.eq(0).And(ndvi.gt(0.3)), 5)                                  # Pastagem
    c = c.where(c.eq(0).And(ndvi.gt(0.15)), 5)                                 # remanescente → pastagem
    return c.updateMask(c.gt(0))


# ── utilidades ────────────────────────────────────────────────────────────
def _mask_in(img: ee.Image, codes: List[int]) -> ee.Image:
    """Máscara 1 onde img ∈ codes, senão 0 (mantém geometria)."""
    return img.remap(codes, [1] * len(codes), 0)


def _area_ha(mask: ee.Image, geom: ee.Geometry, scale: int) -> float:
    """Área (ha) onde mask==1, dentro de geom."""
    if geom is None:
        return 0.0
    a = (ee.Image.pixelArea().updateMask(mask).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=geom, scale=scale,
        maxPixels=int(1e13), bestEffort=True).get("area"))
    v = a.getInfo()
    return (float(v) / 10_000.0) if v else 0.0


def _classes_por_camada(sent: ee.Image, geom: ee.Geometry, scale: int) -> List[Dict[str, Any]]:
    """Área por classe Sentinel dentro de uma geometria."""
    if geom is None:
        return []
    area_img = ee.Image.pixelArea().addBands(sent.select("class"))
    grouped = area_img.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName="class"),
        geometry=geom, scale=scale, maxPixels=int(1e13), bestEffort=True).getInfo()
    por = {int(g["class"]): float(g["sum"]) for g in grouped.get("groups", [])}
    total = sum(por.values()) or 1.0
    out = []
    for cod in sorted(AUDIT_CLASSES):
        m2 = por.get(cod, 0.0)
        if m2 <= 0:
            continue
        nome, cor = AUDIT_CLASSES[cod]
        out.append({"codigo": cod, "classe": nome, "cor": cor,
                    "area_ha": round(m2 / 10_000.0, 3),
                    "pct": round(m2 / total * 100.0, 2)})
    return out


def _nivel_risco(pct: float) -> str:
    if pct >= 20:
        return "crítico"
    if pct >= 8:
        return "alto"
    if pct >= 2:
        return "médio"
    return "baixo"


# ── auditoria principal ───────────────────────────────────────────────────
def run_auditoria(imovel_geojson: Dict[str, Any],
                  camadas: Dict[str, Optional[Dict[str, Any]]],
                  date_start: str, date_end: str, max_cloud: float,
                  mode: str) -> Dict[str, Any]:
    s = get_settings()
    scale = s.stats_scale

    imovel = geometry_from_geojson(imovel_geojson)

    def geom_or_none(key):
        g = camadas.get(key)
        try:
            return geometry_from_geojson(g) if g else None
        except Exception:
            return None

    app = geom_or_none("app")
    rl = geom_or_none("reserva_legal")
    uso = geom_or_none("uso_consolidado")
    vegnat = geom_or_none("vegetacao_nativa")

    # Sentinel-2
    coll = build_collection(imovel, date_start, date_end, max_cloud)
    n = coll.size().getInfo()
    if not n:
        raise ValueError("Nenhuma imagem Sentinel-2 encontrada para os filtros informados.")
    img = add_indices(composite(coll, mode)).clip(imovel)
    sent = classify_audit(img)

    # MapBiomas (ano mais recente disponível ≤ fim do período)
    ano = min(MAPBIOMAS_ANO_MAX, int(date_end[:4])) if date_end[:4].isdigit() else MAPBIOMAS_ANO_MAX
    mb = ee.Image(MAPBIOMAS_ASSET).select(f"classification_{ano}").clip(imovel)

    # máscaras Sentinel
    sent_veg = _mask_in(sent, SENT_VEG)
    sent_ant = _mask_in(sent, SENT_ANTROPICO)
    sent_agua = _mask_in(sent, SENT_AGUA_UMIDA)
    sent_solo_queim = _mask_in(sent, [3, 8])
    sent_agri = _mask_in(sent, [4])
    # máscaras MapBiomas
    mb_nat = _mask_in(mb, MB_NATIVA)
    mb_ant = _mask_in(mb, MB_ANTROPICO)
    mb_agua = _mask_in(mb, MB_AGUA)

    area_imovel = imovel.area(maxError=1).getInfo() / 10_000.0
    base = area_imovel or 1.0

    def pct(ha):
        return round(ha / base * 100.0, 2)

    # ── Detecções de divergência ───────────────────────────────────────────
    divergencias: List[Dict[str, Any]] = []

    def add_div(nome, mask, geom, descricao, severidade):
        ha = _area_ha(mask, geom, scale) if geom is not None else 0.0
        divergencias.append({
            "tipo": nome, "descricao": descricao,
            "area_ha": round(ha, 3), "pct": pct(ha),
            "risco": _nivel_risco(pct(ha)), "severidade": severidade,
            "aplicavel": geom is not None,
        })
        return ha

    # 1. APP antropizada
    app_antrop = add_div("APP antropizada", sent_ant, app,
                         "Uso antrópico (agricultura, pastagem, solo, infra) dentro de APP.", 4)
    # 2. APP sem vegetação
    app_semveg = add_div("APP sem vegetação", sent_veg.Not().And(sent_agua.Not()), app,
                         "APP sem cobertura vegetal nem corpo hídrico.", 3)
    # 3. RL com déficit
    rl_deficit = add_div("RL com déficit", sent_veg.Not().And(_mask_in(mb, MB_NATIVA).Not()), rl,
                         "Reserva Legal sem vegetação nativa (Sentinel e MapBiomas).", 4)
    # 4. RL excedente (veg nativa confirmada em área de uso consolidado)
    veg_conf = sent_veg.And(mb_nat)
    rl_exced = add_div("RL excedente", veg_conf, uso,
                       "Vegetação nativa observada em área de uso consolidado (excedente potencial).", 1)
    # 5. Mudança de uso (discordância Sentinel × MapBiomas)
    mudanca = add_div("Mudança de uso", sent_ant.And(mb_nat).Or(sent_veg.And(mb_ant)), imovel,
                      "Divergência entre uso observado (Sentinel) e MapBiomas.", 2)
    # 6. Supressão vegetal (MapBiomas nativo, Sentinel antrópico)
    supressao = add_div("Supressão vegetal", mb_nat.And(sent_ant), imovel,
                        "Áreas nativas no MapBiomas com uso antrópico no Sentinel (indício de supressão).", 4)
    # 7. Expansão agrícola (Sentinel agricultura, MapBiomas não agrícola)
    expansao = add_div("Expansão agrícola", sent_agri.And(mb_ant.Not()), imovel,
                       "Agricultura no Sentinel sobre área não-agrícola no MapBiomas.", 3)
    # 8. Corpos hídricos não declarados (água fora de APP)
    agua_geom = imovel
    agua_mask = sent_agua.And(mb_agua)
    if app is not None:
        # água dentro do imóvel mas fora da APP declarada
        app_mask = ee.Image(1).clip(app).mask()
        agua_mask = agua_mask.And(app_mask.Not())
    corpos = add_div("Corpos hídricos não declarados", agua_mask, agua_geom,
                     "Água/área úmida fora das APPs declaradas.", 3)
    # 9. Áreas degradadas (solo/queimada em APP ou RL)
    deg_geom = app if app is not None else rl
    degradadas = add_div("Áreas degradadas", sent_solo_queim,
                         deg_geom if deg_geom is not None else imovel,
                         "Solo exposto ou área queimada em zona que deveria ser vegetada.", 2)

    # ── Composição por camada CAR ───────────────────────────────────────────
    camadas_stats = {
        "imovel": {"area_ha": round(area_imovel, 3), "classes": _classes_por_camada(sent, imovel, scale)},
        "app": {"area_ha": round(app.area(1).getInfo()/10_000.0, 3) if app is not None else None,
                "classes": _classes_por_camada(sent, app, scale)},
        "reserva_legal": {"area_ha": round(rl.area(1).getInfo()/10_000.0, 3) if rl is not None else None,
                          "classes": _classes_por_camada(sent, rl, scale)},
        "uso_consolidado": {"area_ha": round(uso.area(1).getInfo()/10_000.0, 3) if uso is not None else None,
                            "classes": _classes_por_camada(sent, uso, scale)},
        "vegetacao_nativa": {"area_ha": round(vegnat.area(1).getInfo()/10_000.0, 3) if vegnat is not None else None,
                             "classes": _classes_por_camada(sent, vegnat, scale)},
    }

    # ── Scores (0–100) ──────────────────────────────────────────────────────
    app_ha = camadas_stats["app"]["area_ha"]
    rl_ha = camadas_stats["reserva_legal"]["area_ha"]

    score_app = None
    if app_ha:
        score_app = round(max(0.0, 100.0 * (1 - app_antrop / app_ha)), 1)
    score_rl = None
    if rl_ha:
        score_rl = round(max(0.0, 100.0 * (1 - rl_deficit / rl_ha)), 1)

    veg_obs_ha = _area_ha(sent_veg, imovel, scale)
    score_veg = round(min(100.0, 100.0 * veg_obs_ha / base), 1)

    div_total_ha = supressao + mudanca + expansao + app_antrop
    score_car = round(max(0.0, 100.0 * (1 - div_total_ha / base)), 1)

    partes = [x for x in [score_app, score_rl, score_veg] if x is not None]
    score_ambiental = round(sum(partes) / len(partes), 1) if partes else score_veg

    todos = [x for x in [score_ambiental, score_car, score_veg, score_app, score_rl] if x is not None]
    indice_geral = round(sum(todos) / len(todos), 1) if todos else 0.0

    if indice_geral >= 85:
        grau = "Conforme"
    elif indice_geral >= 70:
        grau = "Atenção"
    elif indice_geral >= 50:
        grau = "Divergência moderada"
    else:
        grau = "Divergência crítica"

    # ── Camada de severidade + GeoJSON das divergências ─────────────────────
    sev = ee.Image(1).clip(imovel).rename("nivel").toInt()   # 1 = conforme
    sev = sev.where(sent_solo_queim.And(_clip_mask(app, rl)), 2)  # atenção
    sev = sev.where(app_semveg_mask(app, sent_veg, sent_agua), 3)  # moderada
    sev = sev.where(_clip_to(sent_ant, app).Or(mb_nat.And(sent_ant)), 4)  # crítica
    geojson_div = _vetorizar_divergencias(sev, imovel, scale)

    return {
        "n_images": n,
        "image_date": latest_date(coll),
        "mapbiomas_ano": ano,
        "area_total_ha": round(area_imovel, 3),
        "camadas": camadas_stats,
        "divergencias": divergencias,
        "scores": {
            "ambiental": score_ambiental,
            "car": score_car,
            "vegetacao": score_veg,
            "app": score_app,
            "reserva_legal": score_rl,
            "indice_geral": indice_geral,
        },
        "grau_conformidade": grau,
        "geojson_divergencias": geojson_div,
    }


# ── helpers de severidade / vetorização ───────────────────────────────────
def _clip_mask(app, rl):
    """Máscara 1 dentro de APP ∪ RL (ou tudo, se nenhuma)."""
    geoms = [g for g in [app, rl] if g is not None]
    if not geoms:
        return ee.Image(1)
    uniao = ee.FeatureCollection([ee.Feature(g) for g in geoms]).geometry()
    return ee.Image(1).clip(uniao).mask()


def _clip_to(mask, geom):
    if geom is None:
        return ee.Image(0)
    return mask.And(ee.Image(1).clip(geom).mask())


def app_semveg_mask(app, sent_veg, sent_agua):
    if app is None:
        return ee.Image(0)
    dentro = ee.Image(1).clip(app).mask()
    return dentro.And(sent_veg.Not()).And(sent_agua.Not())


def _vetorizar_divergencias(sev: ee.Image, geom: ee.Geometry, scale: int) -> Dict[str, Any]:
    """Converte a imagem de severidade (2..4) em polígonos GeoJSON.
    Nível 1 (conforme) é omitido para reduzir o payload."""
    cores = {2: "#f2c744", 3: "#e8842c", 4: "#d7301f"}
    rotulos = {2: "Atenção", 3: "Divergência moderada", 4: "Divergência crítica"}
    div = sev.updateMask(sev.gte(2)).toInt()
    try:
        vectors = div.reduceToVectors(
            geometry=geom, scale=max(scale, 30), geometryType="polygon",
            eightConnected=False, labelProperty="nivel",
            maxPixels=int(1e12), bestEffort=True)
        info = vectors.limit(500).getInfo()
    except Exception:
        return {"type": "FeatureCollection", "features": []}
    feats = []
    for f in info.get("features", []):
        nivel = int(f["properties"].get("nivel", 2))
        f["properties"] = {"nivel": nivel, "rotulo": rotulos.get(nivel, ""),
                           "cor": cores.get(nivel, "#f2c744")}
        feats.append(f)
    return {"type": "FeatureCollection", "features": feats}
