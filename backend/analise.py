"""ANALISAR ÁREA — pipeline unificado de análise ambiental.

Um único fluxo: Selecionar área → Tipo de análise → Processar → Resultado.
Todos os tipos compartilham os MESMOS intermediários (composição Sentinel-2
classificada, MapBiomas atual e histórico, geometrias do CAR), mudando apenas
os módulos executados:

    completa      = composicao + cruzamentos + score + supressao + recuperacao + temporal
    auditoria     = composicao + cruzamentos + score
    conformidade  = cruzamentos + score
    vegetacao     = composicao (+ NDVI médio)
    supressao     = supressao
    recuperacao   = recuperacao
    temporal      = temporal

A auditoria NÃO usa critérios subjetivos: cada componente do score é um
cruzamento espacial entre uma camada oficial do CAR e a ocupação observada
(Sentinel-2, com MapBiomas como validação histórica), com fórmula explícita
(conforme/avaliada), áreas em ha e justificativa técnica rastreável.
"""
from typing import Any, Dict, List, Optional

import ee

from config import get_settings
from sentinel import (CLASSES, add_indices, build_collection, classify,
                      composite, geometry_from_geojson, latest_date)

# ── MapBiomas (asset oficial no Earth Engine, Coleção 10) ────────────────
MAPBIOMAS_ASSET = ("projects/mapbiomas-public/assets/brazil/lulc/collection10/"
                   "mapbiomas_brazil_collection10_integration_v1")
MAPBIOMAS_ANO_MIN, MAPBIOMAS_ANO_MAX = 1985, 2024

# Agrupamentos de códigos MapBiomas (Coleção 10)
MB_NATIVA = [1, 3, 4, 5, 6, 49, 10, 11, 12, 32, 29, 50, 13]
MB_ANTROPICO = [14, 15, 18, 19, 39, 20, 40, 62, 41, 36, 46, 47, 35, 48,
                9, 21, 22, 23, 24, 30, 25]
MB_AGUA = [26, 33, 31]

# Agrupamentos das 9 classes Sentinel (sentinel.CLASSES)
SENT_VEG = [6, 7]                  # Vegetação Secundária + Floresta
SENT_ANTROPICO = [3, 4, 5, 9]      # Solo, Agricultura, Pastagem, Infraestrutura
SENT_USO_PRODUTIVO = [4, 5]        # Agricultura + Pastagem
SENT_AGUA_UMIDA = [1, 2]
SENT_DEGRADACAO = [3, 8]           # Solo exposto + Queimada

TIPOS_VALIDOS = ["completa", "auditoria", "conformidade", "vegetacao",
                 "supressao", "recuperacao", "temporal"]

# Cores/nomes dos cruzamentos (usados também no GeoJSON de divergências)
CRUZAMENTOS_META = {
    1: ("Uso produtivo × Área Consolidada", "#e8842c"),
    2: ("Reserva Legal × vegetação existente", "#d7301f"),
    3: ("APP × ocupação observada", "#b30000"),
    4: ("Vegetação Nativa declarada × cobertura atual", "#f2c744"),
    5: ("Vegetação nativa histórica × supressão recente", "#7f0000"),
}


# ══════════════════════════════════════════════════════════════════════════
#  Helpers espaciais
# ══════════════════════════════════════════════════════════════════════════
def _mask_in(img: ee.Image, codes: List[int]) -> ee.Image:
    return img.remap(codes, [1] * len(codes), 0)


def _dentro(geom: Optional[ee.Geometry]) -> ee.Image:
    """Máscara 1 dentro da geometria (0 se geom ausente)."""
    if geom is None:
        return ee.Image(0)
    return ee.Image(1).clip(geom).mask()


def _area_ha(mask: ee.Image, geom: ee.Geometry, scale: int) -> float:
    if geom is None:
        return 0.0
    v = (ee.Image.pixelArea().updateMask(mask).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=geom, scale=scale,
        maxPixels=int(1e13), bestEffort=True).get("area")).getInfo()
    return round((float(v) / 10_000.0), 3) if v else 0.0


def _classes_por_geom(sent: ee.Image, geom: Optional[ee.Geometry],
                      scale: int) -> List[Dict[str, Any]]:
    """Área por classe Sentinel dentro de uma geometria (cálculo único,
    reutilizado por todos os módulos que precisam de composição)."""
    if geom is None:
        return []
    grouped = (ee.Image.pixelArea().addBands(sent.select("class"))
               .reduceRegion(
                   reducer=ee.Reducer.sum().group(groupField=1, groupName="class"),
                   geometry=geom, scale=scale, maxPixels=int(1e13),
                   bestEffort=True).getInfo())
    por = {int(g["class"]): float(g["sum"]) for g in grouped.get("groups", [])}
    total = sum(por.values()) or 1.0
    out = []
    for cod in sorted(CLASSES):
        m2 = por.get(cod, 0.0)
        if m2 <= 0:
            continue
        nome, cor = CLASSES[cod]
        out.append({"codigo": cod, "classe": nome, "cor": cor,
                    "area_ha": round(m2 / 10_000.0, 3),
                    "pct": round(m2 / total * 100.0, 2)})
    return out


# ══════════════════════════════════════════════════════════════════════════
#  Pipeline principal
# ══════════════════════════════════════════════════════════════════════════
def run_analise(aoi_geojson: Dict[str, Any],
                camadas_geojson: Dict[str, Optional[Dict[str, Any]]],
                tipo: str, date_start: str, date_end: str,
                max_cloud: float, mode: str) -> Dict[str, Any]:
    if tipo not in TIPOS_VALIDOS:
        raise ValueError(f"Tipo de análise inválido: {tipo!r}. Válidos: {TIPOS_VALIDOS}")
    s = get_settings()
    scale = s.stats_scale

    # ── Intermediários compartilhados (calculados UMA vez) ────────────────
    imovel = geometry_from_geojson(aoi_geojson)
    area_imovel = round(imovel.area(maxError=1).getInfo() / 10_000.0, 3)

    def g(key):
        gj = camadas_geojson.get(key)
        try:
            return geometry_from_geojson(gj) if gj else None
        except Exception:
            return None

    car = {k: g(k) for k in ["app", "reserva_legal", "vegetacao_nativa",
                             "area_consolidada", "servidao", "uso_restrito",
                             "hidrografia"]}

    coll = build_collection(imovel, date_start, date_end, max_cloud)
    n = coll.size().getInfo()
    if not n:
        raise ValueError("Nenhuma imagem Sentinel-2 encontrada para os filtros informados.")
    img = add_indices(composite(coll, mode)).clip(imovel)
    sent = classify(img)

    ano_atual = min(MAPBIOMAS_ANO_MAX, int(date_end[:4])) if date_end[:4].isdigit() else MAPBIOMAS_ANO_MAX
    ano_hist = max(MAPBIOMAS_ANO_MIN, ano_atual - 5)
    mb_img = ee.Image(MAPBIOMAS_ASSET)
    mb_atual = mb_img.select(f"classification_{ano_atual}").clip(imovel)
    mb_hist = mb_img.select(f"classification_{ano_hist}").clip(imovel)

    sent_veg = _mask_in(sent, SENT_VEG)
    sent_ant = _mask_in(sent, SENT_ANTROPICO)
    sent_prod = _mask_in(sent, SENT_USO_PRODUTIVO)
    mb_nat_hist = _mask_in(mb_hist, MB_NATIVA)
    mb_nat_atual = _mask_in(mb_atual, MB_NATIVA)
    mb_ant_hist = _mask_in(mb_hist, MB_ANTROPICO)

    ctx = dict(imovel=imovel, car=car, sent=sent, img=img, scale=scale,
               sent_veg=sent_veg, sent_ant=sent_ant, sent_prod=sent_prod,
               mb_nat_hist=mb_nat_hist, mb_nat_atual=mb_nat_atual,
               mb_ant_hist=mb_ant_hist, mb_img=mb_img,
               ano_atual=ano_atual, ano_hist=ano_hist,
               area_imovel=area_imovel)

    # ── Seleção de módulos por tipo ───────────────────────────────────────
    modulos: Dict[str, Any] = {}
    quer = lambda *mods: tipo in mods or tipo == "completa"

    if quer("auditoria", "vegetacao"):
        modulos["composicao"] = _mod_composicao(ctx)
    if quer("auditoria", "conformidade"):
        cruz, score, geojson = _mod_cruzamentos_score(ctx)
        modulos["cruzamentos"] = cruz
        modulos["score"] = score
        modulos["_geojson"] = geojson
    if quer("supressao"):
        modulos["supressao"] = _mod_supressao(ctx)
    if quer("recuperacao"):
        modulos["recuperacao"] = _mod_recuperacao(ctx)
    if quer("temporal"):
        modulos["temporal"] = _mod_temporal(ctx)

    geojson_div = modulos.pop("_geojson", {"type": "FeatureCollection", "features": []})

    return {
        "tipo": tipo,
        "n_images": n,
        "image_date": latest_date(coll),
        "mapbiomas_ano": ano_atual,
        "mapbiomas_ano_historico": ano_hist,
        "area_total_ha": area_imovel,
        "camadas_recebidas": {k: (v is not None) for k, v in car.items()},
        "modulos": modulos,
        "geojson_divergencias": geojson_div,
    }


# ══════════════════════════════════════════════════════════════════════════
#  Módulo: composição de uso (Sentinel) por camada do CAR
# ══════════════════════════════════════════════════════════════════════════
def _mod_composicao(ctx) -> Dict[str, Any]:
    sent, scale = ctx["sent"], ctx["scale"]
    ndvi = ctx["img"].select("NDVI").reduceRegion(
        reducer=ee.Reducer.mean(), geometry=ctx["imovel"], scale=scale,
        maxPixels=int(1e13), bestEffort=True).get("NDVI").getInfo()
    por_camada = {"imovel": _classes_por_geom(sent, ctx["imovel"], scale)}
    for k, geom in ctx["car"].items():
        if geom is not None:
            por_camada[k] = _classes_por_geom(sent, geom, scale)
    return {"ndvi_medio": round(ndvi, 4) if isinstance(ndvi, (int, float)) else None,
            "por_camada": por_camada}


# ══════════════════════════════════════════════════════════════════════════
#  Módulo: cruzamentos espaciais + score de conformidade
# ══════════════════════════════════════════════════════════════════════════
def _mod_cruzamentos_score(ctx):
    """Cada cruzamento compara UMA camada declarada do CAR com a ocupação
    observada. pct = área_conforme / área_avaliada. O score geral é a média
    dos cruzamentos ponderada pela área avaliada de cada um — sem pesos
    arbitrários: quem pondera é a própria área analisada."""
    car, scale, imovel = ctx["car"], ctx["scale"], ctx["imovel"]
    sent_veg, sent_ant, sent_prod = ctx["sent_veg"], ctx["sent_ant"], ctx["sent_prod"]
    mb_nat_hist = ctx["mb_nat_hist"]
    cruzamentos: List[Dict[str, Any]] = []
    div_img = ee.Image(0).rename("check").toInt()   # divergências p/ GeoJSON

    def add(check_id, camadas_usadas, fontes, geom_avaliada, mask_avaliada,
            mask_conforme, justificativa, extra=None):
        nonlocal div_img
        titulo, cor = CRUZAMENTOS_META[check_id]
        if geom_avaliada is None:
            cruzamentos.append({
                "id": check_id, "titulo": titulo, "aplicavel": False,
                "camadas": camadas_usadas, "fontes": fontes,
                "justificativa": "Camada não fornecida — cruzamento não avaliado.",
            })
            return
        avaliada = _area_ha(mask_avaliada, geom_avaliada, scale)
        conforme = _area_ha(mask_avaliada.And(mask_conforme), geom_avaliada, scale)
        divergente = round(max(0.0, avaliada - conforme), 3)
        pct = round(conforme / avaliada * 100.0, 2) if avaliada > 0 else 100.0
        cruzamentos.append({
            "id": check_id, "titulo": titulo, "aplicavel": True,
            "camadas": camadas_usadas, "fontes": fontes,
            "area_avaliada_ha": avaliada, "area_conforme_ha": conforme,
            "area_divergente_ha": divergente, "pct_conformidade": pct,
            "formula": "pct = área_conforme / área_avaliada × 100",
            "cor": cor, "justificativa": justificativa,
            **(extra or {}),
        })
        # marca a divergência no raster (onde avaliada e NÃO conforme)
        divergencia = mask_avaliada.And(mask_conforme.Not()).And(_dentro(geom_avaliada))
        div_img = div_img.where(div_img.eq(0).And(divergencia), check_id)

    # C1 — Uso produtivo × Área Consolidada
    add(1, ["Área Consolidada (CAR)"], ["Sentinel-2 (uso atual)"],
        imovel if car["area_consolidada"] is not None else None,
        sent_prod, _dentro(car["area_consolidada"]),
        "Avalia se a área com uso produtivo observado (agricultura + pastagem, "
        "Sentinel-2) está contida na Área Consolidada declarada no CAR. "
        "Divergente = uso produtivo fora da área consolidada (inconsistência).")

    # C2 — Reserva Legal × vegetação existente
    rl = car["reserva_legal"]
    extra_rl = None
    if rl is not None:
        rl_ha = round(rl.area(1).getInfo() / 10_000.0, 3)
        mb_pct = None
        mb_conf = _area_ha(mb_nat_hist, rl, scale)
        if rl_ha > 0:
            mb_pct = round(mb_conf / rl_ha * 100.0, 2)
        extra_rl = {"percentual_rl_sobre_imovel": round(rl_ha / ctx["area_imovel"] * 100.0, 2)
                    if ctx["area_imovel"] else None,
                    "validacao_mapbiomas_pct": mb_pct,
                    "validacao_mapbiomas_nota":
                        f"Percentual da RL com vegetação nativa no MapBiomas {ctx['ano_hist']} "
                        "(validação histórica independente)."}
    add(2, ["Reserva Legal (CAR)"], ["Sentinel-2 (cobertura atual)", "MapBiomas (validação)"],
        rl, _dentro(rl), sent_veg,
        "Avalia se a Reserva Legal declarada mantém cobertura vegetal "
        "(floresta ou vegetação secundária no Sentinel-2). Divergente = "
        "porção da RL sem vegetação (déficit).", extra_rl)

    # C3 — APP × ocupação observada
    add(3, ["APP (CAR)"], ["Sentinel-2 (uso atual)"],
        car["app"], _dentro(car["app"]), sent_ant.Not(),
        "Avalia se a APP declarada está livre de uso antrópico (solo exposto, "
        "agricultura, pastagem, infraestrutura). Água e vegetação contam como "
        "conformes. Divergente = APP antropizada.")

    # C4 — Vegetação Nativa declarada × cobertura atual
    add(4, ["Vegetação Nativa / Remanescente (CAR)"], ["Sentinel-2 (cobertura atual)"],
        car["vegetacao_nativa"], _dentro(car["vegetacao_nativa"]), sent_veg,
        "Avalia se os polígonos declarados como vegetação nativa/remanescente "
        "ainda apresentam cobertura vegetal no Sentinel-2. Divergente = perda "
        "de vegetação em área declarada como nativa.")

    # C5 — Vegetação nativa histórica × supressão recente
    add(5, [f"MapBiomas {ctx['ano_hist']} (nativa)"], ["Sentinel-2 (uso atual)"],
        imovel, mb_nat_hist, sent_ant.Not(),
        f"Avalia se as áreas que eram vegetação nativa no MapBiomas {ctx['ano_hist']} "
        "continuam sem uso antrópico hoje (Sentinel-2). Divergente = indício de "
        "supressão recente de vegetação nativa.")

    # ── Score: média ponderada pela área avaliada ─────────────────────────
    aplicaveis = [c for c in cruzamentos if c.get("aplicavel") and c.get("area_avaliada_ha", 0) > 0]
    soma_areas = sum(c["area_avaliada_ha"] for c in aplicaveis)
    if soma_areas > 0:
        valor = round(sum(c["pct_conformidade"] * c["area_avaliada_ha"]
                          for c in aplicaveis) / soma_areas, 2)
    else:
        valor = None
    if valor is None:
        classificacao = "Não avaliável (sem camadas aplicáveis)"
    elif valor >= 90:
        classificacao = "Alta conformidade"
    elif valor >= 70:
        classificacao = "Média conformidade"
    elif valor >= 50:
        classificacao = "Baixa conformidade"
    else:
        classificacao = "Conformidade crítica"

    score = {
        "valor": valor,
        "classificacao": classificacao,
        "formula": "score = Σ(pct_i × área_avaliada_i) / Σ(área_avaliada_i) — "
                   "média dos cruzamentos ponderada pela área avaliada de cada um; "
                   "sem pesos arbitrários.",
        "componentes": [{"id": c["id"], "titulo": c["titulo"],
                         "pct": c["pct_conformidade"],
                         "peso_area_ha": c["area_avaliada_ha"]} for c in aplicaveis],
        "faixas_apresentacao": {"alta": ">=90", "media": "70-89.99",
                                "baixa": "50-69.99", "critica": "<50"},
    }

    geojson = _vetorizar(div_img, imovel, scale)
    return cruzamentos, score, geojson


def _vetorizar(div_img: ee.Image, geom: ee.Geometry, scale: int) -> Dict[str, Any]:
    div = div_img.updateMask(div_img.gt(0))
    try:
        info = (div.reduceToVectors(
            geometry=geom, scale=max(scale, 30), geometryType="polygon",
            eightConnected=False, labelProperty="check",
            maxPixels=int(1e12), bestEffort=True).limit(500).getInfo())
    except Exception:
        return {"type": "FeatureCollection", "features": []}
    feats = []
    for f in info.get("features", []):
        cid = int(f["properties"].get("check", 0))
        titulo, cor = CRUZAMENTOS_META.get(cid, ("Divergência", "#e8842c"))
        f["properties"] = {"check": cid, "titulo": titulo, "cor": cor}
        feats.append(f)
    return {"type": "FeatureCollection", "features": feats}


# ══════════════════════════════════════════════════════════════════════════
#  Módulos: supressão, recuperação, temporal
# ══════════════════════════════════════════════════════════════════════════
def _mod_supressao(ctx) -> Dict[str, Any]:
    scale, imovel = ctx["scale"], ctx["imovel"]
    base = _area_ha(ctx["mb_nat_hist"], imovel, scale)
    mantida = _area_ha(ctx["mb_nat_hist"].And(ctx["sent_ant"].Not()), imovel, scale)
    suprimida = round(max(0.0, base - mantida), 3)
    return {
        "ano_referencia": ctx["ano_hist"],
        "nativa_historica_ha": base,
        "mantida_ha": mantida,
        "suprimida_ha": suprimida,
        "pct_suprimida": round(suprimida / base * 100.0, 2) if base else 0.0,
        "justificativa": f"Vegetação nativa no MapBiomas {ctx['ano_hist']} cruzada com o "
                         "uso atual (Sentinel-2): pixels hoje antrópicos = supressão.",
    }


def _mod_recuperacao(ctx) -> Dict[str, Any]:
    scale, imovel = ctx["scale"], ctx["imovel"]
    base = _area_ha(ctx["mb_ant_hist"], imovel, scale)
    regenerada = _area_ha(ctx["mb_ant_hist"].And(ctx["sent_veg"]), imovel, scale)
    return {
        "ano_referencia": ctx["ano_hist"],
        "antropica_historica_ha": base,
        "regenerada_ha": regenerada,
        "pct_regenerada": round(regenerada / base * 100.0, 2) if base else 0.0,
        "justificativa": f"Áreas antrópicas no MapBiomas {ctx['ano_hist']} que hoje "
                         "apresentam vegetação no Sentinel-2 = recuperação/regeneração.",
    }


def _mod_temporal(ctx) -> Dict[str, Any]:
    scale, imovel = ctx["scale"], ctx["imovel"]
    ano_atual = ctx["ano_atual"]
    anos = sorted({max(MAPBIOMAS_ANO_MIN, ano_atual - d) for d in (20, 10, 5, 0)})
    serie = {}
    for ano in anos:
        banda = ctx["mb_img"].select(f"classification_{ano}").clip(imovel)
        serie[str(ano)] = {
            "nativa_ha": _area_ha(_mask_in(banda, MB_NATIVA), imovel, scale),
            "antropica_ha": _area_ha(_mask_in(banda, MB_ANTROPICO), imovel, scale),
            "agua_ha": _area_ha(_mask_in(banda, MB_AGUA), imovel, scale),
        }
    return {"fonte": "MapBiomas Coleção 10 (asset Earth Engine)",
            "anos": serie,
            "justificativa": "Evolução do uso (nativa/antrópica/água) nos marcos "
                             f"{', '.join(str(a) for a in anos)}."}
