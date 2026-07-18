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


class StatsRequest(BaseAOIRequest):
    pass


class ClassAreaEntry(BaseModel):
    codigo: int
    classe: str
    cor: str
    area_ha: float
    pct: float


class StatsResponse(BaseModel):
    area_total_ha: float
    image_date: Optional[str] = None
    n_images: int = 0
    # médias dos índices espectrais sobre a AOI
    indices: Dict[str, Optional[float]] = {}
    # área por classe da classificação automática
    classes: List[ClassAreaEntry] = []
    # atalhos pedidos no requisito 8
    resumo: Dict[str, float] = {}


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


# ── AUDITORIA_CAR ──────────────────────────────────────────────────────────
class AuditoriaCamadas(BaseModel):
    """Camadas do CAR (GeoJSON); todas opcionais exceto o imóvel."""
    app: Optional[Dict[str, Any]] = None
    reserva_legal: Optional[Dict[str, Any]] = None
    uso_consolidado: Optional[Dict[str, Any]] = None
    vegetacao_nativa: Optional[Dict[str, Any]] = None


class AuditoriaRequest(BaseModel):
    aoi: Dict[str, Any] = Field(..., description="GeoJSON do limite do imóvel")
    camadas: AuditoriaCamadas = AuditoriaCamadas()
    date_start: str
    date_end: str
    max_cloud: float = Field(60.0, ge=0, le=100)
    mode: CompositeMode = CompositeMode.median


class AuditoriaResponse(BaseModel):
    n_images: int
    image_date: Optional[str] = None
    mapbiomas_ano: int
    area_total_ha: float
    camadas: Dict[str, Any]
    divergencias: List[Dict[str, Any]]
    scores: Dict[str, Optional[float]]
    grau_conformidade: str
    geojson_divergencias: Dict[str, Any]
