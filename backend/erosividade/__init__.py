"""Módulo de Erosividade da Chuva (fator R da USLE/EUPS) — BondGIS.

AINDA EM CONSTRUÇÃO (etapa 1: núcleo de cálculo + testes). Isolado do app atual;
nada aqui é importado por main.py/sentinel.py/analise.py ainda. A API e a aba
entram em etapas posteriores (ver prompt_erosividade.md §13).

Base científica: TCC Moreira (UNIR, 2014, Rondônia) + ~100 artigos. Proposta em
coautoria com Junior Luiz Bonfante Filho (restrita a esta aba).

Unidade padrão de R: MJ·mm·ha⁻¹·h⁻¹·ano⁻¹.
"""

__all__ = ["equacoes", "fator_r", "energia", "estatistica", "intensidade", "solo"]
