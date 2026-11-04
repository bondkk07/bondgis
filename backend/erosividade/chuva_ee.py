# -*- coding: utf-8 -*-
"""Chuva mensal da propriedade pelo CHIRPS (Google Earth Engine).

Versão do TCC/artigo: CHIRPS v3.0 em PÊNTADAS somadas em totais mensais (sem dado
diário), série de 1981 até o último ano completo, média ponderada sobre o polígono.

Simplificação assumida pelo projeto (ver plano/§13): em vez do ETL ANA/INMET +
PostGIS, a chuva vem do CHIRPS (satélite, 1981–hoje) reduzido sobre o polígono do
CAR — reaproveitando o Earth Engine que o BondGIS já usa. Devolve a série ano a
ano (para a variante A / período de retorno) e as médias climatológicas (variante
B). Nada de banco, nada de download da ANA em runtime.

Assume que ee.Initialize já rodou (earth_engine.init_earth_engine), como nos
demais endpoints. A reprojeção não é necessária: o CAR vem em lon/lat
(SIRGAS 2000 ≈ WGS84) e o EE trabalha em EPSG:4326.
"""
from typing import Any, Dict

import ee

from sentinel import geometry_from_geojson  # reaproveita o parser de AOI do app

CHIRPS = "UCSB-CHC/CHIRPS/V3/PENTAD"   # v3.0 em pêntadas (Funk et al., 2026)
BANDA = "precipitation"
ESCALA_M = 5566          # resolução nativa do CHIRPS (0,05° ≈ 5,6 km)
# Grade oficial do CHIRPS (0,05°, alinhada em −180°/60°): a redução usa exatamente
# os pixels do produto, e a média é ponderada pela fração de cada pixel no polígono.
CRS = "EPSG:4326"
CRS_TRANSFORM = [0.05, 0, -180, 0, -0.05, 60]

# Série completa do CHIRPS: de 1981 até o último ano com os 12 meses disponíveis
# (calculado na hora; hoje 1981–2025). É o período descrito no artigo (seção 2.3).
ANO_INI_PADRAO = 1981
ANO_FIM_PADRAO = None


def ultimo_ano_completo() -> int:
    """Último ano com dezembro completo na coleção (a última pêntada começa no dia 26)."""
    import datetime
    ultima = ee.Date(ee.ImageCollection(CHIRPS).aggregate_max("system:time_start")).getInfo()["value"]
    d = datetime.datetime.fromtimestamp(ultima / 1000, tz=datetime.timezone.utc)
    return d.year if (d.month == 12 and d.day >= 26) else d.year - 1


def chuva_mensal_chirps(aoi_geojson: Dict[str, Any],
                        ano_ini: int = ANO_INI_PADRAO,
                        ano_fim: int = ANO_FIM_PADRAO) -> Dict[str, Any]:
    """Média de chuva (mm) por mês e por ano sobre o polígono, via CHIRPS.

    Retorna:
      anos: [{"ano": Y, "meses": [12 ou None], "P": anual|None}]  (só p/ info)
      anos_completos: subconjunto com os 12 meses válidos (alimenta a variante A)
      meses_medios: [12]  médias climatológicas (jan→dez)
      P_medio: float      soma das médias mensais
      n_anos, periodo, fonte, area_ha, centroide
    """
    aoi = geometry_from_geojson(aoi_geojson)
    ultimo = ultimo_ano_completo()
    ano_fim = min(ano_fim or ultimo, ultimo)   # nunca usa ano incompleto
    if ano_ini > ano_fim:
        raise ValueError(f"Período inválido: {ano_ini}–{ano_fim}.")
    col = (ee.ImageCollection(CHIRPS).select(BANDA)
           .filterDate(f"{ano_ini}-01-01", f"{ano_fim + 1}-01-01")
           .filterBounds(aoi))

    anos = ee.List.sequence(ano_ini, ano_fim)
    meses = ee.List.sequence(1, 12)

    def soma_mes(y, m):
        ini = ee.Date.fromYMD(y, m, 1)
        fim = ini.advance(1, "month")
        img = col.filterDate(ini, fim).sum().rename("p")
        idx = ee.String(ee.Number(y).int().format()).cat("_").cat(
            ee.Number(m).int().format())
        return img.set("system:index", idx)

    imgs = anos.map(lambda y: meses.map(lambda m: soma_mes(y, m))).flatten()
    multi = ee.ImageCollection(ee.List(imgs)).toBands()   # bandas 'YYYY_M_p'
    # UMA chamada ao servidor resolve as ~360 médias mensais + centroide + área.
    # Média ponderada pela fração de cada pixel dentro do polígono, para qualquer
    # tamanho de imóvel. O centroide só é usado se a redução não devolver valor.
    valores = multi.reduceRegion(
        reducer=ee.Reducer.mean(), geometry=aoi, crs=CRS, crsTransform=CRS_TRANSFORM,
        maxPixels=int(1e10)).getInfo()
    metodo_espacial = "media_ponderada"
    if not any(v is not None for v in valores.values()):
        metodo_espacial = "centroide"
        valores = multi.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=aoi.centroid(1), crs=CRS,
            crsTransform=CRS_TRANSFORM).getInfo()
    centro = aoi.centroid(1).coordinates().getInfo()
    area_ha = aoi.area(1).divide(10000).getInfo()

    # ── parse: {YYYY_M_p: mm} → por ano [12] ────────────────────────────────
    por_ano: Dict[int, list] = {y: [None] * 12 for y in range(ano_ini, ano_fim + 1)}
    for chave, mm in valores.items():
        # chave = 'YYYY_M_p'
        try:
            ystr, mstr, _ = chave.split("_")
            y, m = int(ystr), int(mstr)
        except ValueError:
            continue
        if ano_ini <= y <= ano_fim and 1 <= m <= 12:
            por_ano[y][m - 1] = round(mm, 2) if mm is not None else None

    anos_out, completos = [], []
    for y in range(ano_ini, ano_fim + 1):
        mm12 = por_ano[y]
        completo = all(v is not None for v in mm12)
        P = round(sum(mm12), 2) if completo else None
        reg = {"ano": y, "meses": mm12, "P": P}
        anos_out.append(reg)
        if completo:
            completos.append({"ano": y, "meses": mm12, "P": P})

    # Médias climatológicas por mês (sobre os anos com o mês válido).
    meses_medios = []
    for i in range(12):
        vals = [por_ano[y][i] for y in por_ano if por_ano[y][i] is not None]
        meses_medios.append(round(sum(vals) / len(vals), 2) if vals else 0.0)
    P_medio = round(sum(meses_medios), 2)

    return {
        "fonte": "CHIRPS v3.0 em pêntadas (UCSB-CHC) via Earth Engine",
        "metodo_espacial": metodo_espacial,
        "periodo": f"{ano_ini}–{ano_fim}",
        "n_anos": len(completos),
        "anos": anos_out,
        "anos_completos": completos,
        "meses_medios": meses_medios,
        "P_medio": P_medio,
        "escala_m": ESCALA_M,
        "area_ha": round(area_ha, 2),
        "centroide": {"lon": round(centro[0], 5), "lat": round(centro[1], 5)},
    }
