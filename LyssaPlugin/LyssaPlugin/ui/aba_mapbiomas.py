from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QSpinBox, QGroupBox, QTableWidget, QTableWidgetItem,
    QMessageBox, QProgressBar, QHeaderView,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor
from qgis.core import QgsProject, QgsVectorLayer


class _Worker(QThread):
    finished = pyqtSignal(dict, str)

    def __init__(self, geom_wkt, anos):
        super().__init__()
        self._wkt  = geom_wkt
        self._anos = anos

    def run(self):
        try:
            from ..modules.mapbiomas import analisar_cobertura
            resultado = analisar_cobertura(self._wkt, self._anos)
            self.finished.emit(resultado, '')
        except Exception as exc:
            self.finished.emit({}, str(exc))


class AbaMapBiomas(QWidget):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface      = iface
        self._resultado = None
        self._worker    = None
        self._build()
        self._atualizar_camadas()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        lay.addWidget(QLabel('<b>MapBiomas – Cobertura do Solo</b>'))
        lay.addWidget(QLabel(
            'Analisa a cobertura do solo dentro de uma geometria\n'
            'usando os COGs públicos (MapBiomas Coleção 10.1, 1985–2024).'
        ))

        # Camada
        grp = QGroupBox('Geometria de Análise')
        g   = QVBoxLayout(grp)
        g.addWidget(QLabel('Camada vetorial (polígono):'))
        self._combo_layer = QComboBox()
        g.addWidget(self._combo_layer)
        btn_r = QPushButton('↻  Atualizar')
        btn_r.clicked.connect(self._atualizar_camadas)
        g.addWidget(btn_r)
        lay.addWidget(grp)

        # Anos
        grp2 = QGroupBox('Período de Análise')
        g2   = QHBoxLayout(grp2)
        g2.addWidget(QLabel('Ano inicial:'))
        self._spin_ini = QSpinBox()
        self._spin_ini.setRange(1985, 2024)
        self._spin_ini.setValue(2019)
        g2.addWidget(self._spin_ini)
        g2.addWidget(QLabel('Ano final:'))
        self._spin_fim = QSpinBox()
        self._spin_fim.setRange(1985, 2024)
        self._spin_fim.setValue(2024)
        g2.addWidget(self._spin_fim)
        lay.addWidget(grp2)

        self._btn_anal = QPushButton('▶  Analisar Cobertura do Solo')
        self._btn_anal.clicked.connect(self._analisar)
        lay.addWidget(self._btn_anal)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        lay.addWidget(self._progress)

        self._lbl_info = QLabel('')
        lay.addWidget(self._lbl_info)

        lay.addWidget(QLabel('Resultados por classe (área em ha):'))
        self._tabela = QTableWidget()
        self._tabela.setEditTriggers(QTableWidget.NoEditTriggers)
        self._tabela.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        lay.addWidget(self._tabela)

        row_btns = QHBoxLayout()
        self._btn_html = QPushButton('Gerar HTML')
        self._btn_html.setEnabled(False)
        self._btn_html.clicked.connect(self._gerar_html)
        row_btns.addWidget(self._btn_html)

        self._btn_csv = QPushButton('Exportar CSV')
        self._btn_csv.setEnabled(False)
        self._btn_csv.clicked.connect(self._exportar_csv)
        row_btns.addWidget(self._btn_csv)
        lay.addLayout(row_btns)

    def _atualizar_camadas(self):
        self._combo_layer.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                self._combo_layer.addItem(layer.name(), layer)

    def _analisar(self):
        layer = self._combo_layer.currentData()
        if not layer:
            QMessageBox.warning(self, 'Aviso', 'Selecione uma camada.')
            return

        geom_wkt = self._unir_geom(layer)
        if not geom_wkt:
            QMessageBox.warning(self, 'Aviso', 'Camada sem geometrias válidas.')
            return

        ini = self._spin_ini.value()
        fim = self._spin_fim.value()
        if ini > fim:
            QMessageBox.warning(self, 'Aviso', 'Ano inicial deve ser ≤ ano final.')
            return

        anos = list(range(ini, fim + 1))
        if len(anos) > 10:
            ret = QMessageBox.question(
                self, 'Atenção',
                f'{len(anos)} anos selecionados. A análise pode demorar vários minutos.\nContinuar?',
                QMessageBox.Yes | QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                return

        self._btn_anal.setEnabled(False)
        self._btn_html.setEnabled(False)
        self._btn_csv.setEnabled(False)
        self._progress.setVisible(True)
        self._tabela.clear()
        self._lbl_info.setText(f'Consultando MapBiomas para {len(anos)} ano(s)...')

        self._worker = _Worker(geom_wkt, anos)
        self._worker.finished.connect(self._concluido)
        self._worker.start()

    def _unir_geom(self, layer):
        from qgis.core import QgsGeometry
        geoms = [
            f.geometry()
            for f in layer.getFeatures()
            if f.geometry() and not f.geometry().isEmpty()
        ]
        if not geoms:
            return None
        union = QgsGeometry.unaryUnion(geoms)
        return union.asWkt() if union and not union.isEmpty() else None

    def _concluido(self, resultado, erro):
        self._progress.setVisible(False)
        self._btn_anal.setEnabled(True)

        if erro:
            QMessageBox.critical(self, 'Erro MapBiomas', erro)
            self._lbl_info.setText('Erro na análise.')
            return

        self._resultado = resultado
        meta = resultado.get('meta', {})
        lulc = resultado.get('lulc', {})
        anos = sorted(lulc.keys())

        self._lbl_info.setText(
            f'Área: {meta.get("area_total_ha", 0):.2f} ha  |  '
            f'Anos: {anos[0]}–{anos[-1]}'
        )
        self._preencher_tabela(lulc, anos)
        self._btn_html.setEnabled(True)
        self._btn_csv.setEnabled(True)

    def _preencher_tabela(self, lulc, anos):
        classes_cor = {}
        for ano_data in lulc.values():
            if isinstance(ano_data, dict) and 'erro' not in ano_data and 'aviso' not in ano_data:
                for nome, info in ano_data.items():
                    classes_cor.setdefault(nome, info.get('cor', '#aaa'))

        nomes = sorted(classes_cor.keys())
        self._tabela.setRowCount(len(nomes))
        self._tabela.setColumnCount(len(anos) + 1)
        self._tabela.setHorizontalHeaderLabels(['Classe'] + anos)

        for row, nome in enumerate(nomes):
            item0 = QTableWidgetItem(nome)
            try:
                item0.setBackground(QColor(classes_cor[nome]).lighter(180))
            except Exception:
                pass
            self._tabela.setItem(row, 0, item0)

            for col, ano in enumerate(anos, start=1):
                ano_data = lulc.get(ano, {})
                if isinstance(ano_data, dict) and nome in ano_data:
                    ha = ano_data[nome].get('ha', 0)
                    self._tabela.setItem(row, col, QTableWidgetItem(f'{ha:.2f}'))
                else:
                    self._tabela.setItem(row, col, QTableWidgetItem('–'))

    def _gerar_html(self):
        if not self._resultado:
            return
        try:
            from ..modules.relatorio import gerar_extrato_temporal_html
            path = gerar_extrato_temporal_html(self._resultado)
            self._abrir_arquivo(path)
        except Exception as exc:
            QMessageBox.critical(self, 'Erro', str(exc))

    def _exportar_csv(self):
        if not self._resultado:
            return
        try:
            from ..modules.relatorio import exportar_csv_temporal
            path = exportar_csv_temporal(self._resultado)
            QMessageBox.information(self, 'Exportado', f'CSV salvo em:\n{path}')
            self._abrir_arquivo(path)
        except Exception as exc:
            QMessageBox.critical(self, 'Erro', str(exc))

    @staticmethod
    def _abrir_arquivo(path):
        import os, subprocess, sys
        try:
            if sys.platform == 'win32':
                os.startfile(path)
            elif sys.platform == 'darwin':
                subprocess.call(['open', path])
            else:
                subprocess.call(['xdg-open', path])
        except Exception:
            pass
