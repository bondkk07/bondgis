# -*- coding: utf-8 -*-
"""Chuvas intensas / desagregação de duração (prompt §7, opcional para terraços).

CETESB-DAEE (coeficientes de duração), Bell e Pfafstetter. Durações em string
padronizada. Usado nos testes T16.
"""
import math

# Coeficientes de desagregação DAEE-CETESB (§7). Cada chave: (duração, base).
CETESB = {
    ("24h", "1dia"): 1.14,
    ("12h", "24h"): 0.85, ("10h", "24h"): 0.82, ("8h", "24h"): 0.78,
    ("6h", "24h"): 0.72, ("1h", "24h"): 0.42,
    ("30min", "1h"): 0.74, ("25min", "30min"): 0.91, ("20min", "30min"): 0.81,
    ("15min", "30min"): 0.70, ("10min", "30min"): 0.54, ("5min", "30min"): 0.34,
}
# Cadeia para chegar de "1dia" a cada duração.
_CADEIA = {
    "1dia": [], "24h": [("24h", "1dia")],
    "12h": [("24h", "1dia"), ("12h", "24h")],
    "10h": [("24h", "1dia"), ("10h", "24h")],
    "8h":  [("24h", "1dia"), ("8h", "24h")],
    "6h":  [("24h", "1dia"), ("6h", "24h")],
    "1h":  [("24h", "1dia"), ("1h", "24h")],
    "30min": [("24h", "1dia"), ("1h", "24h"), ("30min", "1h")],
    "25min": [("24h", "1dia"), ("1h", "24h"), ("30min", "1h"), ("25min", "30min")],
    "20min": [("24h", "1dia"), ("1h", "24h"), ("30min", "1h"), ("20min", "30min")],
    "15min": [("24h", "1dia"), ("1h", "24h"), ("30min", "1h"), ("15min", "30min")],
    "10min": [("24h", "1dia"), ("1h", "24h"), ("30min", "1h"), ("10min", "30min")],
    "5min":  [("24h", "1dia"), ("1h", "24h"), ("30min", "1h"), ("5min", "30min")],
}


def desagregar_cetesb(p_1dia: float, alvo: str) -> float:
    """Chuva da duração `alvo` a partir da altura de 1 dia, encadeando os coefs."""
    v = p_1dia
    for passo in _CADEIA[alvo]:
        v *= CETESB[passo]
    return v


def bell_fator(T: float, t_min: float) -> float:
    """Fator de Bell relativo a P(10,60): (0,21·lnT + 0,52)(0,54·t^0,25 − 0,50)."""
    return (0.21 * math.log(T) + 0.52) * (0.54 * (t_min ** 0.25) - 0.50)


def bell(T: float, t_min: float, p_10_60: float) -> float:
    """P(T,t) = fator·P(10,60)."""
    return bell_fator(T, t_min) * p_10_60


# Pfafstetter — α por duração (§7); β = 0 em 5 min, 0,08 nas demais.
_PFAF_ALPHA = {"5min": 0.108, "15min": 0.122, "30min": 0.138, "1h": 0.156,
               "2h": 0.166, "4h": 0.174, "8h": 0.176, "24h": 0.170}


def pfafstetter_K(T: float, duracao: str) -> float:
    """K = T^(α + β/T^0,25)."""
    alpha = _PFAF_ALPHA[duracao]
    beta = 0.0 if duracao == "5min" else 0.08
    return T ** (alpha + beta / (T ** 0.25))
