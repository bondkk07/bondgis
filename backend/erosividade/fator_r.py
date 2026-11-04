# -*- coding: utf-8 -*-
"""Cálculo do fator R pelo coeficiente de chuva (prompt §2.2) e utilidades (§2.7, §8).

R em MJ·mm·ha⁻¹·h⁻¹·ano⁻¹. Métodos:
  - Variante B (climatológica): médias mensais + P anual.
  - Variante A (ano a ano, OFICIAL): só anos com 12 meses válidos; R = média dos R_j.
  - Variante C (desagregação proporcional): opcional.
"""
from typing import List, Dict, Optional
from statistics import mean, pstdev, stdev

from .equacoes import Equacao, PADRAO

FATOR_SI = 9.81   # t·m·mm/ha·h  →  MJ·mm/ha·h  (§2.7)

# Classes de Carvalho (1994, CPRM) — §8
CLASSES = [
    (2452.0, "baixa"), (4905.0, "média"), (7357.0, "média a forte"),
    (9810.0, "forte"), (float("inf"), "muito forte"),
]
EI_MES_CRITICO = 500.0   # Rufino 1986 (§8)
MESES = ["jan", "fev", "mar", "abr", "mai", "jun",
         "jul", "ago", "set", "out", "nov", "dez"]


def converter_si(valor_metrico: float) -> float:
    """t·m·mm·ha⁻¹·h⁻¹ → MJ·mm·ha⁻¹·h⁻¹ (×9,81). Ex.: 6,866 → 67,355."""
    return valor_metrico * FATOR_SI


def rc(p: float, P: float) -> float:
    """Coeficiente de chuva Rc = p²/P (p = chuva do mês, P = chuva do ano)."""
    if P <= 0:
        return 0.0
    return (p * p) / P


def classe(R: float) -> str:
    for limite, nome in CLASSES:
        if R < limite:
            return nome
    return "muito forte"


def _ei_mensal(meses_mm: List[float], P: float, eq: Equacao) -> List[float]:
    """EI de cada mês pela equação (base-Rc usa Rc=p²/P; base-p usa p)."""
    ei = []
    for p in meses_mm:
        if eq.base_rc:
            val, _ = eq.avaliar_ei(rc=rc(p, P))
        else:
            val, _ = eq.avaliar_ei(p=p)
        ei.append(max(0.0, val))
    return ei


def variante_B(meses_mm: List[float], P: float, eq: Equacao = PADRAO) -> Dict:
    """Climatológica: usa as médias mensais e o P anual informado.
    Devolve R, EI mensal, % e % acumulada, meses críticos e período crítico."""
    assert len(meses_mm) == 12, "Informe as 12 médias mensais (jan→dez)."
    ei = _ei_mensal(meses_mm, P, eq)
    R = sum(ei)
    pct = [100.0 * e / R if R else 0.0 for e in ei]
    acum, s = [], 0.0
    for e in ei:
        s += e
        acum.append(100.0 * s / R if R else 0.0)
    criticos = [MESES[i] for i, e in enumerate(ei) if e > EI_MES_CRITICO]
    return {
        "metodo": "B", "equacao_id": eq.id, "R": R, "classe": classe(R),
        "ei_mensal": ei, "pct": pct, "pct_acumulada": acum,
        "meses_criticos": criticos,
        "periodo_critico": periodo_critico(ei),
    }


def variante_A(anos: List[Dict], eq: Equacao = PADRAO) -> Dict:
    """Ano a ano (oficial). `anos` = [{"meses":[12], "P":anual}, ...].
    Só entram anos com os 12 meses (todos != None). R = média dos R_j.
    Devolve também a série anual, desvio, CV e o EI mensal médio."""
    completos = [a for a in anos if a.get("meses") and len(a["meses"]) == 12
                 and all(m is not None for m in a["meses"])]
    if not completos:
        return {"metodo": "A", "equacao_id": eq.id, "R": None, "n_anos": 0,
                "aviso": "Nenhum ano completo (12 meses válidos)."}
    serie_R, soma_ei = [], [0.0] * 12
    for a in completos:
        ei = _ei_mensal(a["meses"], a["P"], eq)
        serie_R.append(sum(ei))
        for i in range(12):
            soma_ei[i] += ei[i]
    n = len(serie_R)
    R = mean(serie_R)
    desvio = stdev(serie_R) if n > 1 else 0.0
    cv = 100.0 * desvio / R if R else 0.0
    ei_medio = [s / n for s in soma_ei]
    return {
        "metodo": "A", "equacao_id": eq.id, "R": R, "classe": classe(R),
        "n_anos": n, "serie_R_anual": serie_R, "desvio": desvio, "cv": cv,
        "ei_mensal": ei_medio, "periodo_critico": periodo_critico(ei_medio),
    }


def variante_C(ei_medio_mensal: List[float], meses_mm: List[float],
               media_mensal: List[float]) -> List[float]:
    """Desagregação proporcional (opcional, §2.2-C): EI_ij = p_ij·EI̅_i/p̄_i."""
    out = []
    for i in range(12):
        pbar = media_mensal[i]
        out.append(meses_mm[i] * ei_medio_mensal[i] / pbar if pbar else 0.0)
    return out


def periodo_critico(ei_mensal: List[float]) -> Dict:
    """Menor bloco de meses CONSECUTIVOS (circular, ano todo) que soma ≥ 70% do R."""
    R = sum(ei_mensal)
    if R <= 0:
        return {"meses": [], "pct": 0.0}
    alvo = 0.70 * R
    melhor = None
    for ini in range(12):
        s = 0.0
        for comp in range(1, 13):
            s += ei_mensal[(ini + comp - 1) % 12]
            if s >= alvo:
                if melhor is None or comp < melhor[0]:
                    melhor = (comp, ini, s)
                break
    if melhor is None:
        return {"meses": MESES[:], "pct": 100.0}
    comp, ini, s = melhor
    meses = [MESES[(ini + k) % 12] for k in range(comp)]
    return {"meses": meses, "pct": round(100.0 * s / R, 1)}
