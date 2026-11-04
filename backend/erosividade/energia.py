# -*- coding: utf-8 -*-
"""Energia cinética da chuva por segmento (prompt §2.3), em MJ·ha⁻¹·mm⁻¹.
I em mm/h. Usado no método direto EI30 (fase 2) e nos testes T5."""
import math


def foster(I: float) -> float:
    """Foster et al. (1981) — padrão. Teto e=0,283 para I > 76 mm/h."""
    if I <= 0:
        return 0.0
    if I > 76.0:
        return 0.283
    return 0.119 + 0.0873 * math.log10(I)


def wagner_massambani(I: float) -> float:
    """Wagner & Massambani. Teto 0,2743."""
    if I <= 0:
        return 0.0
    return min(0.2743, 0.153 + 0.0645 * math.log10(I))


def hudson(I: float) -> float:
    """Hudson: e = 0,298 − 1,275/I."""
    if I <= 0:
        return 0.0
    return 0.298 - 1.275 / I


FUNCOES = {"foster": foster, "wagner_massambani": wagner_massambani, "hudson": hudson}
