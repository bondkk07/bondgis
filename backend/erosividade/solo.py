# -*- coding: utf-8 -*-
"""Preparação da extensão USLE (prompt §10): LS e tolerância de perda de solo.

Só o necessário para os testes T6 (LS de parcela) e T17 (tolerância Método I);
os demais métodos ficam prontos para a fase de perda de solo completa.
"""
import math


# ── LS (topografia) ──────────────────────────────────────────────────────
def ls_parcela(L: float, S_pct: float) -> float:
    """LS de parcela: (L^0,5/100)·(1,36 + 0,975·S + 0,1385·S²). S em %."""
    return (L ** 0.5 / 100.0) * (1.36 + 0.975 * S_pct + 0.1385 * S_pct ** 2)


def ls_bertoni(L: float, S_pct: float) -> float:
    """Bertoni & Lombardi: 0,00984·L^0,63·S^1,18."""
    return 0.00984 * (L ** 0.63) * (S_pct ** 1.18)


def s_usle(theta_rad: float) -> float:
    """Fator S da USLE: 0,065 + 4,56·senθ + 65,41·sen²θ."""
    s = math.sin(theta_rad)
    return 0.065 + 4.56 * s + 65.41 * s * s


# ── Tolerância de perda de solo (§10) ────────────────────────────────────
def _r_metodo_i(relacao_ba: float) -> float:
    """r pela relação textural B/A (argila): <1,5 → 1,0; 1,5–2,5 → 0,75; >2,5 → 0,5."""
    if relacao_ba < 1.5:
        return 1.0
    if relacao_ba <= 2.5:
        return 0.75
    return 0.5


def tolerancia_metodo_i(h_mm: float, relacao_ba: float, densidade: float) -> float:
    """T (t·ha⁻¹·ano⁻¹) = (h·r/1000) · 10 · densidade. h limitado a 1.000 mm.
    Ex. (T17): h=1200→1000, B/A=1,25→r=1,0, dens=1,2 → 12,0."""
    h = min(h_mm, 1000.0)
    r = _r_metodo_i(relacao_ba)
    T_mm = h * r / 1000.0           # espessura tolerável (mm/ano)
    return T_mm * 10.0 * densidade  # mm → t/ha (1 mm·ha = 10 m³ = 10·densidade t)
