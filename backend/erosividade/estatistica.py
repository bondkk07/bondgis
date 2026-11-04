# -*- coding: utf-8 -*-
"""Estatística de frequência e de séries (prompt §7 e §5).

Período de retorno (Weibull), distribuições (log-normal, Gumbel-Chow), mínimo de
anos de Mokus, Grubbs-Beck, IC da média e preenchimento por razão das normais.
"""
import math
from typing import List, Tuple, Dict

SQRT6_PI = math.sqrt(6.0) / math.pi   # ≈ 0,779697


# ── Período de retorno empírico — Weibull (§7) ───────────────────────────
def weibull(N: int, m: int) -> Dict:
    """T = (N+1)/m ; Pr = 100/T. `m` = posição em ordem DECRESCENTE (1 = maior)."""
    T = (N + 1) / m
    return {"T": T, "Pr": 100.0 / T}


# ── Distribuições teóricas (§7) ──────────────────────────────────────────
def gumbel_chow_k(T: float) -> float:
    """Fator de frequência de Gumbel–Chow:
    k = −(√6/π)·[0,5772 + ln ln(T/(T−1))]."""
    return -SQRT6_PI * (0.5772 + math.log(math.log(T / (T - 1.0))))


def x_t_gumbel(media: float, desvio: float, T: float) -> float:
    return media + gumbel_chow_k(T) * desvio


def x_t_lognormal(media: float, cv: float, k: float) -> float:
    """X_T = X̄·(1 + Cv·k) (log-normal, forma do §7). `cv` em fração."""
    return media * (1.0 + cv * k)


# ── Mínimo de anos — Mokus (§7) ──────────────────────────────────────────
def mokus(x100: float, x2: float, t: float) -> float:
    """Y = (4,30·t·log10(θ))² + 6, com θ = X₁₀₀/X₂."""
    theta = x100 / x2
    return (4.30 * t * math.log10(theta)) ** 2 + 6.0


# ── Outliers — Grubbs & Beck (§5) ────────────────────────────────────────
# T(N, α=10%) tabelado (§5); interpola linear entre pontos conhecidos.
_GB = {20: 2.385, 30: 2.563, 68: 2.883}


def grubbs_beck_T(N: int) -> float:
    if N in _GB:
        return _GB[N]
    ks = sorted(_GB)
    if N <= ks[0]:
        return _GB[ks[0]]
    if N >= ks[-1]:
        return _GB[ks[-1]]
    for a, b in zip(ks, ks[1:]):
        if a <= N <= b:
            f = (N - a) / (b - a)
            return _GB[a] + f * (_GB[b] - _GB[a])
    return _GB[ks[-1]]


def grubbs_beck_inferior(media: float, desvio: float, T: float) -> float:
    """Limite inferior: X̄ − T(N,α)·S. Abaixo dele → revisão (não exclusão)."""
    return media - T * desvio


# ── Intervalo de confiança da média (§7, USACE) ──────────────────────────
def ic_media(media: float, desvio: float, N: int, t: float) -> Tuple[float, float]:
    """R̄ ± t(0,025; N−1)·S/√N."""
    margem = t * desvio / math.sqrt(N)
    return (media - margem, media + margem)


# ── Preenchimento: razão das normais (§5) ────────────────────────────────
def razao_das_normais(Nx: float, vizinhas: List[Tuple[float, float]]) -> float:
    """Px = (Nx/n)·Σ(Pi/Ni). `vizinhas` = [(Pi, Ni), ...] (n ≥ 3 recomendável)."""
    n = len(vizinhas)
    if n == 0:
        raise ValueError("Informe ao menos uma vizinha.")
    soma = sum(Pi / Ni for Pi, Ni in vizinhas if Ni)
    return (Nx / n) * soma
