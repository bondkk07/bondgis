"""
Aba de Verificação de Sobreposição / Extrato Ambiental.

Equivalente ao botão "Verificar Sobreposição" do WebGIS LiroGis:
consulta camadas externas (WFS/ArcGIS) e as Listas MCR/PRODES MMA
para identificar sobreposição geométrica real com o imóvel selecionado.
"""

import os
import subprocess
import sys

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QGroupBox, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QMessageBox, QLineEdit,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QSizePolicy, QScrollArea,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QBrush, QFont
from qgis.core import QgsProject, QgsVectorLayer


# ---------------------------------------------------------------------------
# Worker QThread – executa toda a verificação sem bloquear a UI
# ---------------------------------------------------------------------------
class _VerWorker(QThread):
    progresso = pyqtSignal(int, str)    # (pct, mensagem)
    concluido = pyqtSignal(list)        # lista de resultados
    falha     = pyqtSignal(str)         # mensagem de erro

    def __init__(self, imovel_wkt, bbox, codigo_car,
                 camadas_externas, camadas_locais):
        super().__init__()
        self._wkt    = imovel_wkt
        self._bbox   = bbox
        self._car    = codigo_car
        self._ext    = camadas_externas
        self._locais = camadas_locais

    def run(self):
        try:
            from ..modules.verificar_sobreposicao import verificar_sobreposicao
            resultados = verificar_sobreposicao(
                self._wkt, self._bbox, self._car,
                self._ext, self._locais,
                callback=self.progresso.emit,
            )
            self.concluido.emit(resultados)
        except Exception as exc:
            self.falha.emit(str(exc))


# ---------------------------------------------------------------------------
# Aba principal
# ---------------------------------------------------------------------------
class AbaRelatorio(QWidget):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface      = iface
        self._worker    = None
        self._resultados = []
        self._area_ha   = 0.0
        self._build()
        self._atualizar_projeto()

    # ------------------------------------------------------------------
    # Construção da interface
    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        root.addWidget(QLabel('<b>Verificar Sobreposição / Extrato Ambiental</b>'))

        # ── Imóvel ──────────────────────────────────────────────────
        grp_im = QGroupBox('Imóvel Rural')
        g_im   = QVBoxLayout(grp_im)

        h_im = QHBoxLayout()
        h_im.addWidget(QLabel('Camada do imóvel:'))
        self._combo_imovel = QComboBox()
        self._combo_imovel.currentIndexChanged.connect(self._ao_mudar_imovel)
        h_im.addWidget(self._combo_imovel, 1)
        g_im.addLayout(h_im)

        h_car = QHBoxLayout()
        h_car.addWidget(QLabel('Código CAR:'))
        self._edit_car = QLineEdit()
        self._edit_car.setPlaceholderText('Ex.: RO-1100015-XXXXXXX  (preenchido automático)')
        h_car.addWidget(self._edit_car, 1)
        g_im.addLayout(h_car)

        self._lbl_area = QLabel('Área do imóvel: —')
        self._lbl_area.setStyleSheet('color:#555;font-size:12px')
        g_im.addWidget(self._lbl_area)

        root.addWidget(grp_im)

        # ── Camadas externas ─────────────────────────────────────────
        grp_ext = QGroupBox('Camadas Externas a Consultar')
        g_ext   = QVBoxLayout(grp_ext)
        g_ext.setSpacing(4)

        g_ext.addWidget(QLabel(
            'Marque as camadas que devem ser verificadas por sobreposição:'
        ))

        h_sel = QHBoxLayout()
        btn_all  = QPushButton('Marcar todas')
        btn_none = QPushButton('Desmarcar todas')
        btn_all.clicked.connect(lambda: self._marcar_todas(True))
        btn_none.clicked.connect(lambda: self._marcar_todas(False))
        h_sel.addWidget(btn_all)
        h_sel.addWidget(btn_none)
        h_sel.addStretch()
        g_ext.addLayout(h_sel)

        self._tree_ext = QTreeWidget()
        self._tree_ext.setHeaderHidden(True)
        self._tree_ext.setMinimumHeight(130)
        g_ext.addWidget(self._tree_ext)

        root.addWidget(grp_ext)

        # ── Camadas locais do projeto ─────────────────────────────────
        grp_loc = QGroupBox('Camadas Locais (projeto QGIS) – opcional')
        g_loc   = QVBoxLayout(grp_loc)
        g_loc.addWidget(QLabel(
            'Selecione camadas já carregadas no projeto para verificar:'
        ))
        self._lista_locais = QListWidget()
        self._lista_locais.setSelectionMode(QListWidget.MultiSelection)
        self._lista_locais.setMaximumHeight(80)
        g_loc.addWidget(self._lista_locais)
        root.addWidget(grp_loc)

        # ── Botão de atualização ──────────────────────────────────────
        btn_ref = QPushButton('↻  Atualizar camadas do projeto')
        btn_ref.clicked.connect(self._atualizar_projeto)
        root.addWidget(btn_ref)

        # ── Progresso e botão principal ───────────────────────────────
        self._btn_verificar = QPushButton('🔍  Verificar Sobreposição')
        self._btn_verificar.setMinimumHeight(34)
        font = QFont()
        font.setBold(True)
        self._btn_verificar.setFont(font)
        self._btn_verificar.setStyleSheet(
            'QPushButton{background:#1a7f4b;color:#fff;border-radius:4px}'
            'QPushButton:hover{background:#15693e}'
            'QPushButton:disabled{background:#aaa}'
        )
        self._btn_verificar.clicked.connect(self._verificar)
        root.addWidget(self._btn_verificar)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._lbl_status = QLabel('')
        self._lbl_status.setStyleSheet('color:#555;font-size:12px')
        root.addWidget(self._lbl_status)

        # ── Resultados ────────────────────────────────────────────────
        self._tabela = QTableWidget()
        self._tabela.setColumnCount(4)
        self._tabela.setHorizontalHeaderLabels(['Camada', 'Status', 'Qtd', 'Detalhes'])
        self._tabela.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tabela.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._tabela.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._tabela.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._tabela.setEditTriggers(QTableWidget.NoEditTriggers)
        self._tabela.setSelectionBehavior(QTableWidget.SelectRows)
        self._tabela.verticalHeader().setVisible(False)
        self._tabela.setVisible(False)
        root.addWidget(self._tabela)

        # ── Resumo dos resultados ─────────────────────────────────────
        self._lbl_resumo = QLabel('')
        self._lbl_resumo.setVisible(False)
        root.addWidget(self._lbl_resumo)

        # ── Botão Gerar HTML ─────────────────────────────────────────
        self._btn_html = QPushButton('📄  Gerar Relatório HTML')
        self._btn_html.setEnabled(False)
        self._btn_html.clicked.connect(self._gerar_html)
        root.addWidget(self._btn_html)

        root.addStretch()

        # Preenche a árvore de camadas externas (uma vez, estática)
        self._preencher_tree_externas()

    # ------------------------------------------------------------------
    # Preenchimento da árvore de camadas externas
    # ------------------------------------------------------------------
    def _preencher_tree_externas(self):
        from ..modules.camadas_externas import CAMADAS_EXTERNAS
        self._tree_ext.clear()
        grupos = {}

        for camada in CAMADAS_EXTERNAS:
            # Pula rasters e camadas marcadas para ignorar na sobreposição
            if camada.get('tipo') == 'wms':
                continue
            if camada.get('ignorar_sobreposicao'):
                continue

            grupo = camada.get('grupo', 'Outros')
            if grupo not in grupos:
                grp_item = QTreeWidgetItem(self._tree_ext, [grupo])
                grp_item.setExpanded(True)
                grupos[grupo] = grp_item

            child = QTreeWidgetItem(grupos[grupo], [camada['titulo']])
            child.setCheckState(0, Qt.Checked)
            child.setData(0, Qt.UserRole, camada)
            tipo = camada.get('tipo', '').upper()
            child.setToolTip(0, f'[{tipo}] {camada.get("url", "")}')

    def _marcar_todas(self, marcar: bool):
        estado = Qt.Checked if marcar else Qt.Unchecked
        for i in range(self._tree_ext.topLevelItemCount()):
            grp = self._tree_ext.topLevelItem(i)
            for j in range(grp.childCount()):
                grp.child(j).setCheckState(0, estado)

    # ------------------------------------------------------------------
    # Atualização de camadas do projeto
    # ------------------------------------------------------------------
    def _atualizar_projeto(self):
        layers = [
            l for l in QgsProject.instance().mapLayers().values()
            if isinstance(l, QgsVectorLayer)
        ]
        self._combo_imovel.blockSignals(True)
        prev = self._combo_imovel.currentText()
        self._combo_imovel.clear()
        for layer in layers:
            self._combo_imovel.addItem(layer.name(), layer)
        idx = self._combo_imovel.findText(prev)
        if idx >= 0:
            self._combo_imovel.setCurrentIndex(idx)
        self._combo_imovel.blockSignals(False)
        self._ao_mudar_imovel()

        self._lista_locais.clear()
        for layer in layers:
            item = QListWidgetItem(layer.name())
            item.setData(Qt.UserRole, layer)
            self._lista_locais.addItem(item)

    def _ao_mudar_imovel(self):
        layer = self._combo_imovel.currentData()
        if not layer:
            return
        try:
            from ..modules.verificar_sobreposicao import obter_codigo_car
            car = obter_codigo_car(layer)
            self._edit_car.setText(car)
        except Exception:
            pass

        try:
            from ..modules.area_beneficiavel import calcular_area_ha
            self._area_ha = calcular_area_ha(layer)
            self._lbl_area.setText(f'Área do imóvel: {self._area_ha:.4f} ha')
        except Exception:
            self._area_ha = 0.0
            self._lbl_area.setText('Área do imóvel: —')

    # ------------------------------------------------------------------
    # Verificação principal
    # ------------------------------------------------------------------
    def _verificar(self):
        imovel_layer = self._combo_imovel.currentData()
        if not imovel_layer:
            QMessageBox.warning(self, 'Aviso', 'Selecione a camada do imóvel.')
            return

        # Coletar camadas externas marcadas
        camadas_ext = []
        for i in range(self._tree_ext.topLevelItemCount()):
            grp = self._tree_ext.topLevelItem(i)
            for j in range(grp.childCount()):
                child = grp.child(j)
                if child.checkState(0) == Qt.Checked:
                    info = child.data(0, Qt.UserRole)
                    if info:
                        camadas_ext.append(info)

        if not camadas_ext:
            QMessageBox.warning(
                self, 'Aviso',
                'Nenhuma camada externa selecionada para verificação.',
            )
            return

        # Extrair código CAR (da caixa de texto, que pode ter sido editado)
        codigo_car = self._edit_car.text().strip().upper()

        # Preparar geometria e bbox na thread principal (usa PyQGIS)
        try:
            from ..modules.verificar_sobreposicao import (
                preparar_geom_imovel, preparar_camada_local,
            )
            imovel_wkt, bbox = preparar_geom_imovel(imovel_layer)
            if not imovel_wkt:
                QMessageBox.warning(self, 'Aviso', 'Imóvel sem geometrias válidas.')
                return
        except Exception as exc:
            QMessageBox.critical(self, 'Erro', f'Erro ao preparar geometria:\n{exc}')
            return

        # Preparar camadas locais selecionadas
        camadas_locais = []
        for item in self._lista_locais.selectedItems():
            layer = item.data(Qt.UserRole)
            if layer and layer.isValid():
                try:
                    camadas_locais.append(preparar_camada_local(layer))
                except Exception:
                    pass

        # Iniciar worker
        self._resultados = []
        self._btn_verificar.setEnabled(False)
        self._btn_html.setEnabled(False)
        self._tabela.setVisible(False)
        self._tabela.setRowCount(0)
        self._lbl_resumo.setVisible(False)
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._lbl_status.setText('Iniciando verificação...')

        self._worker = _VerWorker(imovel_wkt, bbox, codigo_car,
                                  camadas_ext, camadas_locais)
        self._worker.progresso.connect(self._ao_progresso)
        self._worker.concluido.connect(self._ao_concluir)
        self._worker.falha.connect(self._ao_falha)
        self._worker.start()

    # ------------------------------------------------------------------
    # Slots do worker
    # ------------------------------------------------------------------
    def _ao_progresso(self, pct, msg):
        self._progress.setValue(pct)
        self._lbl_status.setText(msg)

    def _ao_concluir(self, resultados):
        self._progress.setVisible(False)
        self._btn_verificar.setEnabled(True)
        self._resultados = resultados
        self._preencher_tabela(resultados)
        self._atualizar_resumo(resultados)
        self._tabela.setVisible(True)
        self._lbl_resumo.setVisible(True)
        self._btn_html.setEnabled(True)
        self._lbl_status.setText('Verificação concluída.')

    def _ao_falha(self, msg):
        self._progress.setVisible(False)
        self._btn_verificar.setEnabled(True)
        self._lbl_status.setText('Erro durante a verificação.')
        QMessageBox.critical(self, 'Erro na verificação', msg)

    # ------------------------------------------------------------------
    # Tabela de resultados
    # ------------------------------------------------------------------
    def _preencher_tabela(self, resultados):
        # Ordena: sobreposição → erro → sem sobreposição
        def sort_key(r):
            if r.get('sobreposicao'):
                return 0
            if r.get('erroConsulta'):
                return 1
            return 2

        ordenados = sorted(resultados, key=sort_key)
        self._tabela.setRowCount(len(ordenados))

        for row, r in enumerate(ordenados):
            self._tabela.setItem(row, 0, QTableWidgetItem(r.get('camada', '')))

            status  = r.get('statusTexto', '—')
            it_stat = QTableWidgetItem(status)
            it_stat.setTextAlignment(Qt.AlignCenter)
            if r.get('sobreposicao'):
                it_stat.setForeground(QBrush(QColor('#c0392b')))
            elif r.get('erroConsulta'):
                it_stat.setForeground(QBrush(QColor('#d68910')))
            else:
                it_stat.setForeground(QBrush(QColor('#1a7f4b')))
            self._tabela.setItem(row, 1, it_stat)

            count = r.get('count', 0)
            it_cnt = QTableWidgetItem(str(count) if count else '–')
            it_cnt.setTextAlignment(Qt.AlignCenter)
            self._tabela.setItem(row, 2, it_cnt)

            detalhes = r.get('detalhes', [])
            self._tabela.setItem(row, 3, QTableWidgetItem('; '.join(detalhes)))

            # Destaca linha com sobreposição
            if r.get('sobreposicao'):
                for col in range(4):
                    item = self._tabela.item(row, col)
                    if item:
                        item.setBackground(QBrush(QColor('#fce8e6')))

        self._tabela.resizeRowsToContents()

    def _atualizar_resumo(self, resultados):
        com = sum(1 for r in resultados if r.get('sobreposicao'))
        err = sum(1 for r in resultados if r.get('erroConsulta'))
        sem = sum(1 for r in resultados if not r.get('sobreposicao') and not r.get('erroConsulta'))
        total = len(resultados)

        partes = [
            f'<span style="color:#c0392b;font-weight:bold">{com} com sobreposição</span>',
            f'<span style="color:#1a7f4b">{sem} sem sobreposição</span>',
        ]
        if err:
            partes.append(f'<span style="color:#d68910">{err} não verificadas</span>')
        partes.append(f'{total} consultadas no total')

        self._lbl_resumo.setText(' &nbsp;|&nbsp; '.join(partes))

    # ------------------------------------------------------------------
    # Geração do relatório HTML
    # ------------------------------------------------------------------
    def _gerar_html(self):
        if not self._resultados:
            return
        try:
            from ..modules.relatorio import gerar_relatorio_sobreposicao_html
            path = gerar_relatorio_sobreposicao_html(
                self._resultados,
                codigo_car=self._edit_car.text().strip(),
                area_imovel_ha=self._area_ha,
                resultado_mapbiomas=None,
            )
            QMessageBox.information(
                self, 'Relatório gerado',
                f'Arquivo salvo em:\n{path}\n\nAbrindo no navegador...',
            )
            _abrir(path)
        except Exception as exc:
            QMessageBox.critical(self, 'Erro', str(exc))


# ---------------------------------------------------------------------------
# Utilitário – abrir arquivo no programa padrão
# ---------------------------------------------------------------------------
def _abrir(path):
    try:
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.call(['open', path])
        else:
            subprocess.call(['xdg-open', path])
    except Exception:
        pass
