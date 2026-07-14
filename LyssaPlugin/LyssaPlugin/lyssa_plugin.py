import os
from PyQt5.QtWidgets import QAction
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt


class LyssaPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self._dock = None
        self._action = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        self._action = QAction(icon, 'Lyssa – Análise Ambiental', self.iface.mainWindow())
        self._action.setCheckable(True)
        self._action.triggered.connect(self._toggle_dock)
        self.iface.addPluginToMenu('LyssaPlugin', self._action)
        self.iface.addToolBarIcon(self._action)

    def unload(self):
        self.iface.removePluginMenu('LyssaPlugin', self._action)
        self.iface.removeToolBarIcon(self._action)
        if self._dock is not None:
            self.iface.removeDockWidget(self._dock)
            self._dock.deleteLater()
            self._dock = None

    def _toggle_dock(self, checked):
        if self._dock is None:
            from .ui.painel_principal import PainelPrincipal
            self._dock = PainelPrincipal(self.iface)
            self._dock.visibilityChanged.connect(self._action.setChecked)
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self._dock)
        else:
            self._dock.setVisible(checked)
