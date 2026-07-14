from PyQt5.QtWidgets import QDockWidget, QWidget, QVBoxLayout, QTabWidget

from .aba_importar_car import AbaImportarCAR
from .aba_area_benef   import AbaAreaBenef
from .aba_mapbiomas    import AbaMapBiomas
from .aba_camadas      import AbaCamadas
from .aba_relatorio    import AbaRelatorio


class PainelPrincipal(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__('Lyssa – Análise Ambiental', parent or iface.mainWindow())
        self.iface = iface
        self.setObjectName('LyssaPainelPrincipal')
        self.setMinimumWidth(380)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        tabs = QTabWidget()
        tabs.addTab(AbaImportarCAR(iface), 'Importar CAR')
        tabs.addTab(AbaAreaBenef(iface),   'Área Benef.')
        tabs.addTab(AbaMapBiomas(iface),   'MapBiomas')
        tabs.addTab(AbaCamadas(iface),     'Camadas')
        tabs.addTab(AbaRelatorio(iface),   'Relatório')

        layout.addWidget(tabs)
        self.setWidget(container)
