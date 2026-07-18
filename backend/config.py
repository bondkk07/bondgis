"""Configuração central do backend BondGis (lida do ambiente / .env).

Nenhuma credencial fica no código. Todos os segredos vêm de variáveis de
ambiente — em desenvolvimento via arquivo .env (veja .env.example), em
produção via variáveis do serviço de hospedagem (Render, Cloud Run, etc.).
"""
from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── Google Earth Engine ────────────────────────────────────────────
    # Projeto do Google Cloud habilitado para Earth Engine (obrigatório na
    # nova API do EE). Ex.: "bondgis-ee".
    ee_project: str = Field(default="", alias="EE_PROJECT")

    # E-mail da service account (…@…​.iam.gserviceaccount.com).
    ee_service_account_email: str = Field(default="", alias="EE_SERVICE_ACCOUNT_EMAIL")

    # Forneça UMA das duas formas de chave privada:
    #  (a) caminho para o arquivo JSON da chave — bom em dev local;
    #  (b) conteúdo JSON da chave em uma única variável — bom em deploy.
    ee_service_account_key_file: Optional[str] = Field(
        default=None, alias="EE_SERVICE_ACCOUNT_KEY_FILE"
    )
    ee_service_account_key_json: Optional[str] = Field(
        default=None, alias="EE_SERVICE_ACCOUNT_KEY_JSON"
    )

    # ── Servidor / CORS ────────────────────────────────────────────────
    # Origens autorizadas a chamar a API (separadas por vírgula).
    # Inclua o GitHub Pages e o localhost do dev server.
    allowed_origins: str = Field(
        default="http://localhost:8321,http://127.0.0.1:8321,https://bondkk07.github.io",
        alias="ALLOWED_ORIGINS",
    )
    port: int = Field(default=8000, alias="PORT")

    # ── Sentinel-2 ─────────────────────────────────────────────────────
    # Coleção base. S2_SR_HARMONIZED = Surface Reflectance harmonizada.
    s2_collection: str = Field(
        default="COPERNICUS/S2_SR_HARMONIZED", alias="S2_COLLECTION"
    )
    # Escala (m) das reduções/estatísticas. 10 m = resolução nativa das
    # bandas visíveis/NIR do Sentinel-2.
    stats_scale: int = Field(default=10, alias="STATS_SCALE")

    def origins_list(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
