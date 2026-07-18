"""Persistência OPCIONAL em PostgreSQL + PostGIS.

Desligado por padrão — a API funciona 100% sem banco (stateless). Use este
módulo se quiser guardar propriedades e resultados de análise.

Para ativar:
  1. Descomente psycopg/SQLAlchemy/GeoAlchemy2 em requirements.txt e reinstale.
  2. Defina DATABASE_URL no .env
     (ex.: postgresql+psycopg://user:senha@localhost:5432/bondgis).
  3. Rode o schema.sql no banco (cria a extensão postgis e as tabelas).
  4. Importe e chame save_property()/save_analysis() a partir de main.py.
"""
import os
from typing import Any, Dict, Optional

try:
    from sqlalchemy import create_engine, text
    _HAS_SQLALCHEMY = True
except Exception:  # noqa: BLE001
    _HAS_SQLALCHEMY = False

_engine = None


def get_engine():
    global _engine
    if not _HAS_SQLALCHEMY:
        raise RuntimeError("SQLAlchemy não instalado — veja requirements.txt.")
    if _engine is None:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL não definido.")
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def save_property(nome: str, geojson: Dict[str, Any]) -> int:
    """Grava a geometria da propriedade (GeoJSON) e retorna o id."""
    import json
    eng = get_engine()
    with eng.begin() as conn:
        row = conn.execute(
            text("""
                INSERT INTO propriedades (nome, geom)
                VALUES (:nome, ST_SetSRID(ST_GeomFromGeoJSON(:geo), 4326))
                RETURNING id
            """),
            {"nome": nome, "geo": json.dumps(geojson)},
        ).first()
        return int(row[0])


def save_analysis(propriedade_id: int, resultado: Dict[str, Any]) -> int:
    import json
    eng = get_engine()
    with eng.begin() as conn:
        row = conn.execute(
            text("""
                INSERT INTO analises (propriedade_id, resultado)
                VALUES (:pid, CAST(:res AS jsonb))
                RETURNING id
            """),
            {"pid": propriedade_id, "res": json.dumps(resultado)},
        ).first()
        return int(row[0])
