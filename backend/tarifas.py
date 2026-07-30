"""Consulta de tarifas de energia elétrica homologadas pela ANEEL (Dados Abertos).

Fonte: dataset "Tarifas de aplicação das distribuidoras de energia elétrica"
(dadosabertos.aneel.gov.br/dataset/tarifas-distribuidoras-energia-eletrica),
resource_id fixo abaixo. Os valores de TE/TUSD do dataset vêm em R$/MWh —
convertidos aqui para R$/kWh. O valor "com impostos" é apenas uma ESTIMATIVA:
aplica sobre a tarifa homologada (sem impostos) o mesmo cálculo "por dentro"
de ICMS/PIS/COFINS de Rondônia já usado como padrão no simulador solar — não
substitui a tarifa real da fatura, que pode variar por bandeira, revisões
extraordinárias ou componentes adicionais não presentes neste dataset.
"""
import json
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

ANEEL_HOST = "dadosabertos.aneel.gov.br"
ANEEL_RESOURCE_TARIFAS = "fcf2906c-7c32-4b9b-a637-054e7a5234f4"

# Alíquotas de RO já usadas como padrão no simulador solar (nota do formulário:
# "ICMS 19,5% + PIS 1,65% + COFINS 7,60%").
ICMS_RO = 0.195
PIS_RO = 0.0165
COFINS_RO = 0.0760

_CACHE_TTL_S = 12 * 3600  # tarifas só mudam por resolução ANEEL (raro em <12h)
_cache: Dict[str, tuple] = {}  # chave -> (timestamp, dado)


def _parse_valor(raw: Any) -> float:
    """Converte string numérica da ANEEL (às vezes com vírgula decimal) em float."""
    s = str(raw).strip()
    if not s:
        return 0.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def buscar_no_cache(chave: str) -> Optional[Dict[str, Any]]:
    item = _cache.get(chave)
    if item and (time.time() - item[0]) < _CACHE_TTL_S:
        return item[1]
    return None


def salvar_no_cache(chave: str, dado: Dict[str, Any]) -> None:
    _cache[chave] = (time.time(), dado)


def montar_url_aneel(sig_agente: str, subgrupo: str, classe: str, modalidade: str) -> str:
    filtros = {
        "SigAgente": sig_agente,
        "DscSubGrupo": subgrupo,
        "DscClasse": classe,
        "DscModalidadeTarifaria": modalidade,
        "DscBaseTarifaria": "Tarifa de Aplicação",
    }
    params = {
        "resource_id": ANEEL_RESOURCE_TARIFAS,
        "filters": json.dumps(filtros, ensure_ascii=False),
        "limit": 50,
        "sort": "DatInicioVigencia desc",
    }
    return f"https://{ANEEL_HOST}/api/3/action/datastore_search?{urlencode(params)}"


def processar_resposta(payload: Dict[str, Any], sig_agente: str, subgrupo: str,
                        classe: str, modalidade: str) -> Dict[str, Any]:
    if not payload.get("success"):
        raise ValueError("A ANEEL não retornou dados válidos para esta consulta.")
    registros = payload.get("result", {}).get("records", [])
    if not registros:
        raise ValueError(
            f"Nenhuma tarifa encontrada para distribuidora={sig_agente}, "
            f"subgrupo={subgrupo}, classe={classe}, modalidade={modalidade}."
        )

    # Entre os registros retornados, prioriza a variante "padrão" (sem baixa
    # renda / prepago / subestação) e a vigência mais recente.
    def eh_padrao(r: Dict[str, Any]) -> bool:
        subclasse_ok = (r.get("DscSubClasse") or "").strip().lower() == classe.strip().lower()
        detalhe_ok = (r.get("DscDetalhe") or "").strip().lower() == "não se aplica"
        return subclasse_ok and detalhe_ok

    candidatos = [r for r in registros if eh_padrao(r)] or registros
    candidatos.sort(key=lambda r: r.get("DatInicioVigencia") or "", reverse=True)
    registro = candidatos[0]

    vlr_te = _parse_valor(registro.get("VlrTE"))
    vlr_tusd = _parse_valor(registro.get("VlrTUSD"))
    tarifa_base = (vlr_te + vlr_tusd) / 1000  # R$/MWh -> R$/kWh

    total_aliquotas = ICMS_RO + PIS_RO + COFINS_RO
    tarifa_com_impostos = tarifa_base / (1 - total_aliquotas) if total_aliquotas < 1 else tarifa_base

    return {
        "distribuidora": sig_agente,
        "cnpj": registro.get("NumCNPJDistribuidora"),
        "subgrupo": registro.get("DscSubGrupo"),
        "classe": registro.get("DscClasse"),
        "modalidade": registro.get("DscModalidadeTarifaria"),
        "vigencia_inicio": registro.get("DatInicioVigencia"),
        "vigencia_fim": registro.get("DatFimVigencia"),
        "vlr_te_mwh": vlr_te,
        "vlr_tusd_mwh": vlr_tusd,
        "tarifa_base_kwh": round(tarifa_base, 5),
        "tarifa_sugerida_com_impostos_kwh": round(tarifa_com_impostos, 4),
        "aliquotas_usadas": {"icms": ICMS_RO, "pis": PIS_RO, "cofins": COFINS_RO},
        "fonte_url": (
            f"https://{ANEEL_HOST}/dataset/tarifas-distribuidoras-energia-eletrica"
            f"/resource/{ANEEL_RESOURCE_TARIFAS}"
        ),
    }
