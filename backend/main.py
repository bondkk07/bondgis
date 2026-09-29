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
from typing import Dict, Optional
from urllib.parse import urlparse

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from fastapi import FastAPI, Header, HTTPException, Query
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
    "storage.googleapis.com",   # MapBiomas (verificação de status via /api/ping)
}

settings = get_settings()
app = FastAPI(title="BondGis — Earth Engine API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    # Expostos p/ o navegador ler o tamanho/pedaço em respostas de Range —
    # necessário para o geotiff.js ler os COGs do MapBiomas via /api/proxy.
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
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


def _fetch_allowlisted(url: str, timeout: int = 60, allow_redirects: bool = True,
                       headers_extra: Optional[Dict[str, str]] = None) -> requests.Response:
    """GET server-side com fallback de TLS legado. Valida a allowlist e
    levanta HTTPException(403/502). Compartilhado por /api/proxy e /api/ping.
    O ping usa allow_redirects=False: qualquer resposta HTTP (mesmo 3xx) já
    prova que o servidor está no ar, e evita seguir redirects quebrados
    (ex.: geoserver.car.gov.br 301 → HTTP:80 inacessível). headers_extra
    repassa cabeçalhos do cliente (ex.: Range, para leitura parcial de COGs)."""
    host = (urlparse(url).hostname or "").lower()
    if host not in ALLOWED_PROXY_HOSTS:
        raise HTTPException(status_code=403, detail=f"Host não autorizado: {host}")
    headers = {"User-Agent": "BondGis/1.0"}
    if headers_extra:
        headers.update(headers_extra)
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
def proxy(url: str = Query(..., description="URL pública (host na allowlist) a repassar"),
          range_header: Optional[str] = Header(default=None, alias="range")):
    """Proxy CORS para fontes públicas que não enviam cabeçalhos CORS.
    Resolve o navegador bloquear as camadas subsidiárias do SICAR
    (consulta.car.gov.br), as demais fontes e os COGs do MapBiomas
    (storage.googleapis.com, sem CORS). Só repassa hosts da allowlist.
    Repassa o header Range e devolve o 206/Content-Range do upstream — assim
    o geotiff.js lê só a janela do COG, sem baixar o raster inteiro (~800 MB)."""
    extra = {"Range": range_header} if range_header else None
    r = _fetch_allowlisted(url, headers_extra=extra)
    # NÃO repassar Content-Length: o requests pode descomprimir o corpo (gzip),
    # deixando o Content-Length do upstream inconsistente com r.content e
    # truncando a resposta. O Starlette calcula o Content-Length correto a
    # partir do conteúdo. Content-Range/Accept-Ranges seguem para o geotiff.js.
    passthru = {h: r.headers[h] for h in ("Content-Range", "Accept-Ranges")
                if h in r.headers}
    return Response(
        content=r.content,
        status_code=r.status_code,
        media_type=r.headers.get("content-type", "application/octet-stream"),
        headers=passthru,
    )


@app.get("/api/ping")
def ping(
    url: str = Query(..., description="URL da CONSULTA REAL a testar (ex.: WFS GetCapabilities)"),
    contains: str = Query("", description="Marcador que deve existir no corpo para a consulta valer como OK"),
):
    """Testa se a CONSULTA de uma fonte externa realmente funciona — não apenas
    se o servidor responde na raiz. Online exige HTTP < 400, o corpo NÃO ser uma
    página de erro do serviço e (se informado) conter o marcador esperado.
    Assim o painel reflete a realidade da consulta que o app usa."""
    import time
    host = (urlparse(url).hostname or "").lower()
    if host not in ALLOWED_PROXY_HOSTS:
        raise HTTPException(status_code=403, detail=f"Host não autorizado: {host}")
    t0 = time.perf_counter()
    try:
        r = _fetch_allowlisted(url, timeout=20, allow_redirects=True)
    except HTTPException as exc:
        return {"online": False, "status": None,
                "ms": round((time.perf_counter() - t0) * 1000),
                "detalhe": str(exc.detail)[:160]}
    ms = round((time.perf_counter() - t0) * 1000)
    corpo = r.text[:20000]
    corpo_lower = corpo.lower()
    # marcadores de erro de serviço OGC/ArcGIS (respondem HTTP 200 com erro no corpo)
    erro_servico = any(m in corpo_lower for m in
                       ("serviceexceptionreport", "exceptionreport", '"error"'))
    if r.status_code >= 400:
        return {"online": False, "status": r.status_code, "ms": ms,
                "detalhe": f"HTTP {r.status_code}"}
    if contains and contains.lower() not in corpo_lower:
        det = "erro do serviço no corpo" if erro_servico else "resposta inesperada (sem o conteúdo esperado)"
        return {"online": False, "status": r.status_code, "ms": ms, "detalhe": det}
    if erro_servico and not contains:
        return {"online": False, "status": r.status_code, "ms": ms, "detalhe": "erro do serviço no corpo"}
    return {"online": True, "status": r.status_code, "ms": ms}


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
