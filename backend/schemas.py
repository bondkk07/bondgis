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


class TilesResponse(BaseModel):
    layer: str
    tile_url: str
    attribution: str
    image_date: Optional[str] = None
    n_images: int = 0
    vis: Dict[str, Any] = {}
    legend: List[LegendEntry] = []


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


# ── TARIFA DE ENERGIA (ANEEL Dados Abertos) ───────────────────────────────
class AliquotasTarifa(BaseModel):
    icms: float
    pis: float
    cofins: float


class TarifaEnergiaResponse(BaseModel):
    distribuidora: str
    vigente: bool = True
    aviso: Optional[str] = None
    cnpj: Optional[str] = None
    subgrupo: Optional[str] = None
    classe: Optional[str] = None
    modalidade: Optional[str] = None
    vigencia_inicio: Optional[str] = None
    vigencia_fim: Optional[str] = None
    vlr_te_mwh: float
    vlr_tusd_mwh: float
    tarifa_base_kwh: float
    tarifa_sugerida_com_impostos_kwh: float
    aliquotas_usadas: AliquotasTarifa
    fonte_url: str


# ── ANALISAR ÁREA (pipeline unificado) ────────────────────────────────────
class TipoAnalise(str, Enum):
    completa = "completa"
    auditoria = "auditoria"
    conformidade = "conformidade"
    vegetacao = "vegetacao"
    supressao = "supressao"
    recuperacao = "recuperacao"
    temporal = "temporal"


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
    mapbiomas_ano: int
    mapbiomas_ano_historico: int
    area_total_ha: float
    camadas_recebidas: Dict[str, bool]
    modulos: Dict[str, Any]
    geojson_divergencias: Dict[str, Any]
