from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel,
    QTreeWidget, QTreeWidgetItem, QMessageBox, QLineEdit,
)
from PyQt5.QtCore import Qt


class AbaCamadas(QWidget):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        lay.addWidget(QLabel('<b>Camadas Externas</b>'))
        lay.addWidget(QLabel(
            'Clique duas vezes (ou selecione e clique em "Adicionar")\n'
            'para carregar a camada no projeto.'
        ))

        self._filtro = QLineEdit()
        self._filtro.setPlaceholderText('Filtrar camadas...')
        self._filtro.textChanged.connect(self._filtrar)
        lay.addWidget(self._filtro)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.itemDoubleClicked.connect(self._adicionar_item)
        lay.addWidget(self._tree)

        self._btn_add = QPushButton('Adicionar camada selecionada')
        self._btn_add.clicked.connect(self._adicionar_selecionada)
        lay.addWidget(self._btn_add)

        self._preencher()

    def _preencher(self):
        from ..modules.camadas_externas import CAMADAS_EXTERNAS
        self._tree.clear()
        grupos = {}

        for camada in CAMADAS_EXTERNAS:
            grupo = camada.get('grupo', 'Outros')
            if grupo not in grupos:
                it = QTreeWidgetItem(self._tree, [grupo])
                it.setExpanded(False)
                grupos[grupo] = it

            child = QTreeWidgetItem(grupos[grupo], [camada['titulo']])
            child.setData(0, Qt.UserRole, camada)
            tipo = camada.get('tipo', '').upper()
            child.setToolTip(0, f"[{tipo}] {camada.get('url', camada.get('arcgisQueryUrl', ''))}")

    def _filtrar(self, texto):
        texto = texto.lower()
        for i in range(self._tree.topLevelItemCount()):
            grp = self._tree.topLevelItem(i)
            algum = False
            for j in range(grp.childCount()):
                item = grp.child(j)
                vis  = texto in item.text(0).lower()
                item.setHidden(not vis)
                if vis:
                    algum = True
            grp.setHidden(not algum)
            if algum and texto:
                grp.setExpanded(True)

    def _adicionar_item(self, item, _col):
        info = item.data(0, Qt.UserRole)
        if info:
            self._carregar(info)

    def _adicionar_selecionada(self):
        for item in self._tree.selectedItems():
            info = item.data(0, Qt.UserRole)
            if info:
                self._carregar(info)

    def _carregar(self, info):
        from ..modules.camadas_externas import (
            adicionar_camada_wfs,
            adicionar_camada_wms,
            adicionar_camada_arcgis,
        )
        tipo = info.get('tipo', 'wfs')
        try:
            if tipo == 'wfs':
                adicionar_camada_wfs(info)
            elif tipo == 'wms':
                adicionar_camada_wms(info)
            elif tipo == 'arcgis':
                adicionar_camada_arcgis(info)
            else:
                QMessageBox.warning(
                    self, 'Tipo não suportado',
                    f"O tipo de camada '{tipo}' não é suportado nesta versão.",
                )
                return
            self.iface.mapCanvas().refresh()
        except Exception as exc:
            QMessageBox.critical(self, 'Erro ao carregar camada', str(exc))
