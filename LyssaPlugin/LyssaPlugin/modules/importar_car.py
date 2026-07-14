import os
import tempfile
import zipfile

CAR_CAMADAS = {
    'APP':                    'APP',
    'AREA_IMOVEL':            'Área do Imóvel',
    'RESERVA_LEGAL':          'Reserva Legal',
    'VEGETACAO_NATIVA':       'Vegetação Nativa',
    'HIDROGRAFIA':            'Hidrografia',
    'NASCENTES_VEREDAS':      'Nascentes e Veredas',
    'BANHADO':                'Banhado',
    'USO_RESTRITO':           'Uso Restrito',
    'SERVIDAO_ADMINISTRATIVA':'Servidão Administrativa',
    'AREA_CONSOLIDADA':       'Área Consolidada',
    'DESMATAMENTO_EMBARGO':   'Desmatamento / Embargo',
    'TOPO_MORRO':             'Topo de Morro',
}


def extrair_shapefiles_zip(zip_path: str) -> list:
    """Extrai o ZIP do SICAR para um diretório temporário persistente.

    Seguro para chamar em QThread (sem QGIS).

    Returns:
        Lista de {'path': str, 'nome': str} para cada shapefile encontrado.
    """
    temp_dir = tempfile.mkdtemp(prefix='lyssa_zip_')
    _extrair_recursivo(zip_path, temp_dir)
    resultado = []
    for shp_path in sorted(_listar_shapefiles(temp_dir)):
        resultado.append({'path': shp_path, 'nome': _nome_camada(shp_path)})
    return resultado


def carregar_shapefiles_no_qgis(shapefiles: list) -> list:
    """Carrega shapefiles no projeto QGIS.

    DEVE ser chamado na thread principal.

    Args:
        shapefiles: Lista de {'path', 'nome'} retornada por extrair_shapefiles_zip.

    Returns:
        Lista de nomes das camadas adicionadas.
    """
    from qgis.core import QgsVectorLayer, QgsProject, QgsCoordinateReferenceSystem

    nomes = []
    for item in shapefiles:
        layer = QgsVectorLayer(item['path'], item['nome'], 'ogr')
        if layer.isValid():
            crs = layer.crs()
            if not crs.isValid() or crs.authid() == '':
                layer.setCrs(QgsCoordinateReferenceSystem('EPSG:4674'))
            QgsProject.instance().addMapLayer(layer)
            nomes.append(item['nome'])
    return nomes


def _extrair_recursivo(zip_path: str, dest: str):
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(dest)

    for root, _, files in os.walk(dest):
        for fname in files:
            if fname.lower().endswith('.zip'):
                inner = os.path.join(root, fname)
                inner_dest = os.path.splitext(inner)[0]
                os.makedirs(inner_dest, exist_ok=True)
                try:
                    with zipfile.ZipFile(inner, 'r') as inner_zf:
                        inner_zf.extractall(inner_dest)
                except (zipfile.BadZipFile, Exception):
                    pass


def _listar_shapefiles(base: str) -> list:
    paths = []
    for root, _, files in os.walk(base):
        for fname in files:
            if fname.lower().endswith('.shp'):
                paths.append(os.path.join(root, fname))
    return paths


def _nome_camada(shp_path: str) -> str:
    base = os.path.splitext(os.path.basename(shp_path))[0].upper()
    for chave, nome in CAR_CAMADAS.items():
        if chave in base:
            return nome
    return os.path.splitext(os.path.basename(shp_path))[0]


