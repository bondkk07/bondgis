# -*- coding: utf-8 -*-
"""Testes do fluxo por propriedade (sem rede/EE): a chuva é injetada à mão.

Verifica que o override manual reproduz o núcleo (T1/T9) e que a variante A
(ano a ano) liga o período de retorno. O caminho CHIRPS (Earth Engine) é
coberto pelo teste de integração manual na verificação do plano.

Rodar:  (em backend/)  python -m erosividade.tests.test_propriedade
"""
from erosividade import propriedade as pr

CACOAL = ([266.5, 265.4, 257.9, 136.4, 44.1, 23.6, 13.6, 11.4, 61.9, 162.0, 198.3, 233.0], 1674.2)


def _rel(a, b):
    return abs(a - b) / abs(b) if b else abs(a - b)


def _chuva_manual(meses, P):
    return {"fonte": "Entrada manual (médias informadas)", "periodo": "—",
            "n_anos": 0, "anos": [], "anos_completos": [],
            "meses_medios": meses, "P_medio": P,
            "escala_m": None, "area_ha": None, "centroide": None}


def test_manual_reproduz_t1():
    meses, P = CACOAL
    r = pr.calcular({}, _chuva_manual(meses, P), 1)
    assert _rel(r["R"], 8544.95) <= 0.001, r["R"]
    assert r["metodo_R"].startswith("B")
    assert r["classe"] == "forte"              # 7.357–9.810
    assert r["retorno"] == [] and r["n_anos"] == 0   # sem série anual
    assert r["periodo_critico"]["pct"] >= 70.0


def test_sensibilidade_t9():
    meses, P = CACOAL
    r = pr.calcular({}, _chuva_manual(meses, P), 1, [2, 4, 5])
    byid = {s["id"]: s["R"] for s in r["sensibilidade"]}
    assert _rel(byid[1], 8544.9) <= 0.005
    assert _rel(byid[2], 9755.5) <= 0.005      # Cuiabá
    assert _rel(byid[4], 7616.9) <= 0.005      # Cáceres
    assert _rel(byid[5], 6113.6) <= 0.005      # Rondonópolis
    assert sum(1 for s in r["sensibilidade"] if s["escolhida"]) == 1


def test_variante_A_liga_retorno():
    meses, P = CACOAL
    anos = []
    for i, f in enumerate((0.9, 0.95, 1.0, 1.05, 1.1, 1.15)):
        mm = [round(m * f, 2) for m in meses]
        anos.append({"ano": 2015 + i, "meses": mm, "P": round(sum(mm), 2)})
    chuva = _chuva_manual(meses, P)
    chuva["anos_completos"] = anos
    chuva["n_anos"] = len(anos)
    r = pr.calcular({}, chuva, 1)
    assert r["metodo_R"].startswith("A")
    assert r["n_anos"] == 6
    # Weibull empírico (Eq. 8 e 9 do artigo): com 6 anos só vale até T = N+1 = 7
    assert [x["T"] for x in r["retorno"]] == [2, 5]
    rs = [x["R"] for x in r["retorno"]]
    assert rs == sorted(rs)                    # crescente com T
    assert r["ic_media"] and r["ic_media"][0] < r["R"] < r["ic_media"][1]
    assert r["cv"] is not None


def test_artigo_weibull_mk_sen_cs():
    """Conferências do método descrito no artigo (seções 2.4 e 2.8)."""
    from erosividade import estatistica as st
    serie = [float(x) for x in range(1, 46)]           # 45 anos crescentes
    anos = list(range(1981, 2026))
    assert st.declive_sen(anos, serie) == 1.0
    assert st.mann_kendall_p(serie) < 0.001
    assert st.mann_kendall_p([5.0, 5.0, 5.0, 5.0]) == 1.0
    # T = (N+1)/m: o maior de 45 anos tem T = 46; T=2 cai entre m=23 e m=22
    assert abs(st.r_retorno_weibull(serie, 46) - 45) < 1e-9
    assert st.r_retorno_weibull(serie, 50) is None
    assert 22 <= st.r_retorno_weibull(serie, 2) <= 24
    # CS e classes da Tabela 1
    meses, P = CACOAL
    anos_c = [{"ano": 2000 + i, "meses": meses, "P": P} for i in range(6)]
    chuva = _chuva_manual(meses, P)
    chuva["anos_completos"] = anos_c
    r = pr.calcular({}, chuva, 1)
    assert 0 < r["cs_out_abr"] <= 100
    assert r["tendencia"] is not None
    from erosividade import fator_r as fr
    assert fr.classe(2000) == "fraca" and fr.classe(9900) == "muito forte"


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
