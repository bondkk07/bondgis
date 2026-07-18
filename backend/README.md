# BondGis — Backend Earth Engine (Sentinel-2)

Backend **FastAPI** que roda o geoprocessamento no **Google Earth Engine** e
devolve ao frontend apenas **URLs de tiles já assinadas** e **estatísticas
numéricas**. Nenhuma credencial trafega para o navegador.

O frontend (`../index.html`) é estático e continua funcionando sem este
backend — apenas a aba **Satélite** depende dele.

---

## 1. Arquitetura

```
Navegador (index.html, GitHub Pages)
        │  POST /api/tiles | /api/stats | /api/dates | /api/timeseries
        ▼
FastAPI (este backend, hospedado à parte)
        │  earthengine-api (service account)
        ▼
Google Earth Engine  ──►  Copernicus Sentinel-2 (S2_SR_HARMONIZED)
```

- **RGB** cor verdadeira · **NDVI, NDRE, NDWI, NDMI, BSI, NBR** · **classificação
  automática** em 9 classes (regras por índices).
- Bandas usadas: **B2 B3 B4 B5 B6 B7 B8 B11 B12**.
- Estatísticas por classe recortadas pela geometria da propriedade (GeoJSON).

> ⚠️ **GitHub Pages não roda Python.** Este backend precisa ser hospedado
> separadamente (localhost em dev; Render / Cloud Run / Railway em produção).
> No frontend, informe a URL do backend em **⚙ Configurações → URL do backend**.

---

## 2. Pré-requisitos

- **Python 3.10+** (esta máquina ainda não tem — instale de python.org e marque
  "Add python.exe to PATH", ou use o Microsoft Store).
- Conta Google com **Earth Engine** habilitado.
- Um **projeto Google Cloud** com a API do Earth Engine ativada.

---

## 3. Configuração do Google Earth Engine (uma vez)

O backend suporta **dois modos de autenticação**:

- **Modo simples (dev local)** — usa a sua conta Google via
  `earthengine authenticate`. Não precisa de service account nem chave JSON.
  Ideal para rodar na sua máquina. Passos:
  1. Tenha um **projeto Google Cloud** com a **Earth Engine API ativada** e o
     projeto **registrado** no Earth Engine (veja 3.2–3.4 abaixo).
  2. Rode uma vez: `.venv\Scripts\earthengine authenticate` (abre o navegador).
  3. No `.env`, defina apenas `EE_PROJECT=seu-project-id` e deixe
     `EE_SERVICE_ACCOUNT_EMAIL` **vazio**.

- **Modo service account (produção)** — para deploy sem interação humana.
  Siga os passos 3.5 abaixo (criar service account + chave JSON).

Em ambos, `EE_PROJECT` é obrigatório. Detalhamento:


1. **Registrar-se no Earth Engine**: https://earthengine.google.com/ → *Sign up*
   (escolha uso *não comercial* se aplicável). Aguarde a aprovação.
2. **Criar/escolher um projeto no Google Cloud**: https://console.cloud.google.com/
   → anote o *Project ID* (ex.: `bondgis-ee`).
3. **Ativar a API**: no Console → *APIs & Services* → *Enable APIs* → procure
   **"Earth Engine API"** → *Enable*.
4. **Registrar o projeto no Earth Engine**:
   https://code.earthengine.google.com/register → vincule o projeto do passo 2.
5. **Criar a service account**:
   - Console → *IAM & Admin* → *Service Accounts* → *Create service account*.
   - Nome ex.: `bondgis-ee`. Anote o e-mail
     `bondgis-ee@SEU-PROJETO.iam.gserviceaccount.com`.
   - Conceda o papel **"Earth Engine Resource Viewer"** (e, se for exportar,
     *Writer*).
   - Em *Keys* → *Add key* → *Create new key* → **JSON**. Baixe o arquivo.
6. **Autorizar a service account no Earth Engine**: em
   https://code.earthengine.google.com/ → *Assets* / *Settings* não é
   necessário para leitura pública, mas garanta que o **projeto** está
   registrado (passo 4). A service account herda o acesso do projeto.

Guarde o JSON com segurança. **Nunca** faça commit dele (o `.gitignore` já
ignora `backend/*.json` e `backend/.env`).

---

## 4. Instalação e execução local

```bash
cd backend

# 1) ambiente virtual
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux/macOS:
# source .venv/bin/activate

# 2) dependências
pip install -r requirements.txt

# 3) configuração
cp .env.example .env          # Windows: copy .env.example .env
#   edite .env e preencha EE_PROJECT, EE_SERVICE_ACCOUNT_EMAIL e o caminho
#   EE_SERVICE_ACCOUNT_KEY_FILE apontando para o JSON baixado.

# 4) subir a API
uvicorn main:app --reload --port 8000
```

Verifique: abra http://localhost:8000/api/health — deve retornar
`{"status":"ok","earth_engine":true,...}`.

Documentação interativa automática: http://localhost:8000/docs

No frontend, abra **⚙ Configurações** e confirme a URL `http://localhost:8000`.
A aba **Satélite** mostrará "✔ Backend online · Earth Engine ativo".

---

## 5. Endpoints

| Método | Rota               | Descrição                                             |
|--------|--------------------|-------------------------------------------------------|
| GET    | `/api/health`      | Status da API e do Earth Engine.                      |
| POST   | `/api/tiles`       | URL de tiles de uma camada (rgb/ndvi/.../classificacao). |
| POST   | `/api/dates`       | Datas de imagens disponíveis no período/filtro.       |
| POST   | `/api/timeseries`  | Série temporal (média do índice na AOI por imagem).   |
| POST   | `/api/analise`     | **Fluxo único de análise** (`tipo`: completa, auditoria, conformidade, vegetacao, supressao, recuperacao, temporal). Cruza CAR × Sentinel-2 × MapBiomas no mesmo pipeline, com score de conformidade transparente e GeoJSON das divergências. Ver `REVISAO_ARQUITETURAL.md`. |

Corpo comum (JSON):

```json
{
  "aoi": { "type": "Feature", "geometry": { "type": "Polygon", "coordinates": [...] } },
  "date_start": "2026-01-01",
  "date_end": "2026-07-01",
  "max_cloud": 40,
  "mode": "recent"
}
```

`/api/tiles` adiciona `"layer": "ndvi"`; `/api/timeseries` adiciona `"index": "ndvi"`.

---

## 6. Deploy em produção

### Opção A — Render (Docker, tem plano free)

1. Faça push do repositório para o GitHub (já está em `bondkk07/bondgis`).
2. No Render: *New* → *Web Service* → conecte o repo. O `backend/render.yaml`
   já define o serviço via Docker.
3. Em *Environment*, configure os segredos:
   - `EE_PROJECT` = seu project id
   - `EE_SERVICE_ACCOUNT_EMAIL` = e-mail da service account
   - `EE_SERVICE_ACCOUNT_KEY_JSON` = **conteúdo** do JSON (cole tudo em uma linha)
   - `ALLOWED_ORIGINS` = `https://bondkk07.github.io`
4. Deploy. Anote a URL pública (ex.: `https://bondgis-backend.onrender.com`).
5. No frontend (⚙ Configurações), troque a URL do backend para essa.

### Opção B — Google Cloud Run

```bash
cd backend
gcloud run deploy bondgis-backend \
  --source . --region southamerica-east1 --allow-unauthenticated \
  --set-env-vars "EE_PROJECT=SEU-PROJETO,EE_SERVICE_ACCOUNT_EMAIL=...,ALLOWED_ORIGINS=https://bondkk07.github.io" \
  --set-env-vars "EE_SERVICE_ACCOUNT_KEY_JSON=$(cat service-account-key.json | tr -d '\n')"
```

Como a service account do EE e a do Cloud Run podem ser a mesma, no Cloud Run
você pode até dispensar a chave JSON e usar a identidade do serviço.

---

## 7. PostgreSQL + PostGIS (opcional)

Desligado por padrão — a API é *stateless*. Para persistir propriedades e
resultados, veja `optional_postgis.py` e `schema.sql` (instruções no topo do
`optional_postgis.py`).

---

## 8. Notas sobre a classificação

A classificação em 9 classes (Água, Solo exposto, Vegetação rasteira,
Pastagem, Agricultura, Vegetação arbustiva, Floresta, Área queimada, Área
construída) é **preliminar**, baseada em limiares de índices espectrais
(`sentinel.py → classify`). Serve como diagnóstico rápido; para uso oficial,
ajuste os limiares à sua região ou substitua por um classificador treinado
(Random Forest no próprio Earth Engine, por exemplo).
