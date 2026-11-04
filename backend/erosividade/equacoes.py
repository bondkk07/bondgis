# -*- coding: utf-8 -*-
"""Biblioteca de equações de erosividade (prompt §2.5).

Cada equação transforma o coeficiente de chuva Rc (ou a chuva p) no EI mensal
(MJ·mm·ha⁻¹·h⁻¹·mês⁻¹). Formas suportadas:
  - 'pot_rc' : a·Rc^b
  - 'lin_rc' : a·Rc + c
  - 'quad_rc': a·Rc² + b·Rc + c
  - 'pot_p'  : a·p^b
  - 'lin_p'  : a·p + c

Regra do projeto: na carga inicial SÓ a equação 1 (padrão) vem `ativa=True`.
As demais só podem ser ativadas depois de conferidas na fonte original.
Faixa de validade (`rc_min`/`rc_max` ou `p_min`/`p_max`) governa extrapolação
(ver §2.6).
"""
from dataclasses import dataclass, field
from typing import Optional, Dict


class ForaDaFaixa(Exception):
    """Rc/p fora da faixa de calibração e a equação não permite extrapolar
    (polinômio nunca extrapola; ver §2.6)."""


@dataclass
class Equacao:
    id: int
    nome: str
    forma: str
    coef: Dict[str, float]
    local: str = ""
    koppen: str = ""
    usar_para: str = "mensal_anual"      # 'mensal_anual' ou 'anual'
    rc_min: Optional[float] = None
    rc_max: Optional[float] = None
    p_min: Optional[float] = None
    p_max: Optional[float] = None
    r_publicado: Optional[float] = None
    referencia: str = ""
    verificada: bool = False
    ativa: bool = False
    unidade: str = "MJ mm/ha h mes"
    obs: str = ""

    # ── avaliação ────────────────────────────────────────────────────────
    def _bruto(self, rc: Optional[float], p: Optional[float]) -> float:
        f, c = self.forma, self.coef
        if f == "pot_rc":
            return c["a"] * (rc ** c["b"])
        if f == "lin_rc":
            return c["a"] * rc + c["c"]
        if f == "quad_rc":
            return c["a"] * rc * rc + c["b"] * rc + c["c"]
        if f == "pot_p":
            return c["a"] * (p ** c["b"])
        if f == "lin_p":
            return c["a"] * p + c["c"]
        raise ValueError(f"Forma desconhecida: {f}")

    @property
    def base_rc(self) -> bool:
        return self.forma in ("pot_rc", "lin_rc", "quad_rc")

    def avaliar_ei(self, rc: Optional[float] = None, p: Optional[float] = None,
                   aplicar_faixa: bool = False, permitir_extrapolar: bool = False):
        """Devolve (EI, alerta). `alerta` é None, 'abaixo_rc_min', 'acima_rc_max'…

        Por padrão avalia a equação CRUA (usado em comparações e sensibilidade;
        é como os R publicados foram obtidos). Com `aplicar_faixa=True` aplica as
        regras de validade de produção (§2.6):
          - acima de rc_max/p_max → alerta; polinômio (quad) é RECUSADO;
          - abaixo de rc_min → EI = EI(rc_min)·Rc/rc_min (escala linear).
        """
        alerta = None
        if self.base_rc:
            if rc is None:
                raise ValueError("Equação base-Rc exige rc.")
            if aplicar_faixa:
                if self.rc_max is not None and rc > self.rc_max:
                    if self.forma == "quad_rc" and not permitir_extrapolar:
                        raise ForaDaFaixa(
                            f"Eq {self.id} (quadrática): Rc={rc} > rc_max={self.rc_max}; "
                            "polinômio não extrapola.")
                    alerta = "acima_rc_max"
                if self.rc_min is not None and rc < self.rc_min:
                    ei_min = self._bruto(self.rc_min, None)
                    return ei_min * rc / self.rc_min, "abaixo_rc_min"
            return self._bruto(rc, None), alerta
        else:
            if p is None:
                raise ValueError("Equação base-p exige p.")
            if aplicar_faixa:
                if self.p_max is not None and p > self.p_max:
                    alerta = "acima_p_max"
                if self.p_min is not None and p < self.p_min:
                    alerta = "abaixo_p_min"
            return self._bruto(None, p), alerta


# ── Carga inicial (prompt §2.5). SÓ a nº 1 ativa. ────────────────────────
BIBLIOTECA = [
    Equacao(1, "Padrão (Lombardi Neto & Moldenhauer 1992)", "pot_rc",
            {"a": 67.355, "b": 0.85}, "Campinas-SP", "Cwa",
            referencia="Lombardi Neto & Moldenhauer, Bragantia 51(2), 1992",
            verificada=True, ativa=True, obs="Versão SI de 6,866·Rc^0,85 (×9,81)."),
    Equacao(2, "Cuiabá (Rc)", "pot_rc", {"a": 109.412, "b": 0.744},
            "Cuiabá-MT", "Aw", r_publicado=8810.0, referencia="Almeida 2011"),
    Equacao(3, "Cuiabá (p)", "pot_p", {"a": 0.547, "b": 1.483},
            "Cuiabá-MT", "Aw", referencia="Almeida 2011"),
    Equacao(4, "Cáceres", "pot_rc", {"a": 172.632645, "b": 0.5245258},
            "Cáceres-MT", "Aw", referencia="Almeida 2009, citado em Almeida 2012"),
    Equacao(5, "Rondonópolis", "pot_rc", {"a": 133.200429, "b": 0.5372499},
            "Rondonópolis-MT", "Aw", referencia="Almeida 2012"),
    Equacao(6, "Canarana", "pot_rc", {"a": 317.397829, "b": 0.484654},
            "Canarana-MT", "Aw", r_publicado=11874.0, referencia="Almeida 2012"),
    Equacao(7, "Vera", "pot_rc", {"a": 399.538719, "b": 0.458718},
            "Vera-MT", "Aw", rc_min=6.0, r_publicado=15414.0,
            referencia="Almeida 2012", obs="rc_min ilustrativo (faixa a confirmar na fonte)."),
    Equacao(8, "Poxoréo", "pot_rc", {"a": 272.865645, "b": 0.419164},
            "Poxoréo-MT", "Aw", usar_para="anual", r_publicado=8621.0,
            referencia="Almeida 2012"),
    Equacao(9, "São José do Rio Claro", "pot_rc", {"a": 147.262400, "b": 0.533025},
            "S. J. Rio Claro-MT", "Aw", r_publicado=6827.0, referencia="Almeida 2012"),
    Equacao(10, "Fortaleza (Rc)", "pot_rc", {"a": 73.989, "b": 0.7387},
            "Fortaleza-CE", "Aw/As", referencia="Silva & Dias 2003"),
    Equacao(11, "Fortaleza (linear Rc)", "lin_rc", {"a": 22.218, "c": 119.43},
            "Fortaleza-CE", "Aw/As", referencia="Silva & Dias 2003",
            obs="Alternativa em p: 4,7781·p − 103,18."),
    Equacao(12, "Mococa", "pot_rc", {"a": 111.173, "b": 0.691},
            "Mococa-SP", "Cwa", referencia="citada por Moreti 2003 e Cassol 2008"),
    Equacao(13, "Piraju", "pot_rc", {"a": 72.5488, "b": 0.8488},
            "Piraju-SP", "", r_publicado=7074.0,
            referencia="Roque 2001 (Cassol cita '75,5488' por engano)"),
    Equacao(14, "Teodoro Sampaio", "lin_rc", {"a": 46.9562, "c": 106.8183},
            "Teodoro Sampaio-SP", "", r_publicado=7172.0, referencia="Colodro 2002"),
    Equacao(15, "São Borja", "pot_rc", {"a": 55.564, "b": 1.1054},
            "São Borja-RS", "Cfa", r_publicado=9751.0, referencia="Cassol 2008",
            obs="Linear alternativa: 99,646 + 63,874·Rc (prefira a potência)."),
    Equacao(16, "Quaraí (linear Rc)", "lin_rc", {"a": 82.72, "c": -47.35},
            "Quaraí-RS", "Cfa", r_publicado=9292.0, referencia="Bazzano 2007",
            obs="Alternativa em p (p>55,8): −754,37 + 13,50·p."),
    Equacao(17, "Uruguaiana", "pot_rc", {"a": 59.265, "b": 1.087},
            "Uruguaiana-RS", "Cfa", rc_min=3.0, rc_max=19.0, r_publicado=8875.0,
            referencia="Hickmann 2008"),
    Equacao(18, "Santa Rosa", "pot_rc", {"a": 118.52, "b": 0.8034},
            "Santa Rosa-RS", "Cfa", usar_para="anual", r_publicado=11217.0,
            referencia="Mazurana 2009"),
    Equacao(19, "Lavras", "pot_rc", {"a": 85.672, "b": 0.6557},
            "Lavras-MG", "Cwa", referencia="Aquino 2014"),
    Equacao(20, "Vale do Rio Doce", "pot_rc", {"a": 137.09, "b": 0.7717},
            "Vale do Rio Doce-MG", "", referencia="Oliveira 2009 (NÃO verificada)"),
    Equacao(21, "Seropédica (linear Rc)", "lin_rc", {"a": 38.138, "c": 64.866},
            "Seropédica-RJ", "", r_publicado=5472.0, referencia="Carvalho 2005",
            obs="Alternativa em p: 7,171·p + 211,82."),
    Equacao(22, "Nova Friburgo (linear Rc)", "lin_rc", {"a": 33.856, "c": 67.991},
            "Nova Friburgo-RJ", "", r_publicado=5431.0, referencia="Carvalho 2005",
            obs="Alternativa em p: 7,216·p + 186,64."),
    Equacao(23, "Paraná (em p)", "lin_p", {"a": 4.2, "c": 19.55},
            "Paraná", "", referencia="Rufino 1993 (conferir unidade)"),
]

# Variante quadrática de Uruguaiana (proibido extrapolar; decresce após Rc≈35).
URUGUAIANA_QUADRATICA = Equacao(
    170, "Uruguaiana (quadrática)", "quad_rc",
    {"a": -1.657, "b": 117.069, "c": -252.559},
    "Uruguaiana-RS", "Cfa", rc_min=3.0, rc_max=35.0,
    referencia="Hickmann 2008", obs="Decresce a partir de Rc≈35 — proibido extrapolar.")

POR_ID = {e.id: e for e in BIBLIOTECA}
PADRAO = POR_ID[1]


def ativas():
    return [e for e in BIBLIOTECA if e.ativa]
