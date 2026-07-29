# Deploy do backend BondGis no Google Cloud Run
**Data:** 19/07/2026 · **Autor da execução:** deploy assistido (Claude Code) + autorizações de Gabriel

Registro exato do processo usado para colocar o backend (FastAPI + Earth Engine)
em produção no Cloud Run, servindo o site publicado em
`https://bondkk07.github.io/bondgis`. Serve como referência para redeploys e
para reproduzir o ambiente do zero.

---

## Resultado

| Item | Valor |
|------|-------|
| Serviço Cloud Run | `bondgis-backend` |
| URL pública | `https://bondgis-backend-68534915010.southamerica-east1.run.app` |
| Região | `southamerica-east1` (São Paulo) |
| Projeto GCP | `analise-ambiental-502803` (nº `68534915010`) |
| Service account de runtime | `bondgis-ee@analise-ambiental-502803.iam.gserviceaccount.com` |
| Autenticação Earth Engine | Identidade da service account (ADC) — **sem chave JSON** |
| Escala | 0 → N (paga por uso; cold start na 1ª req.) |

---

## Pré-requisitos

- Projeto Google Cloud com **billing ativo** e **Earth Engine API** habilitada e
  o projeto **registrado** no Earth Engine (já feito em etapa anterior).
- **gcloud CLI** instalado. Nesta máquina foi via winget:
  ```powershell
  winget install --id Google.CloudSDK --silent --accept-package-agreements --accept-source-agreements
  ```
  (o binário fica em `%LOCALAPPDATA%\Google\Cloud SDK\google-cloud-sdk\bin\gcloud`)
- Docker **não** é necessário: `gcloud run deploy --source` builda na nuvem (Cloud Build).

---

## Passo a passo (comandos exatos)

### 1. Login e projeto
```powershell
gcloud auth login              # abre o navegador; autorizar com a conta dona do projeto
gcloud config set project analise-ambiental-502803
```

### 2. Ativar as APIs necessárias
```powershell
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```
(A `earthengine.googleapis.com` já estava habilitada.)

### 3. Service account de runtime (autenticação EE sem chave)
```powershell
$PROJ = "analise-ambiental-502803"
$SA   = "bondgis-ee@$PROJ.iam.gserviceaccount.com"

gcloud iam service-accounts create bondgis-ee --display-name "BondGis backend (Earth Engine)"

# Aguardar alguns segundos a propagação da SA antes de conceder papéis.
gcloud projects add-iam-policy-binding $PROJ --member "serviceAccount:$SA" `
  --role "roles/earthengine.writer" --condition=None
gcloud projects add-iam-policy-binding $PROJ --member "serviceAccount:$SA" `
  --role "roles/serviceusage.serviceUsageConsumer" --condition=None
```
> Como o backend roda **como** essa SA, o `earth_engine.py` usa as credenciais
> padrão do ambiente (ADC). Por isso `EE_SERVICE_ACCOUNT_EMAIL` fica **vazio**
> no deploy — nenhuma chave JSON é necessária nem versionada.

### 4. Permissões do Cloud Build (corrige erro comum em projeto novo)
Na 1ª tentativa o deploy falhou com:
`ERROR: ... 68534915010-compute@developer.gserviceaccount.com does not have
storage.objects.get access ... run-sources-... .zip ... forbidden`

A service account **padrão do Compute** (usada pelo Cloud Build) precisava de papéis:
```powershell
$COMPUTE = "68534915010-compute@developer.gserviceaccount.com"
foreach ($role in @(
  "roles/cloudbuild.builds.builder",
  "roles/storage.objectViewer",
  "roles/logging.logWriter",
  "roles/artifactregistry.writer")) {
  gcloud projects add-iam-policy-binding $PROJ --member "serviceAccount:$COMPUTE" `
    --role $role --condition=None
}
```

### 5. Proteger o build (.dockerignore)
Criado `backend/.dockerignore` para o `COPY . .` do Dockerfile **não** enviar o
venv (Windows, inútil no container Linux) nem segredos:
```
.venv/
__pycache__/
**/__pycache__/
*.pyc
.env
*.json
service-account-key.json
```

### 6. Deploy
```powershell
gcloud run deploy bondgis-backend `
  --source ./backend `
  --region southamerica-east1 `
  --allow-unauthenticated `
  --service-account "bondgis-ee@analise-ambiental-502803.iam.gserviceaccount.com" `
  --set-env-vars "^@^EE_PROJECT=analise-ambiental-502803@ALLOWED_ORIGINS=https://bondkk07.github.io,http://localhost:8321,http://127.0.0.1:8321" `
  --memory 512Mi --timeout 300
```
> **Sintaxe do `--set-env-vars`:** o prefixo `^@^` troca o separador de vírgula
> por `@`, para que a vírgula dentro de `ALLOWED_ORIGINS` seja preservada.

---

## Configuração do frontend

O `index.html` decide o backend automaticamente (`API_PADRAO`):
- em `localhost` → `http://localhost:8000` (dev);
- publicado → a URL do Cloud Run.

Um `apiBase` localhost salvo no site publicado cai para o padrão da nuvem
(localhost é inalcançável de fora). O usuário sempre pode sobrescrever em
**⚙ Configurações**.

---

## Verificação pós-deploy

```bash
# saúde (EE ativo)
curl -s https://bondgis-backend-68534915010.southamerica-east1.run.app/api/health
# -> {"status":"ok","earth_engine":true,"project":"analise-ambiental-502803",...}
```
Testado também no site publicado: proxy SICAR (HTTP 200 com TLS legado),
`/api/ping` (16/16 fontes online) e CORS a partir de `bondkk07.github.io`.

---

## Redeploy (quando o código do backend mudar)

```powershell
gcloud config set project analise-ambiental-502803
gcloud run deploy bondgis-backend --source ./backend --region southamerica-east1
```
(As variáveis de ambiente e a service account persistem entre revisões; só
reinformar se quiser alterá-las.)

---

## Operação e custo

- **Custo:** Cloud Run cobra por requisição + CPU/mem-tempo, com camada gratuita
  generosa. Neste volume, tende a ~R$0. Conferir em *Billing* no Console.
- **Cold start:** sem uso por um tempo, a 1ª requisição leva alguns segundos
  (a instância sobe do zero). Normal.
- **Logs:** `gcloud run services logs read bondgis-backend --region southamerica-east1`
- **URL/estado:** `gcloud run services describe bondgis-backend --region southamerica-east1`

---

## Endpoints em produção

| Método | Rota | Uso |
|--------|------|-----|
| GET | `/api/health` | Status da API + Earth Engine |
| GET | `/api/proxy?url=` | Proxy CORS (allowlist) p/ GeoServers gov-br (SICAR etc.) |
| GET | `/api/ping?url=` | Teste de disponibilidade server-side (painel de status) |
| POST | `/api/tiles` | Tiles Sentinel-2 (RGB/índices/classificação) |
| POST | `/api/analise` | Fluxo único de análise (auditoria, conformidade, temporal…) |
| POST | `/api/dates` `/api/timeseries` | Datas disponíveis / série temporal |

Segurança: `/api/proxy` e `/api/ping` só aceitam hosts da allowlist (evita proxy
aberto/SSRF). A sessão de TLS legado é usada apenas nesses hosts públicos gov-br
que negociam cifras que o OpenSSL 3.x recusa por padrão.
