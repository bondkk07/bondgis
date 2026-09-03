"""API BondGis — Sentinel-2 via Google Earth Engine (FastAPI).

Execução local:
    uvicorn main:app --reload --port 8000
(a partir da pasta backend/, com o .env configurado)

Todos os endpoints recebem a AOI em GeoJSON e devolvem URLs de tiles já
assinadas pelo Earth Engine ou estatísticas numéricas — nenhuma credencial
trafega para o frontend.
"""
import logging
import ssl
from urllib.parse import urlparse

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class _LegacyTLSAdapter(HTTPAdapter):
    """Habilita cifras/TLS legados que vários GeoServers gov-br exigem e que o
    OpenSSL 3.x do Python recusa por padrão (SSLV3_ALERT_HANDSHAKE_FAILURE).
    Navegadores e curl aceitam; o requests precisa deste ajuste."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        except ssl.SSLError:
            pass
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


# Sessão de fallback para hosts com TLS legado (dados públicos da allowlist).
_legacy_session = requests.Session()
_legacy_session.mount("https://", _LegacyTLSAdapter())

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

# Hosts públicos autorizados no /api/proxy. Muitos GeoServers de governo
# (SICAR consulta, FUNAI, IPHAN, INPE…) não enviam cabeçalhos CORS, então o
# navegador bloqueia o acesso direto. O backend busca server-side (sem CORS)
# e devolve com os cabeçalhos CORS corretos. Allowlist evita proxy aberto/SSRF.
ALLOWED_PROXY_HOSTS = {
    "consulta.car.gov.br", "geoserver.car.gov.br",
    "geoserver.funai.gov.br", "geoserver.iphan.gov.br",
    "geoservicos.ibge.gov.br", "geo.sema.mt.gov.br",
    "geoservicos.inde.gov.br", "smapas.florestal.gov.br",
    "terrabrasilis.dpi.inpe.br", "geoinfo.dados.embrapa.br",
    "geoportal.sedam.ro.gov.br", "labdez.mma.gov.br",
    "pamgia.ibama.gov.br", "tiles.maps.eox.at",
}

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


def _fetch_allowlisted(url: str, timeout: int = 60,
                       allow_redirects: bool = True) -> requests.Response:
    """GET server-side com fallback de TLS legado. Valida a allowlist e
    levanta HTTPException(403/502). Compartilhado por /api/proxy e /api/ping.
    O ping usa allow_redirects=False: qualquer resposta HTTP (mesmo 3xx) já
    prova que o servidor está no ar, e evita seguir redirects quebrados
    (ex.: geoserver.car.gov.br 301 → HTTP:80 inacessível)."""
    host = (urlparse(url).hostname or "").lower()
    if host not in ALLOWED_PROXY_HOSTS:
        raise HTTPException(status_code=403, detail=f"Host não autorizado: {host}")
    headers = {"User-Agent": "BondGis/1.0"}
    try:
        return requests.get(url, timeout=timeout, headers=headers, allow_redirects=allow_redirects)
    except requests.exceptions.SSLError:
        # Cadeia/handshake SSL incompatível (comum em GeoServers gov-br).
        # Refaz pela sessão de TLS legado. Hosts públicos da allowlist, sem
        # credenciais — risco baixo.
        try:
            return _legacy_session.get(url, timeout=timeout, headers=headers,
                                       allow_redirects=allow_redirects, verify=False)
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"Falha ao acessar a fonte: {exc}")
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao acessar a fonte: {exc}")


@app.get("/api/proxy")
def proxy(url: str = Query(..., description="URL pública (host na allowlist) a repassar")):
    """Proxy CORS para GeoServers públicos que não enviam cabeçalhos CORS.
    Resolve o problema de o navegador bloquear as camadas subsidiárias do
    SICAR (consulta.car.gov.br) e demais fontes. Só repassa hosts da allowlist."""
    r = _fetch_allowlisted(url)
    return Response(
        content=r.content,
        status_code=r.status_code,
        media_type=r.headers.get("content-type", "application/octet-stream"),
    )


@app.get("/api/ping")
def ping(url: str = Query(..., description="URL pública (host na allowlist) a testar")):
    """Testa server-side se uma fonte externa responde — do MESMO caminho por
    onde o app a acessa (backend), sem os falsos negativos do ping no-cors do
    navegador. Qualquer resposta HTTP (mesmo 3xx/4xx) = servidor no ar."""
    import time
    host = (urlparse(url).hostname or "").lower()
    if host not in ALLOWED_PROXY_HOSTS:
        raise HTTPException(status_code=403, detail=f"Host não autorizado: {host}")
    t0 = time.perf_counter()
    try:
        r = _fetch_allowlisted(url, timeout=15, allow_redirects=False)
        return {"online": True, "status": r.status_code,
                "ms": round((time.perf_counter() - t0) * 1000)}
    except HTTPException as exc:
        return {"online": False, "status": None,
                "ms": round((time.perf_counter() - t0) * 1000),
                "detalhe": str(exc.detail)[:140]}


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
