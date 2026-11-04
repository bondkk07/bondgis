# -*- coding: utf-8 -*-
"""Testes obrigatórios do módulo de erosividade (prompt §11).

Cobre os testes DETERMINÍSTICOS (sem banco/rede): T1, T3–T6, T9–T18, e as
partes puras de T7. Os que exigem séries da ANA/pipeline (T2, T8) ficam para
as etapas de ETL/integração.

Rodar:  (na pasta backend/)  python -m erosividade.tests.test_erosividade
Também compatível com pytest.
"""
from erosividade import fator_r as fr
from erosividade import equacoes as eqs
from erosividade import energia as en
from erosividade import estatistica as st
from erosividade import intensidade as it
from erosividade import solo as so


def _rel(a, b):      # erro relativo
    return abs(a - b) / abs(b) if b else abs(a - b)


# Médias mensais (jan→dez) e P anual — Tabela 2 do TCC (T1).
CACOAL = ([266.5, 265.4, 257.9, 136.4, 44.1, 23.6, 13.6, 11.4, 61.9, 162.0, 198.3, 233.0], 1674.2)
VILHENA = ([348.3, 327.9, 300.5, 179.7, 70.3, 13.5, 8.5, 40.6, 75.8, 185.3, 247.8, 275.8], 2073.9)
ANDREAZZA = ([367.5, 332.8, 295.6, 159.4, 62.1, 13.2, 14.9, 15.2, 65.6, 140.0, 196.5, 287.1], 1949.9)
COSTA_MARQUES = ([141.2, 170.7, 165.5, 66.3, 27.4, 10.2, 12.7, 11.0, 27.4, 85.5, 101.5, 145.8], 928.9)


# ── T1 — Variante B, equação padrão (±0,1%) ──────────────────────────────
def test_t1_variante_B():
    casos = [("Cacoal", CACOAL, 8544.95), ("Vilhena", VILHENA, 10170.92),
             ("Min. Andreazza", ANDREAZZA, 10098.73), ("Costa Marques", COSTA_MARQUES, 5644.18)]
    for nome, (meses, P), R_esp in casos:
        r = fr.variante_B(meses, P)
        assert _rel(r["R"], R_esp) <= 0.001, f"{nome}: R={r['R']:.2f} ≠ {R_esp}"
    # EI de janeiro de Cacoal = 1628,62
    r = fr.variante_B(*CACOAL)
    assert abs(r["ei_mensal"][0] - 1628.62) <= 2.0, r["ei_mensal"][0]


# ── T3 — Weibull ─────────────────────────────────────────────────────────
def test_t3_weibull():
    a = st.weibull(30, 1);  assert abs(a["T"] - 31.0) < 0.01 and abs(a["Pr"] - 3.2) < 0.05
    b = st.weibull(30, 30); assert abs(b["T"] - 1.03) < 0.01
    c = st.weibull(20, 1);  assert abs(c["T"] - 21.0) < 0.01 and abs(c["Pr"] - 4.8) < 0.05


# ── T4 — Razão das normais ───────────────────────────────────────────────
def test_t4_razao_normais():
    px = st.razao_das_normais(1155, [(126, 1323), (105, 1104), (144, 1416)])
    assert abs(px - 112.44) < 0.05, px


# ── T5 — Energia cinética ────────────────────────────────────────────────
def test_t5_energia():
    assert abs(en.foster(10) - 0.2063) < 0.001
    assert abs(en.foster(50) - 0.2673) < 0.001
    assert abs(en.foster(100) - 0.283) < 0.001         # I>76 → teto
    assert abs(en.wagner_massambani(50) - 0.2626) < 0.001
    assert abs(en.wagner_massambani(100) - 0.2743) < 0.001  # teto


# ── T6 — LS de parcela ───────────────────────────────────────────────────
def test_t6_ls_parcela():
    assert abs(so.ls_parcela(9, 15) - 1.414) < 0.002
    assert abs(so.ls_parcela(9, 12) - 0.990) < 0.002
    assert abs(so.ls_parcela(22.13, 9) - 1.00) < 0.02


# ── T9 — Sensibilidade (médias de Cacoal, variante B, ±0,5%) ─────────────
def test_t9_sensibilidade():
    esperado = {1: 8544.9, 2: 9755.5, 4: 7616.9, 5: 6113.6, 7: 14424.0,
                6: 12392.3, 9: 6670.9, 8: 8759.6, 12: 8332.1, 13: 9166.9}
    meses, P = CACOAL
    for eid, R_esp in esperado.items():
        r = fr.variante_B(meses, P, eqs.POR_ID[eid])
        assert _rel(r["R"], R_esp) <= 0.005, f"eq{eid}: R={r['R']:.1f} ≠ {R_esp}"


# ── T10 — Equações com Rc = 20 (e Piraju com Rc=25,85) ───────────────────
def test_t10_rc20():
    val = lambda eid, rc: eqs.POR_ID[eid].avaliar_ei(rc=rc)[0]
    assert abs(val(1, 20) - 859.50) < 0.5
    assert abs(val(2, 20) - 1016.32) < 0.5
    assert abs(val(12, 20) - 881.07) < 0.5
    assert abs(val(15, 20) - 1523.88) < 0.5
    assert abs(val(17, 20) - 1538.22) < 0.5
    assert abs(val(13, 25.85) - 1146.90) < 0.5


# ── T11 — Faixa de calibração ────────────────────────────────────────────
def test_t11_faixa():
    # Uruguaiana quadrática com Rc=40 → recusada (produção aplica a faixa)
    try:
        eqs.URUGUAIANA_QUADRATICA.avaliar_ei(rc=40, aplicar_faixa=True)
        assert False, "deveria recusar extrapolação do polinômio"
    except eqs.ForaDaFaixa:
        pass
    # Vera (rc_min=6) com Rc abaixo → regra §2.6: EI = EI(rc_min)·Rc/rc_min + alerta
    vera = eqs.POR_ID[7]
    ei_min = vera._bruto(vera.rc_min, None)
    ei, alerta = vera.avaliar_ei(rc=3.0, aplicar_faixa=True)
    assert alerta == "abaixo_rc_min"
    assert abs(ei - ei_min * 3.0 / vera.rc_min) < 1e-6


# ── T12 — Conversão de unidade ───────────────────────────────────────────
def test_t12_conversao():
    assert abs(fr.converter_si(600.63) - 5892.18) < 0.05
    assert abs(fr.converter_si(6.866) - 67.355) < 0.01
    assert abs(fr.converter_si(198) - 1942.38) < 0.05


# ── T13 — Gumbel–Chow ────────────────────────────────────────────────────
def test_t13_gumbel():
    assert abs(st.gumbel_chow_k(10) - 1.3046) < 0.001
    assert abs(st.gumbel_chow_k(100) - 3.1367) < 0.001


# ── T14 — Mokus ──────────────────────────────────────────────────────────
def test_t14_mokus():
    assert abs(st.mokus(15852, 8442, 1.740) - 10.2) < 0.1


# ── T15 — Grubbs-Beck ────────────────────────────────────────────────────
def test_t15_grubbs_beck():
    s = 27.83 ** 0.5
    assert abs(st.grubbs_beck_inferior(20.01, s, 2.883) - 4.80) < 0.02


# ── T16 — Chuvas intensas ────────────────────────────────────────────────
def test_t16_intensas():
    assert abs(it.desagregar_cetesb(100, "24h") - 114.0) < 0.01
    assert abs(it.desagregar_cetesb(100, "1h") - 47.88) < 0.05
    assert abs(it.desagregar_cetesb(100, "30min") - 35.43) < 0.05
    assert abs(it.bell_fator(10, 60) - 1.0065) < 0.001
    assert abs(it.pfafstetter_K(10, "1h") - 1.5885) < 0.001


# ── T17 — Tolerância (Método I) ──────────────────────────────────────────
def test_t17_tolerancia():
    assert abs(so.tolerancia_metodo_i(1200, 1.25, 1.2) - 12.0) < 0.01


# ── T18 — IC do R médio ──────────────────────────────────────────────────
def test_t18_ic():
    lo, hi = st.ic_media(8810, 2244, 18, 2.110)
    assert abs(lo - 7694) < 1.5 and abs(hi - 9926) < 1.5, (lo, hi)


# ── T7 (partes puras) — robustez ─────────────────────────────────────────
def test_t7_robustez():
    assert fr.rc(0, 1000) == 0.0
    assert eqs.PADRAO.avaliar_ei(rc=0)[0] == 0.0           # p=0 → EI=0
    # ano incompleto fica fora da variante A
    r = fr.variante_A([{"meses": [100]*11 + [None], "P": 1500}])
    assert r["R"] is None and r["n_anos"] == 0


# ── Runner (sem depender de pytest) ──────────────────────────────────────
def run_all():
    testes = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    ok = 0
    for t in testes:
        try:
            t(); ok += 1; print(f"  ✔ {t.__name__}")
        except AssertionError as e:
            print(f"  ✘ {t.__name__}  →  {e}")
        except Exception as e:
            print(f"  ⚠ {t.__name__}  →  {type(e).__name__}: {e}")
    print(f"\n{ok}/{len(testes)} testes passaram.")
    return ok == len(testes)


if __name__ == "__main__":
    import sys
    sys.exit(0 if run_all() else 1)
