"""
Aba de importação do CAR – dois métodos:
  1. Busca online por número CAR no SICAR (GeoServer oficial).
  2. Importação de arquivo ZIP local do SICAR.
"""

import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QLineEdit, QListWidget, QMessageBox,
    QProgressBar, QGroupBox, QFrame,
)
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QFont


# ---------------------------------------------------------------------------
# Worker – busca completa no SICAR: área do imóvel + camadas subsidiárias
# Tudo via urllib + SSL permissivo; não usa Qt Network → seguro em QThread
# ---------------------------------------------------------------------------
class _SicarWorker(QThread):
    progresso = pyqtSignal(str)
    concluido = pyqtSignal(list, str)   # (todos_os_resultados, erro_fatal)

    def __init__(self, codigo_car):
        super().__init__()
        self._car = codigo_car

    def run(self):
        from ..modules.sicar_api import buscar_area_imovel, buscar_camadas_consulta

        # ── Fase 1: área do imóvel ────────────────────────────────────────
        self.progresso.emit('Buscando área do imóvel no GeoServer SICAR...')
        try:
            area = buscar_area_imovel(self._car)
            resultados = [area]
        except Exception as exc:
            self.concluido.emit([], str(exc))
            return

        # ── Fase 2: camadas subsidiárias ──────────────────────────────────
        self.progresso.emit('Área encontrada. Buscando camadas subsidiárias...')
        try:
            subsidiarias = buscar_camadas_consulta(
                self._car, callback=self.progresso.emit
            )
            resultados.extend(subsidiarias)
        except Exception as exc:
            # Subsidiárias falhando não é fatal: emite o que tem + aviso
            self.concluido.emit(resultados, str(exc))
            return

        self.concluido.emit(resultados, '')


# ---------------------------------------------------------------------------
# Worker – extração de ZIP local (sem QGIS, thread-safe)
# ---------------------------------------------------------------------------
class _ZipWorker(QThread):
    # emite lista de {'path', 'nome'} (shapefiles extraídos) + mensagem de erro
    finished = pyqtSignal(list, str)

    def __init__(self, zip_path):
        super().__init__()
        self._zip = zip_path

    def run(self):
        try:
            from ..modules.importar_car import extrair_shapefiles_zip
            shapefiles = extrair_shapefiles_zip(self._zip)
            self.finished.emit(shapefiles, '')
        except Exception as exc:
            self.finished.emit([], str(exc))


# ---------------------------------------------------------------------------
# Aba principal
# ---------------------------------------------------------------------------
class AbaImportarCAR(QWidget):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface         = iface
        self._sicar_worker = None
        self._zip_worker   = None
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        lay.addWidget(QLabel('<b>Importar CAR (SICAR)</b>'))

        # ── Método 1: Busca por número CAR (online) ──────────────────────
        grp1 = QGroupBox('Método 1 – Buscar por Número CAR (online)')
        g1   = QVBoxLayout(grp1)
        g1.addWidget(QLabel(
            'Informe o código completo do CAR.\n'
            'Os dados são buscados nos serviços WFS públicos do SICAR/MMA.'
        ))

        h_car = QHBoxLayout()
        self._edit_car = QLineEdit()
        self._edit_car.setPlaceholderText('Ex.: MT-5105101-830D812491D3484A91E747C32107BD0F')
        h_car.addWidget(self._edit_car)
        g1.addLayout(h_car)

        self._btn_buscar = QPushButton('🌐  Buscar CAR no SICAR')
        self._btn_buscar.setMinimumHeight(30)
        font = QFont()
        font.setBold(True)
        self._btn_buscar.setFont(font)
        self._btn_buscar.setStyleSheet(
            'QPushButton{background:#1a7f4b;color:#fff;border-radius:4px}'
            'QPushButton:hover{background:#15693e}'
            'QPushButton:disabled{background:#aaa}'
        )
        self._btn_buscar.clicked.connect(self._buscar_sicar)
        g1.addWidget(self._btn_buscar)

        self._progress_sicar = QProgressBar()
        self._progress_sicar.setRange(0, 0)
        self._progress_sicar.setVisible(False)
        g1.addWidget(self._progress_sicar)

        self._lbl_sicar = QLabel('')
        self._lbl_sicar.setStyleSheet('color:#555;font-size:12px')
        g1.addWidget(self._lbl_sicar)

        g1.addWidget(QLabel('Camadas adicionadas ao projeto:'))
        self._lista_sicar = QListWidget()
        self._lista_sicar.setMaximumHeight(80)
        g1.addWidget(self._lista_sicar)

        lay.addWidget(grp1)

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        lay.addWidget(sep)

        # ── Método 2: Importar ZIP local ──────────────────────────────────
        grp2 = QGroupBox('Método 2 – Importar arquivo ZIP do SICAR (local)')
        g2   = QVBoxLayout(grp2)
        g2.addWidget(QLabel(
            'Selecione o arquivo .zip exportado do portal SICAR.\n'
            'Os shapefiles contidos serão adicionados ao projeto QGIS.'
        ))

        row_zip = QHBoxLayout()
        self._edit_zip = QLineEdit()
        self._edit_zip.setPlaceholderText('Caminho do arquivo .zip...')
        self._edit_zip.setReadOnly(True)
        row_zip.addWidget(self._edit_zip)
        btn_browse = QPushButton('...')
        btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(self._browse)
        row_zip.addWidget(btn_browse)
        g2.addLayout(row_zip)

        self._btn_import = QPushButton('▶  Importar ZIP')
        self._btn_import.setEnabled(False)
        self._btn_import.clicked.connect(self._importar_zip)
        g2.addWidget(self._btn_import)

        self._progress_zip = QProgressBar()
        self._progress_zip.setRange(0, 0)
        self._progress_zip.setVisible(False)
        g2.addWidget(self._progress_zip)

        g2.addWidget(QLabel('Camadas adicionadas:'))
        self._lista_zip = QListWidget()
        self._lista_zip.setMaximumHeight(80)
        g2.addWidget(self._lista_zip)

        lay.addWidget(grp2)
        lay.addStretch()

    # ------------------------------------------------------------------
    # Busca no SICAR (online) – worker único, não bloqueia a UI
    # ------------------------------------------------------------------
    def _buscar_sicar(self):
        codigo = self._edit_car.text().strip().upper()
        if not codigo:
            QMessageBox.warning(self, 'Aviso', 'Informe o código CAR.')
            return

        self._btn_buscar.setEnabled(False)
        self._progress_sicar.setVisible(True)
        self._lbl_sicar.setText('Conectando ao GeoServer SICAR...')
        self._lista_sicar.clear()

        self._sicar_worker = _SicarWorker(codigo)
        self._sicar_worker.progresso.connect(self._lbl_sicar.setText)
        self._sicar_worker.concluido.connect(self._sicar_concluido)
        self._sicar_worker.start()

    def _sicar_concluido(self, resultados, erro_fatal):
        self._progress_sicar.setVisible(False)
        self._btn_buscar.setEnabled(True)

        if not resultados:
            self._lbl_sicar.setText('Imóvel não encontrado.')
            QMessageBox.critical(
                self, 'Erro ao buscar no SICAR',
                f'{erro_fatal}\n\n'
                'Se o serviço estiver indisponível, use o Método 2 (importar ZIP).',
            )
            return

        # Carrega no QGIS na thread principal
        try:
            from ..modules.sicar_api import carregar_no_qgis
            nomes = carregar_no_qgis(resultados)
            self._lista_sicar.addItems(nomes)
            msg = f'{len(nomes)} camada(s) adicionada(s) ao projeto.'
            if erro_fatal:
                msg += f'\nAtenção: algumas camadas subsidiárias falharam.'
            self._lbl_sicar.setText(msg)
            QMessageBox.information(self, 'Busca concluída', msg)
        except Exception as exc:
            QMessageBox.critical(self, 'Erro ao carregar camadas', str(exc))

    # ------------------------------------------------------------------
    # Importação de ZIP local
    # ------------------------------------------------------------------
    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Selecionar ZIP do CAR', '', 'Arquivo ZIP (*.zip)'
        )
        if path:
            self._edit_zip.setText(path)
            self._btn_import.setEnabled(True)

    def _importar_zip(self):
        zip_path = self._edit_zip.text()
        if not os.path.isfile(zip_path):
            QMessageBox.warning(self, 'Erro', 'Arquivo não encontrado.')
            return

        self._btn_import.setEnabled(False)
        self._progress_zip.setVisible(True)
        self._lista_zip.clear()

        self._zip_worker = _ZipWorker(zip_path)
        self._zip_worker.finished.connect(self._zip_concluido)
        self._zip_worker.start()

    def _zip_concluido(self, shapefiles, erro):
        self._progress_zip.setVisible(False)
        self._btn_import.setEnabled(True)

        if erro:
            QMessageBox.critical(self, 'Erro ao importar CAR', erro)
            return
        if not shapefiles:
            QMessageBox.warning(self, 'Aviso', 'Nenhum shapefile encontrado no ZIP.')
            return

        # Carrega no QGIS na thread principal (seguro)
        try:
            from ..modules.importar_car import carregar_shapefiles_no_qgis
            nomes = carregar_shapefiles_no_qgis(shapefiles)
        except Exception as exc:
            QMessageBox.critical(self, 'Erro ao carregar camadas', str(exc))
            return

        self._lista_zip.addItems(nomes)
        QMessageBox.information(
            self, 'Importação concluída',
            f'{len(nomes)} camada(s) adicionada(s) ao projeto.'
        )
