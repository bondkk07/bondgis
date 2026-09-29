from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QGroupBox, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from qgis.core import QgsProject, QgsVectorLayer

ESTADOS_BR = [
    '', 'AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO',
    'MA', 'MG', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'PR',
    'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO',
]


class _Worker(QThread):
    finished = pyqtSignal(object, float, str)

    def __init__(self, imovel, restritivas, estado, apf):
        super().__init__()
        self._imovel      = imovel
        self._restritivas = restritivas
        self._estado      = estado
        self._apf         = apf

    def run(self):
        try:
            from ..modules.area_beneficiavel import calcular_area_beneficiavel, calcular_area_ha
            layer = calcular_area_beneficiavel(
                self._imovel, self._restritivas, self._estado, self._apf
            )
            area = calcular_area_ha(layer) if layer else 0.0
            self.finished.emit(layer, area, '')
        except Exception as exc:
            self.finished.emit(None, 0.0, str(exc))


class AbaAreaBenef(QWidget):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface   = iface
        self._worker = None
        self._build()
        self._atualizar_camadas()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        lay.addWidget(QLabel('<b>Área Beneficiável</b>'))

        # Imóvel + estado
        grp = QGroupBox('Imóvel Rural')
        g   = QVBoxLayout(grp)
        g.addWidget(QLabel('Camada do imóvel:'))
        self._combo_imovel = QComboBox()
        g.addWidget(self._combo_imovel)
        row = QHBoxLayout()
        row.addWidget(QLabel('Estado (UF):'))
        self._combo_estado = QComboBox()
        self._combo_estado.addItems(ESTADOS_BR)
        row.addWidget(self._combo_estado)
        g.addLayout(row)
        lay.addWidget(grp)

        # Camadas restritivas
        grp2 = QGroupBox('Camadas Restritivas (selecione as que serão subtraídas)')
        g2   = QVBoxLayout(grp2)
        self._lista_rest = QListWidget()
        self._lista_rest.setSelectionMode(QListWidget.MultiSelection)
        self._lista_rest.setToolTip('Ctrl+clique para selecionar múltiplas camadas')
        g2.addWidget(self._lista_rest)
        lay.addWidget(grp2)

        # APF (MT)
        grp3 = QGroupBox('APF – SEMA-MT (interseção obrigatória para MT)')
        g3   = QVBoxLayout(grp3)
        g3.addWidget(QLabel('Camada APF (apenas para MT):'))
        self._combo_apf = QComboBox()
        g3.addWidget(self._combo_apf)
        lay.addWidget(grp3)

        btn_refresh = QPushButton('↻  Atualizar lista de camadas')
        btn_refresh.clicked.connect(self._atualizar_camadas)
        lay.addWidget(btn_refresh)

        self._btn_calc = QPushButton('▶  Calcular Área Beneficiável')
        self._btn_calc.clicked.connect(self._calcular)
        lay.addWidget(self._btn_calc)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        lay.addWidget(self._progress)

        self._lbl_result = QLabel('')
        lay.addWidget(self._lbl_result)

        lay.addStretch()

    def _atualizar_camadas(self):
        layers = [
            l for l in QgsProject.instance().mapLayers().values()
            if isinstance(l, QgsVectorLayer)
        ]
        self._combo_imovel.clear()
        self._lista_rest.clear()
        self._combo_apf.clear()
        self._combo_apf.addItem('(nenhuma)', None)

        for layer in layers:
            self._combo_imovel.addItem(layer.name(), layer)
            item = QListWidgetItem(layer.name())
            item.setData(Qt.UserRole, layer)
            self._lista_rest.addItem(item)
            self._combo_apf.addItem(layer.name(), layer)

    def _calcular(self):
        imovel = self._combo_imovel.currentData()
        if not imovel:
            QMessageBox.warning(self, 'Aviso', 'Selecione a camada do imóvel.')
            return

        restritivas = [
            item.data(Qt.UserRole)
            for item in self._lista_rest.selectedItems()
        ]
        estado = self._combo_estado.currentText().strip()
        apf    = self._combo_apf.currentData()

        self._btn_calc.setEnabled(False)
        self._progress.setVisible(True)
        self._lbl_result.setText('')

        self._worker = _Worker(imovel, restritivas, estado, apf)
        self._worker.finished.connect(self._concluido)
        self._worker.start()

    def _concluido(self, layer, area, erro):
        self._progress.setVisible(False)
        self._btn_calc.setEnabled(True)

        if erro:
            QMessageBox.critical(self, 'Erro', erro)
            return
        if layer is None:
            QMessageBox.warning(
                self, 'Resultado vazio',
                'A área beneficiável ficou vazia após aplicar as restrições.'
            )
            return

        self._lbl_result.setText(
            f'<span style="color:#1a7f4b;font-weight:bold">'
            f'✔ Área Beneficiável: {area:.4f} ha</span>'
        )
        self.iface.mapCanvas().refresh()
