# -*- coding: utf-8 -*-
"""Cálculo da erosividade por propriedade (orquestra o núcleo).

Junta: chuva mensal (CHIRPS ou manual) → variantes A/B (fator_r) → período de
retorno/IC/Mokus (estatistica) → sensibilidade entre equações → faixa de
incerteza → nível de confiança. Não baixa dados nem toca em banco; recebe a
chuva já pronta (ver chuva_ee.py) e devolve um dict pronto para a API.

Regras científicas: prompt §2.6 (seleção/sensibilidade), §7 (estatística) e §8
(classes e confiança).
"""
from datetime import date
from typing import Any, Dict, List, Optional

from . import equacoes as eqs
from . import estatistica as st
from . import fator_r as fr

T_RETORNO = [2, 5, 10, 20]   # Weibull empírico só vale até T = N+1 (45 anos → 46)
MES_SECO_MM = 60.0          # limiar p/ contar meses secos (regime)

# t de Student bilateral (α=0,05 → 0,025 por cauda) por grau de liberdade.
_T_0025 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056,
    27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}


def _t_student(df: int) -> float:
    if df <= 0:
        return 12.706
    if df in _T_0025:
        return _T_0025[df]
    return 1.96 if df > 30 else _T_0025[min(_T_0025, key=lambda k: abs(k - df))]


def _regime(meses_medios: List[float]) -> Dict[str, Any]:
    """Detecta estação seca a partir das médias mensais. O método Rc funciona
    bem com estação seca (Aw/Am/Cwa) e mal com chuva distribuída (Cf*)."""
    secos = sum(1 for p in meses_medios if p < MES_SECO_MM)
    tem_seca = secos >= 2
    return {"meses_secos": secos, "tem_estacao_seca": tem_seca,
            "rotulo": "estação seca definida" if tem_seca else "chuva distribuída"}


def _alternativas_por_regime(regime: Dict[str, Any]) -> List[int]:
    """Equações de sensibilidade (2–3) do mesmo regime (§2.6). Para RO (Aw, sem
    equação calibrada) usa as de Mato Grosso; chuva distribuída usa as do Sul."""
    if regime["tem_estacao_seca"]:
        return [2, 4, 5]          # Cuiabá, Cáceres, Rondonópolis (MT, Aw)
    return [15, 17, 18]           # São Borja, Uruguaiana, Santa Rosa (RS, Cfa)


def _nivel(n: int) -> str:
    return {3: "alta", 2: "média", 1: "baixa"}.get(max(1, min(3, n)), "baixa")


def _confianca(chuva: Dict, A: Dict, spread: float, eq: eqs.Equacao,
               regime: Dict) -> Dict[str, Any]:
    nivel = 3
    motivos: List[str] = []
    fonte = chuva.get("fonte", "")

    if "CHIRPS" in fonte:
        nivel = min(nivel, 2)
        motivos.append("Chuva estimada por satélite (CHIRPS), não por pluviômetro da ANA/INMET.")
    if not regime["tem_estacao_seca"]:
        nivel = min(nivel, 2)
        motivos.append("Chuva bem distribuída no ano: o método do coeficiente de chuva (Rc) perde precisão.")
    if eq.id == 1:
        motivos.append("Equação padrão (Lombardi Neto & Moldenhauer); não há equação calibrada para a região.")
    if spread is not None and spread > 0.25:
        nivel -= 1
        motivos.append(f"Equações alternativas discordam em {spread*100:.0f}% (> 25%).")

    n_anos = A.get("n_anos") or 0
    if n_anos and n_anos < 20:
        nivel -= 1
        motivos.append(f"Série de {n_anos} anos (abaixo dos 20 recomendados).")
    elif not n_anos:
        motivos.append("Sem série ano a ano (apenas médias): período de retorno indisponível.")

    return {"nivel": _nivel(nivel), "motivos": motivos}


def calcular(aoi_geojson: Dict[str, Any], chuva: Dict[str, Any],
             equacao_id: int = 1,
             alternativas: Optional[List[int]] = None) -> Dict[str, Any]:
    eq = eqs.POR_ID.get(equacao_id, eqs.PADRAO)
    meses = chuva["meses_medios"]
    P = chuva["P_medio"]
    regime = _regime(meses)

    # ── variantes B (climatológica) e A (ano a ano, oficial) ────────────────
    B = fr.variante_B(meses, P, eq)
    completos = chuva.get("anos_completos") or []
    A = fr.variante_A(completos, eq) if completos else {"R": None, "n_anos": 0}
    R_oficial = A["R"] if A.get("R") else B["R"]

    # ── distribuição mensal: média dos EI de cada ano (ano a ano, como no artigo)
    dist = B
    if A.get("ei_mensal"):
        ei_A = A["ei_mensal"]
        tot = sum(ei_A)
        acum, s_ = [], 0.0
        for e in ei_A:
            s_ += e
            acum.append(100.0 * s_ / tot if tot else 0.0)
        dist = {"ei_mensal": ei_A, "pct": [100.0 * e / tot if tot else 0.0 for e in ei_A],
                "pct_acumulada": acum,
                "meses_criticos": [fr.MESES[i] for i, e in enumerate(ei_A) if e > fr.EI_MES_CRITICO],
                "periodo_critico": fr.periodo_critico(ei_A)}
    tot_d = sum(dist["ei_mensal"])
    cs_out_abr = (100.0 * sum(dist["ei_mensal"][i] for i in (9, 10, 11, 0, 1, 2, 3)) / tot_d) if tot_d else None

    # ── período de retorno (Weibull, Eq. 8 e 9), tendência (Mann-Kendall/Sen), IC, Mokus
    retorno: List[Dict] = []
    tendencia = None
    ic = None
    mokus_anos = None
    if A.get("serie_R_anual") and A["n_anos"] >= 5:
        Rm, S, N = A["R"], A["desvio"], A["n_anos"]
        serie = A["serie_R_anual"]
        for T in T_RETORNO:
            r_t = st.r_retorno_weibull(serie, T)
            if r_t is not None:
                retorno.append({"T": T, "R": round(r_t, 1)})
        anos_A = [a["ano"] for a in completos if a.get("meses") and len(a["meses"]) == 12
                  and all(m is not None for m in a["meses"])]
        if len(anos_A) == len(serie):
            p_mk = st.mann_kendall_p(serie)
            tendencia = {"sen_por_ano": round(st.declive_sen(anos_A, serie), 1),
                         "p_mann_kendall": round(p_mk, 3), "significativa": p_mk < 0.05}
        t = _t_student(N - 1)
        lo, hi = st.ic_media(Rm, S, N, t)
        ic = [round(lo, 1), round(hi, 1)]
        x100, x2 = st.x_t_gumbel(Rm, S, 100), st.x_t_gumbel(Rm, S, 2)
        if x2 > 0:
            mokus_anos = round(st.mokus(x100, x2, t), 1)

    # ── sensibilidade (R com a escolhida + alternativas do regime) ──────────
    alt = alternativas or _alternativas_por_regime(regime)
    ordem = [equacao_id] + [a for a in alt if a != equacao_id]
    sensibilidade = []
    for aid in ordem:
        e = eqs.POR_ID.get(aid)
        if not e:
            continue
        # Mesmo método do R principal (A, ano a ano, quando há série), para que a
        # linha da equação escolhida coincida com o R exibido.
        rA = fr.variante_A(completos, e) if completos else {"R": None}
        r = rA if rA.get("R") else fr.variante_B(meses, P, e)
        sensibilidade.append({
            "id": aid, "nome": e.nome, "local": e.local, "koppen": e.koppen,
            "referencia": e.referencia, "R": round(r["R"], 1),
            "escolhida": aid == equacao_id,
            "metodo": "A (ano a ano)" if rA.get("R") else "B (climatológica)",
        })
    Rs = [s["R"] for s in sensibilidade] or [R_oficial]
    media_s = sum(Rs) / len(Rs)
    spread = (max(Rs) - min(Rs)) / media_s if media_s else 0.0
    faixa = [round(min(Rs), 1), round(max(Rs), 1)]

    confianca = _confianca(chuva, A, spread, eq, regime)

    return {
        "R": round(R_oficial, 1),
        "R_climatologico": round(B["R"], 1),
        "metodo_R": "A (ano a ano)" if A.get("R") else "B (climatológica)",
        "classe": fr.classe(R_oficial),
        "faixa_sensibilidade": faixa,
        "ic_media": ic,
        "mokus_anos": mokus_anos,
        "ei_mensal": [round(v, 1) for v in dist["ei_mensal"]],
        "pct": [round(v, 1) for v in dist["pct"]],
        "pct_acumulada": [round(v, 1) for v in dist["pct_acumulada"]],
        "cs_out_abr": round(cs_out_abr, 1) if cs_out_abr is not None else None,
        "tendencia": tendencia,
        "meses": fr.MESES,
        "meses_criticos": dist["meses_criticos"],
        "periodo_critico": dist["periodo_critico"],
        "serie_R_anual": [round(v, 1) for v in (A.get("serie_R_anual") or [])],
        "n_anos": A.get("n_anos", 0),
        "cv": round(A.get("cv"), 1) if A.get("cv") is not None else None,
        "retorno": retorno,
        "sensibilidade": sensibilidade,
        "spread_sensibilidade": round(spread, 3),
        "confianca": confianca["nivel"],
        "motivos_confianca": confianca["motivos"],
        "regime": regime,
        "equacao": {"id": eq.id, "nome": eq.nome, "referencia": eq.referencia,
                    "koppen": eq.koppen, "local": eq.local},
        "chuva": {"meses_medios": meses, "P_medio": P},
        "metodologia": {
            "fonte_chuva": chuva.get("fonte", "—"),
            "periodo": chuva.get("periodo", "—"),
            "n_anos": chuva.get("n_anos", A.get("n_anos", 0)),
            "escala_m": chuva.get("escala_m"),
            "equacao": f"{eq.nome} — {eq.referencia}",
            "indice": "EI30 via coeficiente de chuva (Rc = p²/P)",
            "classes": "Carvalho (2008)",
            "periodo_retorno": "Weibull empírico, T = (N+1)/m",
            "metodo_espacial": chuva.get("metodo_espacial"),
            "data_calculo": date.today().isoformat(),
            "limitacoes": [
                "A USLE estima média de longo prazo, não um evento isolado; não considera deposição.",
                "O método Rc mede volume e concentração da chuva, não a intensidade.",
            ],
        },
        # série mensal ano a ano (mm), usada na comparação com estações (artigo, seção 2.7)
        "chuva_anos": [{"ano": a["ano"], "meses": a["meses"]} for a in (chuva.get("anos_completos") or [])],
        "anos_serie": [a["ano"] for a in (chuva.get("anos_completos") or [])],
        "area_ha": chuva.get("area_ha"),
        "centroide": chuva.get("centroide"),
        "unidade_R": "MJ·mm·ha⁻¹·h⁻¹·ano⁻¹",
    }
