"""Inicialização segura do Google Earth Engine via service account.

A autenticação acontece somente no backend. O frontend nunca recebe a
chave — apenas URLs de tiles já assinadas e resultados numéricos.
"""
import json
import logging
import tempfile
from pathlib import Path

import ee

from config import get_settings

logger = logging.getLogger("bondgis.ee")

_initialized = False


def init_earth_engine() -> None:
    """Inicializa o EE uma única vez. Lança RuntimeError com mensagem clara
    se faltar configuração."""
    global _initialized
    if _initialized:
        return

    s = get_settings()
    if not s.ee_project:
        raise RuntimeError(
            "EE_PROJECT não definido. Configure o id do projeto Google Cloud "
            "habilitado para Earth Engine (veja backend/README.md)."
        )
    if not s.ee_service_account_email:
        raise RuntimeError("EE_SERVICE_ACCOUNT_EMAIL não definido.")

    key_file = _resolve_key_file(s)
    if not key_file:
        raise RuntimeError(
            "Nenhuma chave da service account encontrada. Defina "
            "EE_SERVICE_ACCOUNT_KEY_FILE (caminho) ou EE_SERVICE_ACCOUNT_KEY_JSON "
            "(conteúdo JSON)."
        )

    credentials = ee.ServiceAccountCredentials(s.ee_service_account_email, key_file)
    ee.Initialize(credentials, project=s.ee_project, opt_url="https://earthengine-highvolume.googleapis.com")
    _initialized = True
    logger.info("Earth Engine inicializado no projeto %s", s.ee_project)


def _resolve_key_file(s) -> str | None:
    """Retorna um caminho de arquivo de chave utilizável. Se a chave veio como
    JSON inline (deploy), grava em arquivo temporário."""
    if s.ee_service_account_key_file:
        p = Path(s.ee_service_account_key_file).expanduser()
        if p.is_file():
            return str(p)
        logger.warning("EE_SERVICE_ACCOUNT_KEY_FILE aponta para arquivo inexistente: %s", p)

    if s.ee_service_account_key_json:
        try:
            data = json.loads(s.ee_service_account_key_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"EE_SERVICE_ACCOUNT_KEY_JSON não é um JSON válido: {exc}")
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(data, tmp)
        tmp.flush()
        tmp.close()
        return tmp.name

    return None


def is_initialized() -> bool:
    return _initialized
