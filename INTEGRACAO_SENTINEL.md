# Integração Sentinel-2 (Google Earth Engine) — visão geral

Este documento resume a integração adicionada ao BondGis: visualização e
análise de propriedades rurais com imagens **Sentinel-2** processadas no
**Google Earth Engine**, exibidas no mapa **Leaflet** existente.

## Arquitetura (por que há um backend)

O `index.html` é uma página **estática** (hospedada no GitHub Pages, que não
executa Python). O Earth Engine exige autenticação por *service account*, que
**nunca** pode ficar no frontend. Por isso a integração tem duas partes:

```
Frontend estático (index.html)  ──►  Backend FastAPI (pasta backend/)  ──►  Earth Engine
   aba "Satélite"                     /api/tiles, /api/stats, ...            Sentinel-2
```

O frontend envia a **geometria da propriedade (GeoJSON)** + filtros e recebe
**URLs de tiles assinadas** (para o mapa) e **estatísticas numéricas**.

## O que foi alterado / criado

### Frontend — `index.html` (arquivo existente, alterado)
Todas as mudanças são aditivas e não quebram funcionalidades anteriores:

| Onde | O quê |
|------|-------|
| `<head>` | Novo `<script>` do **togeojson** (converte KML→GeoJSON no navegador). |
| Trilho de navegação `#tabs` | Novo botão **Satélite** (ícone + rótulo), seguindo o padrão de rail vertical. |
| `#painel-area` | Nova `<section id="tab-satelite">` com os controles (propriedade, índice, composição, datas, nuvens, botões). |
| Modal `#modal-cfg` | Novo campo **URL do backend Earth Engine** (salvo no localStorage). |
| `cfg` (JS) | Novo `apiBase` (URL do backend). |
| Mapa | `L.control.layers` agora tem referência (`layersControl`) para registrar overlays de satélite. |
| `removerCamada`/`zoomCamada`/`atualizarUICamadas` | Passaram a tratar o novo tipo de camada `gee`. |
| Bloco JS "Satélite" | `apiPost`, `satVisualizar`, `satEstatisticas`, `satDatas`, `satSerie`, `adicionarCamadaGEE`, `relSatelite`, `carregarArquivoSatelite`, `atualizarStatusSatelite`. |
| Inicialização | Listeners dos botões, datas padrão (últimos 6 meses), *health-check* do backend. |

### Backend — pasta `backend/` (novos arquivos)

| Arquivo | Papel |
|---------|-------|
| `main.py` | API FastAPI: `/api/health`, `/api/tiles`, `/api/stats`, `/api/dates`, `/api/timeseries`. |
| `sentinel.py` | Processamento Sentinel-2: máscara de nuvens, composições, índices (NDVI, NDRE, NDWI, NDMI, BSI, NBR), classificação em 9 classes, estatísticas por classe. |
| `earth_engine.py` | Inicialização segura do EE via service account. |
| `config.py` | Configuração via `.env` (pydantic-settings). |
| `schemas.py` | Modelos de request/response (Pydantic). |
| `requirements.txt` | Dependências Python. |
| `.env.example` | Modelo de variáveis de ambiente (copie para `.env`). |
| `Dockerfile`, `render.yaml` | Deploy em container / Render. |
| `optional_postgis.py`, `schema.sql` | Persistência PostgreSQL+PostGIS (opcional, desligada). |
| `README.md` | **Instalação, configuração do Earth Engine e deploy — passo a passo.** |

### VS Code — `.vscode/` (atualizado)
- `launch.json`: configuração de debug do backend (uvicorn) + composto
  "frontend + backend".
- `tasks.json`: task para subir o backend.
- `settings.json`, `extensions.json`: interpretador Python e extensões
  recomendadas.

## Como rodar (resumo)

1. **Backend** — siga `backend/README.md` (instalar Python, `pip install -r
   requirements.txt`, configurar `.env` com as credenciais do Earth Engine,
   `uvicorn main:app --reload --port 8000`).
2. **Frontend** — abra o `index.html` (dev server local `serve.ps1`, ou o site
   publicado). Em **⚙ Configurações**, confirme a URL do backend
   (`http://localhost:8000` em dev).
3. Na aba **Satélite**: carregue/selecione uma propriedade, escolha o índice e
   as datas, e clique em **Visualizar no mapa** ou **Calcular estatísticas**.

> Sem o backend rodando, a aba Satélite mostra um aviso claro e o restante do
> app continua 100% funcional.

## Camadas e índices implementados

- **RGB** (cor verdadeira, B4/B3/B2)
- **NDVI** = (B8−B4)/(B8+B4)
- **NDRE** = (B8−B5)/(B8+B5)
- **NDWI** = (B3−B8)/(B3+B8)
- **NDMI** = (B8−B11)/(B8+B11)
- **BSI** (solo exposto) = ((B11+B4)−(B8+B2))/((B11+B4)+(B8+B2))
- **Queimadas** via **NBR** = (B8−B12)/(B8+B12)
- **Classificação automática** (regras por índices): Água, Solo exposto,
  Vegetação rasteira, Pastagem, Agricultura, Vegetação arbustiva, Floresta,
  Área queimada, Área construída.

## Estatísticas exibidas

Área total, área com água, vegetação, agrícola, solo exposto e floresta —
mais o percentual de cada classe e as médias dos índices na área. Um relatório
imprimível é gerado com um clique.

---

# Módulo AUDITORIA_CAR

Cruza automaticamente as camadas do CAR com a cobertura observada pelo
Sentinel-2, **validada pelo MapBiomas** (asset da Coleção 10 lido no próprio
Earth Engine), e produz um diagnóstico de conformidade.

### Arquivos
- **Backend**: `backend/auditoria.py` + endpoint `POST /api/auditoria` em
  `main.py` (modelos em `schemas.py`).
- **Frontend**: aba **Auditoria** (trilho de ícones) em `index.html`, com o
  painel executivo, a camada Leaflet de divergências e os exports.

### Fluxo
1. A aba detecta automaticamente as sub-camadas do CAR já carregadas
   (Limite do imóvel, APP, Reserva Legal, Uso Consolidado, Vegetação Nativa)
   pelo grupo/nome.
2. Envia o limite do imóvel + as sub-camadas ao backend.
3. O backend classifica o Sentinel-2 (9 classes: Água, Área Úmida, Solo
   Exposto, Agricultura, Pastagem, Vegetação Secundária, Floresta, Área
   Queimada, Infraestrutura), valida contra o MapBiomas e detecta 9 tipos de
   divergência: APP antropizada, APP sem vegetação, RL com déficit, RL
   excedente, mudança de uso, supressão vegetal, expansão agrícola, corpos
   hídricos não declarados e áreas degradadas.

### Saídas
- **Painel executivo**: Score Ambiental, Score CAR, Score Vegetação, Score
  APP, Score Reserva Legal e Índice Geral de Conformidade, com o grau
  (Conforme / Atenção / Divergência moderada / Divergência crítica).
- **Camada Leaflet** das divergências, colorida por severidade
  (verde = conforme, amarelo = atenção, laranja = moderada, vermelho = crítica).
- **Relatório HTML** (com botão Imprimir/Salvar **PDF**), **JSON** estruturado
  e **GeoJSON** das divergências, todos exportáveis com um clique.

> As heurísticas de classificação e de divergência são **preliminares**
> (cena única, limiares de índices) — servem como triagem, não como laudo
> oficial. Ajuste os limiares em `auditoria.py` para a sua região.
