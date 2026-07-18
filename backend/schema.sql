-- Schema OPCIONAL PostgreSQL + PostGIS para o BondGis.
-- Rode uma vez no banco: psql "$DATABASE_URL" -f schema.sql

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS propriedades (
    id         SERIAL PRIMARY KEY,
    nome       TEXT NOT NULL,
    geom       GEOMETRY(Geometry, 4326) NOT NULL,
    criado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS propriedades_geom_gix ON propriedades USING GIST (geom);

CREATE TABLE IF NOT EXISTS analises (
    id              SERIAL PRIMARY KEY,
    propriedade_id  INTEGER NOT NULL REFERENCES propriedades(id) ON DELETE CASCADE,
    resultado       JSONB NOT NULL,
    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS analises_prop_idx ON analises (propriedade_id);
