"""API BondGis — Sentinel-2 via Google Earth Engine (FastAPI).

Execução local:
    uvicorn main:app --reload --port 8000
(a partir da pasta backend/, com o .env configurado)

Todos os endpoints recebem a AOI em GeoJSON e devolvem URLs de tiles já
assinadas pelo Earth Engine ou estatísticas numéricas — nenhuma credencial
trafega para o frontend.
"""
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import analise
import sentinel
from config import get_settings
from earth_engine import init_earth_engine, is_initialized
from schemas import (
    AnaliseRequest, AnaliseResponse,
    DatesRequest, DatesResponse, HealthResponse,
    TilesRequest, TilesResponse, TimeSeriesRequest, TimeSeriesResponse,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bondgis.api")

settings = get_settings()
app = FastAPI(title="BondGis — Earth Engine API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    """Tenta inicializar o EE no boot. Se falhar, a API sobe mesmo assim e o
    /api/health reporta o erro — evita derrubar o serviço por config faltando."""
    try:
        init_earth_engine()
    except Exception as exc:  # noqa: BLE001
        logger.error("Falha ao inicializar o Earth Engine: %s", exc)


def _ensure_ee() -> None:
    if not is_initialized():
        try:
            init_earth_engine()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=503,
                detail=f"Earth Engine não inicializado: {exc}",
            )


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    ok = is_initialized()
    return HealthResponse(
        status="ok" if ok else "degraded",
        earth_engine=ok,
        project=settings.ee_project or None,
        message=None if ok else "Earth Engine não inicializado — verifique as variáveis de ambiente.",
    )


@app.post("/api/tiles", response_model=TilesResponse)
def tiles(req: TilesRequest) -> TilesResponse:
    _ensure_ee()
    try:
        data = sentinel.make_tiles(
            req.aoi, req.layer.value, req.date_start, req.date_end,
            req.max_cloud, req.mode.value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro em /api/tiles")
        raise HTTPException(status_code=500, detail=f"Erro ao gerar tiles: {exc}")
    return TilesResponse(**data)


@app.post("/api/dates", response_model=DatesResponse)
def dates(req: DatesRequest) -> DatesResponse:
    _ensure_ee()
    try:
        data = sentinel.list_dates(
            req.aoi, req.date_start, req.date_end, req.max_cloud, req.mode.value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro em /api/dates")
        raise HTTPException(status_code=500, detail=f"Erro ao listar datas: {exc}")
    return DatesResponse(**data)


@app.post("/api/timeseries", response_model=TimeSeriesResponse)
def timeseries(req: TimeSeriesRequest) -> TimeSeriesResponse:
    _ensure_ee()
    try:
        data = sentinel.time_series(
            req.aoi, req.index.value, req.date_start, req.date_end,
            req.max_cloud, req.mode.value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro em /api/timeseries")
        raise HTTPException(status_code=500, detail=f"Erro na série temporal: {exc}")
    return TimeSeriesResponse(**data)


@app.post("/api/analise", response_model=AnaliseResponse)
def analisar_area(req: AnaliseRequest) -> AnaliseResponse:
    """Fluxo único: selecionar área → tipo de análise → processar → resultado.
    Todos os tipos compartilham o mesmo pipeline (ver analise.py)."""
    _ensure_ee()
    try:
        data = analise.run_analise(
            req.aoi, req.camadas.model_dump(), req.tipo.value,
            req.date_start, req.date_end, req.max_cloud, req.mode.value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro em /api/analise")
        raise HTTPException(status_code=500, detail=f"Erro na análise: {exc}")
    return AnaliseResponse(**data)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=True)
