"""Modelos de entrada/saída (Pydantic) da API BondGis."""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LayerType(str, Enum):
    rgb = "rgb"
    ndvi = "ndvi"
    ndre = "ndre"
    ndwi = "ndwi"
    ndmi = "ndmi"
    bsi = "bsi"
    nbr = "nbr"           # queimadas (Normalized Burn Ratio)
    classificacao = "classificacao"


class CompositeMode(str, Enum):
    recent = "recent"     # imagem mais recente do período
    median = "median"     # composição por mediana do período


class BaseAOIRequest(BaseModel):
    """A área de interesse aceita qualquer GeoJSON: Geometry, Feature ou
    FeatureCollection (Polygon/MultiPolygon)."""
    aoi: Dict[str, Any] = Field(..., description="GeoJSON da propriedade")
    date_start: str = Field(..., description="Data inicial ISO (YYYY-MM-DD)")
    date_end: str = Field(..., description="Data final ISO (YYYY-MM-DD)")
    max_cloud: float = Field(60.0, ge=0, le=100, description="Nuvens máx. (%)")
    mode: CompositeMode = CompositeMode.recent


class TilesRequest(BaseAOIRequest):
    layer: LayerType = LayerType.rgb


class LegendEntry(BaseModel):
    label: str
    color: str
    criterio: Optional[str] = None   # regra espectral que define a classe


class TilesResponse(BaseModel):
    layer: str
    tile_url: str
    attribution: str
    image_date: Optional[str] = None
    n_images: int = 0
    vis: Dict[str, Any] = {}
    legend: List[LegendEntry] = []
    # Para camadas de índice (NDVI, NDRE…): barra de cor contínua e o que ela mede.
    escala: Optional[Dict[str, Any]] = None


class DatesRequest(BaseAOIRequest):
    pass


class DateEntry(BaseModel):
    date: str
    cloud: Optional[float] = None


class DatesResponse(BaseModel):
    dates: List[DateEntry] = []


class TimeSeriesRequest(BaseAOIRequest):
    index: LayerType = LayerType.ndvi


class TimeSeriesPoint(BaseModel):
    date: str
    value: Optional[float] = None


class TimeSeriesResponse(BaseModel):
    index: str
    points: List[TimeSeriesPoint] = []


class HealthResponse(BaseModel):
    status: str
    earth_engine: bool
    project: Optional[str] = None
    message: Optional[str] = None


# ── ANALISAR ÁREA (pipeline unificado) ────────────────────────────────────
class TipoAnalise(str, Enum):
    completa = "completa"
    auditoria = "auditoria"
    conformidade = "conformidade"
    vegetacao = "vegetacao"


class CamadasCAR(BaseModel):
    """Camadas oficiais do CAR (GeoJSON); todas opcionais exceto o limite."""
    app: Optional[Dict[str, Any]] = None
    reserva_legal: Optional[Dict[str, Any]] = None
    vegetacao_nativa: Optional[Dict[str, Any]] = None
    area_consolidada: Optional[Dict[str, Any]] = None
    servidao: Optional[Dict[str, Any]] = None
    uso_restrito: Optional[Dict[str, Any]] = None
    hidrografia: Optional[Dict[str, Any]] = None


class AnaliseRequest(BaseModel):
    aoi: Dict[str, Any] = Field(..., description="GeoJSON do limite do imóvel")
    tipo: TipoAnalise = TipoAnalise.completa
    camadas: CamadasCAR = CamadasCAR()
    date_start: str
    date_end: str
    max_cloud: float = Field(60.0, ge=0, le=100)
    mode: CompositeMode = CompositeMode.median


class AnaliseResponse(BaseModel):
    tipo: str
    n_images: int
    image_date: Optional[str] = None
    area_total_ha: float
    camadas_recebidas: Dict[str, bool]
    modulos: Dict[str, Any]
    geojson_divergencias: Dict[str, Any]


# ── EROSIVIDADE (fator R da USLE) ─────────────────────────────────────────
class ChuvaManual(BaseModel):
    """Override manual: 12 médias mensais (jan→dez) e o total anual (mm)."""
    meses: List[float] = Field(..., description="12 médias mensais jan→dez (mm)")
    P: float = Field(..., gt=0, description="Total anual (mm)")


class ErosividadeRequest(BaseModel):
    aoi: Dict[str, Any] = Field(..., description="GeoJSON do limite do imóvel")
    equacao_id: int = Field(1, description="Equação da biblioteca (1 = padrão)")
    alternativas: Optional[List[int]] = Field(
        None, description="IDs das equações de sensibilidade; padrão = pelo regime")
    chuva_manual: Optional[ChuvaManual] = Field(
        None, description="Se informado, usa estas médias em vez do CHIRPS")
    ano_ini: Optional[int] = None
    ano_fim: Optional[int] = None


class ErosividadeResponse(BaseModel):
    R: float
    R_climatologico: float
    metodo_R: str
    classe: str
    faixa_sensibilidade: List[float]
    ic_media: Optional[List[float]] = None
    mokus_anos: Optional[float] = None
    ei_mensal: List[float]
    pct: List[float]
    pct_acumulada: List[float]
    meses: List[str]
    meses_criticos: List[str]
    periodo_critico: Dict[str, Any]
    serie_R_anual: List[float] = []
    anos_serie: List[int] = []
    chuva_anos: List[Dict[str, Any]] = []
    cs_out_abr: Optional[float] = None
    tendencia: Optional[Dict[str, Any]] = None
    n_anos: int = 0
    cv: Optional[float] = None
    retorno: List[Dict[str, Any]] = []
    sensibilidade: List[Dict[str, Any]] = []
    spread_sensibilidade: float = 0.0
    confianca: str
    motivos_confianca: List[str] = []
    regime: Dict[str, Any]
    equacao: Dict[str, Any]
    chuva: Dict[str, Any]
    metodologia: Dict[str, Any]
    area_ha: Optional[float] = None
    centroide: Optional[Dict[str, float]] = None
    unidade_R: str


class EquacaoInfo(BaseModel):
    id: int
    nome: str
    local: str
    koppen: str
    referencia: str
    ativa: bool
    usar_para: str


class EquacoesResponse(BaseModel):
    equacoes: List[EquacaoInfo] = []
