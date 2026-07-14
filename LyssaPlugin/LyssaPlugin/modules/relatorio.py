"""Geração de extratos de análise ambiental e temporal."""

import csv
import html as _html_escape
import os
import tempfile
from datetime import datetime

from qgis.core import QgsVectorLayer


def gerar_extrato_ambiental_html(
    imovel_layer: QgsVectorLayer,
    camadas: dict,
    area_beneficiavel_layer: QgsVectorLayer = None,
) -> str:
    """Gera extrato ambiental em HTML.

    Args:
        imovel_layer:             Camada do imóvel.
        camadas:                  Dict {nome: QgsVectorLayer} das camadas analisadas.
        area_beneficiavel_layer:  Resultado do cálculo de área beneficiável (opcional).

    Returns:
        Caminho do arquivo HTML gerado.
    """
    from .area_beneficiavel import calcular_area_ha

    area_imovel = calcular_area_ha(imovel_layer) if imovel_layer else 0.0
    linhas = []
    for nome, layer in camadas.items():
        if layer and layer.isValid():
            area = calcular_area_ha(layer)
            pct  = (area / area_imovel * 100) if area_imovel > 0 else 0.0
            linhas.append((nome, area, pct))

    area_benef = (
        calcular_area_ha(area_beneficiavel_layer)
        if area_beneficiavel_layer and area_beneficiavel_layer.isValid()
        else None
    )

    now  = datetime.now().strftime('%d/%m/%Y %H:%M')
    html = _html_ambiental(area_imovel, linhas, area_benef, now)

    path = os.path.join(tempfile.gettempdir(), 'lyssa_extrato_ambiental.html')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(html)
    return path


def gerar_extrato_temporal_html(resultados_mapbiomas: dict) -> str:
    """Gera extrato temporal MapBiomas em HTML.

    Args:
        resultados_mapbiomas: Saída de modules.mapbiomas.analisar_cobertura().

    Returns:
        Caminho do arquivo HTML gerado.
    """
    lulc = resultados_mapbiomas.get('lulc', {})
    meta = resultados_mapbiomas.get('meta', {})
    now  = datetime.now().strftime('%d/%m/%Y %H:%M')
    html = _html_temporal(lulc, meta, now)

    path = os.path.join(tempfile.gettempdir(), 'lyssa_extrato_temporal.html')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(html)
    return path


def exportar_csv_temporal(resultados_mapbiomas: dict) -> str:
    """Exporta resultados temporais como CSV."""
    lulc   = resultados_mapbiomas.get('lulc', {})
    anos   = sorted(lulc.keys())
    classes = _coletar_classes(lulc)

    path = os.path.join(tempfile.gettempdir(), 'lyssa_cobertura_temporal.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.writer(fh)
        writer.writerow(['Classe'] + anos)
        for classe in sorted(classes):
            row = [classe]
            for ano in anos:
                ano_data = lulc.get(ano, {})
                if isinstance(ano_data, dict) and classe in ano_data:
                    row.append(round(ano_data[classe].get('ha', 0), 2))
                else:
                    row.append('')
            writer.writerow(row)
    return path


def gerar_relatorio_sobreposicao_html(
    resultados: list,
    codigo_car: str = '',
    area_imovel_ha: float = 0.0,
    resultado_mapbiomas: dict = None,
) -> str:
    """Gera relatório de sobreposição ambiental em HTML.

    Args:
        resultados:          Saída de verificar_sobreposicao.verificar_sobreposicao().
        codigo_car:          Código CAR do imóvel.
        area_imovel_ha:      Área total do imóvel em ha.
        resultado_mapbiomas: Saída de mapbiomas.analisar_cobertura() (opcional).

    Returns:
        Caminho do arquivo HTML gerado.
    """
    # Separar resultados por categoria
    com_sobrep = [r for r in resultados if r.get('sobreposicao') and not r.get('erroConsulta')]
    com_erro   = [r for r in resultados if r.get('erroConsulta')]
    sem_sobrep = [r for r in resultados if not r.get('sobreposicao') and not r.get('erroConsulta')]

    # Ordem: sobreposição → erro → sem sobreposição
    sorted_res = (
        sorted(com_sobrep, key=lambda r: r['camada']) +
        sorted(com_erro,   key=lambda r: r['camada']) +
        sorted(sem_sobrep, key=lambda r: r['camada'])
    )

    now  = datetime.now().strftime('%d/%m/%Y %H:%M')
    html = _html_sobreposicao(sorted_res, codigo_car, area_imovel_ha, now, resultado_mapbiomas)

    path = os.path.join(tempfile.gettempdir(), 'lyssa_extrato_ambiental.html')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(html)
    return path


def _html_sobreposicao(resultados, codigo_car, area_imovel_ha, data_hora, mapbiomas):
    com_sobrep = sum(1 for r in resultados if r.get('sobreposicao'))
    sem_sobrep = sum(1 for r in resultados if not r.get('sobreposicao') and not r.get('erroConsulta'))
    com_erro   = sum(1 for r in resultados if r.get('erroConsulta'))

    rows = ''
    for r in resultados:
        camada  = _html_escape.escape(r.get('camada', ''))
        status  = r.get('statusTexto', '')
        count   = r.get('count', 0)
        details = r.get('detalhes', [])

        if r.get('sobreposicao'):
            badge = f'<span class="badge red">{_html_escape.escape(status)}</span>'
        elif r.get('erroConsulta'):
            badge = f'<span class="badge amber">{_html_escape.escape(status)}</span>'
        else:
            badge = f'<span class="badge green">{_html_escape.escape(status)}</span>'

        det_html = ''
        if details:
            det_html = '<ul>' + ''.join(f'<li>{_html_escape.escape(d)}</li>' for d in details) + '</ul>'

        count_cell = f'{count}' if count else '–'
        rows += (
            f'<tr>'
            f'<td>{camada}</td>'
            f'<td style="text-align:center">{badge}</td>'
            f'<td style="text-align:center">{count_cell}</td>'
            f'<td class="det">{det_html}</td>'
            f'</tr>\n'
        )

    mb_section = ''
    if mapbiomas:
        lulc = mapbiomas.get('lulc', {})
        anos = sorted(lulc.keys())
        ano_ref = anos[-1] if anos else None
        if ano_ref and isinstance(lulc.get(ano_ref), dict):
            mb_rows = ''
            for classe, info in sorted(lulc[ano_ref].items()):
                cor  = info.get('cor', '#aaa')
                ha   = info.get('ha', 0)
                pct  = info.get('pct', 0)
                dot  = f'<span style="background:{cor};display:inline-block;width:12px;height:12px;margin-right:6px;border-radius:2px;vertical-align:middle"></span>'
                mb_rows += (
                    f'<tr>'
                    f'<td>{dot}{_html_escape.escape(classe)}</td>'
                    f'<td style="text-align:right">{ha:.2f}</td>'
                    f'<td style="text-align:right">{pct:.1f}%</td>'
                    f'</tr>\n'
                )
            mb_section = f'''
<h2 style="color:#1a7f4b;margin-top:32px">
  MapBiomas – Cobertura do Solo ({ano_ref})
</h2>
<p style="font-size:.85em;color:#555">
  Fonte: MapBiomas Brasil Coleção 10.1 &nbsp;|&nbsp; Resolução: 30 m
</p>
<table>
  <thead>
    <tr><th>Classe</th><th style="text-align:right">Área (ha)</th><th style="text-align:right">%</th></tr>
  </thead>
  <tbody>{mb_rows}</tbody>
</table>'''

    car_display = _html_escape.escape(codigo_car) if codigo_car else '<em>Não identificado</em>'
    area_display = f'{area_imovel_ha:.4f} ha' if area_imovel_ha else '—'

    return f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Extrato de Análise Ambiental – Lyssa</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:"Segoe UI",Arial,sans-serif;background:#f4f6f8;color:#1a2530}}
  .header{{background:#0a2b36;color:#fff;padding:24px 32px 20px}}
  .header .tag{{background:#1a7f4b;color:#fff;font-size:.72em;padding:3px 10px;
                border-radius:12px;letter-spacing:1px;text-transform:uppercase}}
  .header h1{{font-size:1.5em;margin:8px 0 4px}}
  .header .car{{color:#a8d5c2;font-size:.9em}}
  .content{{max-width:960px;margin:0 auto;padding:24px 16px 40px}}
  .cards{{display:flex;gap:12px;margin-bottom:24px;flex-wrap:wrap}}
  .card{{background:#fff;border-radius:8px;padding:14px 20px;min-width:140px;
          box-shadow:0 1px 4px rgba(0,0,0,.08);flex:1}}
  .card .n{{font-size:2em;font-weight:700;line-height:1}}
  .card .l{{font-size:.8em;color:#666;margin-top:4px}}
  .card.red .n{{color:#c0392b}}
  .card.green .n{{color:#1a7f4b}}
  .card.amber .n{{color:#d68910}}
  .card.blue .n{{color:#1a5276}}
  .meta{{background:#fff;border-radius:8px;padding:12px 20px;margin-bottom:20px;
          box-shadow:0 1px 4px rgba(0,0,0,.08);display:flex;gap:32px;flex-wrap:wrap}}
  .meta span{{font-size:.88em;color:#555}}
  .meta strong{{color:#1a2530}}
  table{{border-collapse:collapse;width:100%;background:#fff;border-radius:8px;
          overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
  th{{background:#1a7f4b;color:#fff;padding:10px 14px;text-align:left;font-size:.85em}}
  td{{border-bottom:1px solid #eee;padding:9px 14px;font-size:.87em;vertical-align:top}}
  tr:last-child td{{border-bottom:none}}
  td.det ul{{margin:4px 0 0 14px;padding:0;color:#444;font-size:.93em}}
  .badge{{padding:3px 10px;border-radius:12px;font-size:.78em;font-weight:600;
           white-space:nowrap}}
  .badge.red{{background:#fce8e6;color:#c0392b}}
  .badge.green{{background:#e9f7ef;color:#1a7f4b}}
  .badge.amber{{background:#fef9e7;color:#d68910}}
  .footer{{text-align:center;margin-top:32px;font-size:.8em;color:#999}}
  h2{{margin-top:28px;margin-bottom:12px}}
</style>
</head>
<body>
<div class="header">
  <div class="tag">Análise Ambiental</div>
  <h1>Relatório de Sobreposição</h1>
  <div class="car">CAR: {car_display}</div>
</div>
<div class="content">

  <div class="meta">
    <span><strong>Área do Imóvel:</strong> {area_display}</span>
    <span><strong>Data da análise:</strong> {_html_escape.escape(data_hora)}</span>
    <span><strong>Camadas verificadas:</strong> {len(resultados)}</span>
  </div>

  <div class="cards">
    <div class="card red">
      <div class="n">{com_sobrep}</div>
      <div class="l">Com sobreposição</div>
    </div>
    <div class="card green">
      <div class="n">{sem_sobrep}</div>
      <div class="l">Sem sobreposição</div>
    </div>
    <div class="card amber">
      <div class="n">{com_erro}</div>
      <div class="l">Não verificadas</div>
    </div>
    <div class="card blue">
      <div class="n">{len(resultados)}</div>
      <div class="l">Total consultadas</div>
    </div>
  </div>

  <h2 style="color:#1a7f4b">Resultado por Camada</h2>
  <table>
    <thead>
      <tr>
        <th style="width:38%">Camada</th>
        <th style="width:14%;text-align:center">Status</th>
        <th style="width:9%;text-align:center">Qtd</th>
        <th>Detalhes</th>
      </tr>
    </thead>
    <tbody>
{rows}
    </tbody>
  </table>

  {mb_section}

  <p class="footer">Gerado pelo plugin Lyssa – QGIS &nbsp;|&nbsp; {_html_escape.escape(data_hora)}</p>
</div>
</body>
</html>'''


def _coletar_classes(lulc: dict) -> set:
    classes = set()
    for ano_data in lulc.values():
        if isinstance(ano_data, dict) and 'erro' not in ano_data and 'aviso' not in ano_data:
            classes.update(ano_data.keys())
    return classes


def _html_ambiental(area_imovel, linhas, area_benef, data_hora):
    rows = ''
    for nome, area, pct in linhas:
        rows += f'<tr><td>{nome}</td><td>{area:.4f}</td><td>{pct:.2f}%</td></tr>\n'

    benef_row = ''
    if area_benef is not None:
        pct_benef = (area_benef / area_imovel * 100) if area_imovel else 0.0
        benef_row = (
            f'<tr style="background:#d4f4d4;font-weight:bold">'
            f'<td>Área Beneficiável</td>'
            f'<td>{area_benef:.4f}</td>'
            f'<td>{pct_benef:.2f}%</td></tr>'
        )

    return f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Extrato Ambiental – Lyssa</title>
<style>
  body {{font-family:Arial,sans-serif;margin:30px;color:#222}}
  h1   {{color:#1a7f4b;margin-bottom:4px}}
  p    {{margin:4px 0}}
  table{{border-collapse:collapse;width:100%;margin-top:16px}}
  th,td{{border:1px solid #ccc;padding:8px 12px;text-align:left}}
  th   {{background:#1a7f4b;color:#fff}}
  tr:nth-child(even){{background:#f5f5f5}}
  .footer{{margin-top:20px;font-size:.85em;color:#888}}
</style>
</head>
<body>
<h1>Extrato de Análise Ambiental</h1>
<p><strong>Área do Imóvel:</strong> {area_imovel:.4f} ha</p>
<p><strong>Data:</strong> {data_hora}</p>
<table>
  <thead><tr><th>Camada</th><th>Área (ha)</th><th>% do Imóvel</th></tr></thead>
  <tbody>{rows}{benef_row}</tbody>
</table>
<p class="footer">Gerado pelo plugin Lyssa – QGIS</p>
</body>
</html>'''


def _html_temporal(lulc, meta, data_hora):
    anos        = sorted(lulc.keys())
    area_total  = meta.get('area_total_ha', 0)
    resolucao   = meta.get('resolucao_m', 30)
    classes_cor = {}

    for ano_data in lulc.values():
        if isinstance(ano_data, dict) and 'erro' not in ano_data:
            for nome, info in ano_data.items():
                classes_cor.setdefault(nome, info.get('cor', '#aaa'))

    header = '<tr><th>Classe</th>' + ''.join(f'<th>{a}</th>' for a in anos) + '</tr>'
    rows   = ''

    for classe in sorted(classes_cor):
        cor   = classes_cor[classe]
        cells = ''
        for ano in anos:
            ano_data = lulc.get(ano, {})
            if isinstance(ano_data, dict) and classe in ano_data:
                ha = ano_data[classe].get('ha', 0)
                cells += f'<td>{ha:.2f}</td>'
            else:
                cells += '<td>–</td>'
        dot   = f'<span style="background:{cor};display:inline-block;width:12px;height:12px;margin-right:6px;border-radius:2px;vertical-align:middle"></span>'
        rows += f'<tr><td>{dot}{classe}</td>{cells}</tr>\n'

    return f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Extrato Temporal MapBiomas – Lyssa</title>
<style>
  body {{font-family:Arial,sans-serif;margin:30px;color:#222}}
  h1   {{color:#1a7f4b;margin-bottom:4px}}
  p    {{margin:4px 0}}
  table{{border-collapse:collapse;width:100%;margin-top:16px;font-size:.88em}}
  th,td{{border:1px solid #ccc;padding:6px 10px;text-align:left;white-space:nowrap}}
  th   {{background:#1a7f4b;color:#fff}}
  tr:nth-child(even){{background:#f5f5f5}}
  .footer{{margin-top:20px;font-size:.82em;color:#888}}
</style>
</head>
<body>
<h1>Extrato Temporal – Cobertura do Solo (MapBiomas Coleção 10.1)</h1>
<p><strong>Área do Imóvel:</strong> {area_total:.4f} ha |
   <strong>Resolução:</strong> {resolucao} m |
   <strong>Anos:</strong> {", ".join(anos)}</p>
<p><strong>Data:</strong> {data_hora}</p>
<table>
  <thead>{header}</thead>
  <tbody>{rows}</tbody>
</table>
<p class="footer">Fonte: MapBiomas Brasil Coleção 10.1 &nbsp;|&nbsp; Plugin Lyssa – QGIS</p>
</body>
</html>'''
