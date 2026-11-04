# PROMPT — Módulo de Erosividade da Chuva (Fator R) com dados da ANA e do INMET

> Cole este texto inteiro na conversa onde está o código do site.

## 0. Contexto e objetivo

O site já recebe o número do **CAR** e obtém o **polígono da propriedade**. A nova funcionalidade deve calcular a **erosividade da chuva (fator R da EUPS/USLE)** da propriedade. O cálculo precisa ser preciso e rastreável, com dados oficiais de chuva da **ANA** (HidroWeb/HidroWebService) e do **INMET** (BDMEP e estações automáticas).

Atue como engenheiro de software sênior e como especialista em hidrologia e conservação do solo. A base científica vem de um TCC sobre Rondônia e de cerca de 100 artigos revisados (§14).

- Siga as fórmulas exatamente como estão aqui. Se houver motivo técnico para mudar alguma, explique antes.
- Um valor marcado com **⚠** só pode ficar `ativo` em produção depois de conferido na fonte original.

**Saída para cada CAR:**
- R anual (MJ mm ha⁻¹ h⁻¹ ano⁻¹) com faixa de incerteza;
- EI mensal (valor, % e % acumulada) e EI por decêndio (36 valores);
- classe, meses críticos (EI > 500) e período crítico;
- período de retorno e R para T = 2, 5, 10, 20, 50 e 100 anos;
- estações usadas: distância, peso, série, % preenchida e Köppen;
- equação usada e sua referência;
- **sensibilidade**: R calculado com 2 a 3 equações alternativas;
- **nível de confiança**, com os motivos.

## 1. Antes de codar

1. Explore o repositório:
   - stack, banco de dados (PostgreSQL + **PostGIS**?), ORM e jobs;
   - como o CAR guarda o polígono: SRID e datum. O CAR usa SIRGAS 2000; mapas antigos de Rondônia estão em SAD69/UTM 20S, então reprojete;
   - como os dados chegam ao front-end.
2. Escreva um plano curto (arquivos, tabelas, jobs, endpoints) seguindo os padrões do projeto.
3. Use duas camadas:
   - **Offline (job agendado, reprocessável):** baixa, limpa, consiste e preenche as séries, depois pré-calcula o R por estação e as superfícies interpoladas.
   - **Online:** recebe o CAR, consulta o que já foi calculado e responde em segundos. **Nunca** baixe dados da ANA ou do INMET durante a requisição.

## 2. Fundamentos

### 2.1 Definições
- **Equação:** `A = R·K·LS·C·P` (Wischmeier & Smith, 1978), com R em MJ mm ha⁻¹ h⁻¹ ano⁻¹ e K em Mg h MJ⁻¹ mm⁻¹.
- **EI30 de uma chuva:** energia cinética × intensidade máxima em 30 min. O EI do mês é a soma das chuvas erosivas; o do ano é a soma dos meses. **R é a média dos EI anuais.**
- **Índice oficial: EI30.** Foi o índice mais correlacionado com as perdas de solo no Brasil (r entre 0,61 e 0,80, em Lages, Sete Lagoas e Sumé). KE>25 fica como índice opcional.
- **Série:**
  - recomendado ≥ 20 anos (a OMM recomenda 30); o TCC usou 13 a 29;
  - calcule também o mínimo de anos de Mokus (§7);
  - séries mais curtas rebaixam a confiança.
- **A USLE estima médias de longo prazo.** O R de um ano isolado varia muito: o CV vai de 18% (Lavras) a 48% (Quaraí). Por isso mostre a média e a variabilidade.

### 2.2 Método principal: coeficiente de chuva (Fournier/Lombardi Neto)
Quase todas as estações são pluviômetros (total diário). O cálculo é:

```
Rc = p²/P   (p = chuva do mês, P = chuva do ano, em mm)
EI_mês = f(Rc)   (forma potência a·Rc^b, ou linear/quadrática; ver §2.5)
```

A equação padrão, usada no TCC de Rondônia, é `EI = 67,355·Rc^0,85` (Lombardi Neto & Moldenhauer, 1992, Campinas). Ela é a versão SI de `6,866·Rc^0,85` (fator de conversão 9,81). Moreti (2003) cita `67,414·Rc^0,850` ⚠: guarde essa variante à parte.

Calcule três variantes e guarde todas:

- **(A) Ano a ano — resultado oficial.**
  - Para cada ano completo: `Rc_ij = p_ij²/P_j` e `R_j = Σ EI_ij`.
  - `R = média(R_j)`. A série de R_j alimenta o desvio-padrão, o CV e o período de retorno.
- **(B) Climatológica.** Usa as médias mensais e a média anual da série. Fica ~3–4% abaixo de (A); guarde para comparação.
- **(C) Desagregação proporcional (opcional).** `EI_ij = p_ij·EI̅_i/p̄_i`.

**Limitação do método:** o Rc mede volume e concentração da chuva, não intensidade.
- **Funciona** em clima com estação seca (Aw, Am, Cwa).
- **Falha** com chuva bem distribuída: Lages (Cfb) deu r de 0,58–0,61, sem significância; Santa Rosa (Cfa) deu R² de 0,41–0,51 no mensal.
- **Pode falhar** no Nordeste com dois regimes de chuva (por exemplo, o agreste de Alagoas, que chove de maio a agosto).
- A **distribuição mensal** estimada pelo Rc pode diferir da real (Seropédica/Nova Friburgo; Cassol, 2008).

### 2.3 Método direto EI30 (dado ≤ 15 min; o dado horário do INMET não serve)
1. **Chuvas individuais:** separe chuvas com intervalo ≥ 6 h e menos de 1,0 mm nesse intervalo (configurável; Wischmeier usa 1,27 mm).
2. **Chuva erosiva:** ≥ 10 mm, ou ≥ 6 mm em ≤ 15 min.
   - Variante de De Maria (1994): não erosiva se < 10 mm e I15 < 24 mm/h, ou se E < 3,6 MJ/ha.
3. **Leitura do registro:** use segmentos de intensidade uniforme, não intervalos fixos de 10 min. Em Sete Lagoas, a leitura em intervalos fixos deu R = 1.942 contra 5.835 por segmentos.
4. **Energia por segmento** (MJ ha⁻¹ mm⁻¹, I em mm/h):
   - **Foster (1981):** `e = 0,119 + 0,0873·log10(I)`, com e = 0,283 para I > 76 mm/h;
   - **Wagner & Massambani:** `e = 0,153 + 0,0645·log10(I)`, com teto 0,2743;
   - **Hudson:** `e = 0,298 − 1,275/I`;
   - os estudos não acharam diferença significativa entre elas; o padrão é Foster.
5. **I30** = 2 × maior lâmina em 30 min. Se a chuva durar menos de 30 min, I30 = 2 × total.
6. **EI30** = E × I30. Some por mês, decêndio e ano.
7. **Opcionais:**
   - **KE>25:** energia dos segmentos com I ≥ 25 mm/h;
   - **padrão da chuva:** avançado/intermediário/atrasado, conforme o pico caia no 1º, 2º ou 3º terço. O padrão atrasado gera 37–91% mais perda de solo.

### 2.4 Calibração local (fase 2)
Para estações com EI30 direto e totais mensais:
1. **Ajuste:** potência, linear, quadrática e em p. Grave R², n e a faixa de Rc (`rc_min`, `rc_max`).
   - Prefira a forma potência: ela dá EI = 0 com Rc = 0; a linear com intercepto dá EI > 0 em mês seco.
2. **Validação:**
   - teste t (α = 0,05) entre o R do pluviograma e o R da equação;
   - índice c = r·d (Willmott). Escala de Camargo & Sentelhas: > 0,85 ótimo; 0,76–0,85 muito bom; 0,66–0,75 bom; 0,61–0,65 mediano; 0,51–0,60 sofrível; 0,41–0,50 mau; ≤ 0,40 péssimo.
3. **Série mínima:** ≥ 5 anos. Com 1 ano só, o Rio Doce deu R de 8.243 a 26.676, valores instáveis.

### 2.5 Biblioteca de equações (tabela no banco)
**Campos de cada equação:**
- forma: potência (a·Rc^b), linear em Rc (a·Rc + c), quadrática em Rc, linear em p, potência em p;
- coeficientes e unidade de saída;
- local, lat/lon, Köppen e período da série;
- n, R² ou r;
- `rc_min`/`rc_max` (ou `p_min`/`p_max`);
- R publicado;
- tipo de dado da calibração;
- `usar_para` (mensal e anual, ou só anual);
- referência, `verificada` e `ativa`.

Na carga inicial, **só a equação 1 vem ativa**. As outras ficam inativas até serem conferidas. O Köppen da tabela é indicativo: confirme com um mapa oficial (ex.: Alvares et al., 2013).

| # | Equação (EI em MJ mm ha⁻¹ h⁻¹ mês⁻¹) | Local (Köppen) | Calibração | Ajuste | R publ. | Fonte |
|---|---|---|---|---|---|---|
| 1 | `67,355·Rc^0,85` | Campinas-SP (Cwa) | pluviogramas | — | — | Lombardi & Moldenhauer 1992 — **padrão** |
| 2 | `109,412·Rc^0,744` | Cuiabá-MT (Aw) | INMET, 18 anos | R² 0,911 | 8.810 | Almeida 2011 |
| 3 | `0,547·p^1,483` | Cuiabá-MT | idem | R² 0,914 | — | idem |
| 4 | `172,632645·Rc^0,5245258` | Cáceres-MT (Aw) | ⚠ | R² ≥ 0,9 | — | Almeida 2009, citado em Almeida 2012 |
| 5 | `133,200429·Rc^0,5372499` | Rondonópolis-MT (Aw) | ⚠ | R² ≥ 0,9 | — | idem |
| 6 | `317,397829·Rc^0,484654` | Canarana-MT (13°28'S 52°16'W) | 1986–2009 | R² 0,86 | 11.874 | Almeida 2012 |
| 7 | `399,538719·Rc^0,458718` | Vera-MT (12°17'S 55°17'W) | 1975–2007 | R² 0,84 | 15.414 | idem |
| 8 | `272,865645·Rc^0,419164` | Poxoréo-MT (15°50'S 54°23'W) | — | R² 0,66 | 8.621 | idem — **só anual** |
| 9 | `147,262400·Rc^0,533025` | S. J. Rio Claro-MT (13°26'S 56°43'W) | — | R² 0,83 | 6.827 | idem |
| 10 | `73,989·Rc^0,7387` | Fortaleza-CE (Aw/As) | 1962–2000 | r 0,99 | — | Silva & Dias 2003 |
| 11 | `22,218·Rc + 119,43` / `4,7781·p − 103,18` | Fortaleza-CE | idem | r 0,96 / 0,98 | — | idem |
| 12 | `111,173·Rc^0,691` | Mococa-SP (Cwa) | pluviogramas | R² 0,991 | — | citada por Moreti 2003 e Cassol 2008 |
| 13 | `72,5488·Rc^0,8488` | Piraju-SP | DAEE 1975–97 | r 0,963 | 7.074 | Roque 2001 (⚠ Cassol cita "75,5488" por engano) |
| 14 | `106,8183 + 46,9562·Rc` | Teodoro Sampaio-SP | DAEE 1976–94 | r 0,963 | 7.172 | Colodro 2002 |
| 15 | `55,564·Rc^1,1054` | São Borja-RS (Cfa) | 1956–2003 | R² 0,841 | 9.751 | Cassol 2008 |
| 16 | `−47,35 + 82,72·Rc` / `−754,37 + 13,50·p` (só p > 55,8) | Quaraí-RS (Cfa) | 1966–2003 | R² 0,84 / 0,85 | 9.292 | Bazzano 2007 |
| 17 | `59,265·Rc^1,087` | Uruguaiana-RS (Cfa) | 1963–91; Rc 3–19 | R² 0,865 | 8.875 | Hickmann 2008 |
| 18 | `118,52·Rc^0,8034` | Santa Rosa-RS (Cfa) | 1975–2003 | R² 0,51 | 11.217 | Mazurana 2009 — **só anual** |
| 19 | `85,672·Rc^0,6557` | Lavras-MG (Cwa) | 1961–85 | r 0,979 | 5.403–6.843 | Aquino 2014 |
| 20 | `137,09·Rc^0,7717` | Vale do Rio Doce-MG | 5 min, só 2005 | R² 0,90 | — | Oliveira 2009 (não verificada) |
| 21 | `38,138·Rc + 64,866` / `7,171·p + 211,82` | Seropédica-RJ (INMET 83741) | 1974–80 | R² 0,82 / 0,78 | 5.472 | Carvalho 2005 |
| 22 | `33,856·Rc + 67,991` / `7,216·p + 186,64` | Nova Friburgo-RJ (INMET 83745) | 1974–80 | R² 0,85 / 0,87 | 5.431 | idem |
| 23 | `19,55 + 4,2·p` | Paraná | — | — | — | Rufino 1993 ⚠ (conferir unidade) |

**Notas:**
- **Uruguaiana** também tem a linear `−96,735 + 81,967·Rc` e a quadrática `−252,559 + 117,069·Rc − 1,657·Rc²`. A quadrática decresce a partir de Rc ≈ 35: **proibido extrapolar**.
- **São Borja** tem a linear `99,646 + 63,874·Rc` (R² 0,771); prefira a potência.
- **Não ativar:**
  - Lages: correlações não significativas;
  - Sete Lagoas: cúbica com 3 anos, válida só para p ≤ 350 e Rc ≤ 105.
- **Tabela `erosividade_referencia`** (para validação):
  - R publicados: Lages 5.790/5.694; Ribeirão das Lajes-RJ 6.772; Viçosa 5.892 (convertido);
  - faixas: Brasil 5.000–12.000 (Cogo, 1988); mapa de Silva (2004) 3.116–20.035; RJ 2.168–15.806.
- **Novas equações:** a biblioteca deve crescer. Trindade et al. (2016) reúnem 75 equações do Brasil. Toda equação nova só fica ativa depois de conferida no original.

### 2.6 Seleção e transferência de equação (ponto mais sensível)
Com as **mesmas médias de Cacoal-RO**, as equações acima dão R entre **6.114 e 14.424** (T9). A escolha da equação pesa mais que a interpolação.

1. **Clima antes de distância.** Use a equação de mesmo Köppen e regime de chuva; entre essas, a mais próxima. UF não é critério. Em MG, o R não se correlacionou com a P anual nem com lat/lon (Mello, 2007).
2. **Teste de similaridade** (Moreti, 2003), antes de transferir uma equação para outra estação:
   - (i) r ≥ 0,8 entre as P anuais;
   - (ii) IC95% das médias mensais se sobrepõem em ≥ 10 dos 12 meses.

   Se falhar, a equação pode ser usada, mas rebaixe a confiança.
3. **Faixa de calibração:**
   - **acima de `rc_max`:** alerta e confiança menor; polinômio é recusado;
   - **abaixo de `rc_min`:** potências com b ≈ 0,42–0,53 dão EI de ~100–150 num mês quase sem chuva. Proposta nossa (configurável): `EI = EI(rc_min)·Rc/rc_min`.
4. **Equações "só anual"** não alimentam a distribuição mensal. Nesses casos, use a distribuição mensal da equação padrão, normalizada ao R.
5. **Rondônia:** nenhum documento traz equação calibrada no estado.
   - Mantenha a padrão, por coerência com o TCC.
   - Mostre sempre a sensibilidade com as equações de Mato Grosso (Aw, chuva de out–abr).
   - A calibração local é prioridade da fase 2: verificar se há estações sub-horárias do CEMADEN em RO.
6. **Sensibilidade obrigatória:** R com a equação escolhida e com 2–3 alternativas plausíveis (mesmo clima, ≤ 1.000 km), devolvendo mínimo e máximo.

### 2.7 Unidades
- t·m·mm ha⁻¹ h⁻¹ × **9,81** = MJ mm ha⁻¹ h⁻¹. Exemplos: 6,866 → 67,355; 600,63 → 5.892; 198 → 1.942.
- Todo valor importado de artigo guarda a `unidade_original`.

## 3. Fontes de dados

### 3.1 ANA (fonte principal)
- **API REST:** `https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas`, Swagger em `/hidrowebservice/swagger-ui/index.html`.
- **Autenticação:**
  - `GET /EstacoesTelemetricas/OAUth/v1` com os headers `Identificador` e `Senha`;
  - o token vem em `tokenautenticacao` e vai em `Authorization: Bearer`;
  - validade de ~60 min: guarde em cache e renove antes, porque autenticar demais pode bloquear o IP;
  - credenciais por e-mail a `hidro@ana.gov.br`, assunto "[CPF/CNPJ] - Solicitação de acesso à API HidroWebService para consumo de dados"; guarde em variável de ambiente.
- **Endpoints:**
  - inventário: `HidroInventarioEstacoes/v1`;
  - séries convencionais de chuva: confira o endpoint no Swagger;
  - telemetria: `HidroinfoanaSerieTelemetricaAdotada/v1` (complemento). Verifique a resolução: se for ≤ 15 min, a série serve para o EI30 direto.
- **Fallback SOAP:** `https://telemetriaws1.ana.gov.br/ServiceANA.asmx` (`HidroInventario`, `HidroSerieHistorica`, `tipoDados=2`). Campos: `Chuva01..31`, status diários, `NivelConsistencia`.
- **Regras da ANA:**
  - `NivelConsistencia` 2 = consistido, 1 = bruto: prefira o 2;
  - guarde os status diários (confirme os códigos);
  - espere falhas no HidroWeb;
  - use retry com backoff e pausa entre estações.
- **Precedentes do mesmo fluxo (ANA → Rc → krigagem):** Rio Negrinho-SC, MG (248 estações; Mello, 2007) e RJ (Montebeller, 2007).

### 3.2 INMET
- **BDMEP:** `https://portal.inmet.gov.br/servicos/bdmep-dados-historicos` (séries diárias e mensais longas).
- **Estações automáticas:** dado horário; use só para totais.
- **Catálogo:** `/paginas/catalogoaut`.
- **Duplicatas com a ANA:** estações a menos de 1 km com séries coincidentes contam como uma só.

### 3.3 Fase 2
- CEMADEN (sub-horário).
- Agências e empresas: SEDAM-RO/REMAR (fonte do TCC), IAPAR, EPAGRI, DAEE, FEPAGRO, LIGHT, CENIBRA.
- **Importador CSV genérico**, incluindo EI30 já calculado pelo CHUVEROS e pluviogramas digitalizados.

## 4. Modelo de dados (PostGIS; adapte ao projeto)

- **`estacao_pluviometrica`:** fonte, código, tipo, lat, lon, altitude, `geom` (4326), município, UF, **koppen**, período, resolução em minutos.
- **`precipitacao_diaria`:** data, valor, status_origem, nivel_consistencia, flag_qualidade, fonte_versao.
- **`precipitacao_subhoraria`** (opcional).
- **`precipitacao_mensal`:** total; dias válidos e faltantes; `completo`; `preenchido` + método + estações usadas + R²; consistência; flags de dupla massa e de outlier.
- **`chuva_evento`:** E, I30, EI30, KE25, padrão, erosiva.
- **`equacao_erosividade`** (§2.5) e **`erosividade_referencia`**.
- **`erosividade_estacao`:** equação, método (A/B/C/direto), período, n_anos, n_min_mokus, R, desvio, CV, `ei_mensal[12]`, `pct[12]`, `ei_decendio[36]`, `serie_R_anual`, `retorno`, % preenchido, flags, versão.
- **`superficie_erosividade`:** grade de ~1 km com R e EI mensal, mais a variância de krigagem.
- **`erosividade_propriedade`:** todos os campos de §0 + sensibilidade + versão. **Cache por CAR**, invalidado quando o ETL gera nova versão.

## 5. ETL e controle de qualidade

1. **Erros grosseiros:**
   - datas inválidas, negativos, duplicados;
   - diário > 500 mm → suspeito, vai para revisão (não apagar);
   - se houver pluviógrafo e pluviômetro no posto, compare o total de 24 h (detecta defeito de sifonagem).
2. **Outliers (Grubbs & Beck)** nos totais anuais e mensais:
   - inferior: `X̄ − T(N,α)·S` (T de tabela; ex.: N = 20 → 2,385; N = 30 → 2,563; N = 68 → 2,883, todos com α = 10%);
   - superior: pela razão S₁²/S²;
   - outlier vai para **revisão, não exclusão**.
3. **Mês completo:** só se todos os dias forem válidos. Mês incompleto vai para o preenchimento.
4. **Preenchimento — só mensal/anual, nunca diário, e NUNCA com a média do próprio posto.** Artigos de Quaraí, São Borja e Santa Rosa fizeram isso e geraram R artificial. Ordem de preferência (Oliveira et al., 2010, Goiás, 132 simulações por método):
   1. regressão múltipla com vizinhas: `Px = a0 + Σ ai·Pi`, exigindo R² ≥ 0,7;
   2. razão das normais: `Px = (Nx/n)·Σ(Pi/Ni)`, com n ≥ 3 vizinhas de ≥ 10 anos cada;
   3. ponderação por correlação: `Px = Σ(r_i·Pi')/Σ r_i`;
   4. média simples das vizinhas: só se as normais diferirem ≤ 10%, em terreno plano;
   5. krigagem (erro de 1,4–2,4 mm em Alagoas; Wanderley, 2012).

   Regras comuns:
   - vizinhas da mesma região climática e de altitude semelhante, a ~40–80 km;
   - **semiárido:** em duas etapas (primeiro decide se choveu no mês, depois quanto);
   - marque todo valor preenchido com método e R²;
   - > 20% dos meses preenchidos → confiança menor; > 40% → estação excluída;
   - **a regressão achata a variância** (USACE, 1962). Para as estatísticas de frequência:
     - use `X₁ = M₁ + (X₂ − M₂)·S₁/S₂`;
     - ou ajuste as estatísticas: `M₁' = M₁ + (M₂' − M₂)·R·S₁/S₂` e `S₁'² = S₁² + (S₂'² − S₂²)·R²·S₁²/S₂²`.
5. **Dupla massa:** compare o acumulado da estação com a média acumulada das vizinhas.
   - Mudança de inclinação: sinalize; a correção é `Pc = Pi + (Mc/Mo)·(Po − Pi)`.
   - Preencha antes da dupla massa e revise o preenchimento depois.
6. **Testes da série anual (o resultado vira flag):**
   - aleatoriedade: pontos de inflexão, com E = 2(N−2)/3 e var = (16N−29)/90;
   - estacionariedade: Spearman;
   - independência: Wald-Wolfowitz;
   - homogeneidade: Mann-Whitney ou *run test*;
   - **tendência: Mann-Kendall** em P e em R. Na Paraíba, 38 de 52 postos tinham tendência.
7. **Anos utilizáveis** na variante (A): só os anos com os 12 meses válidos.
8. **Anomalias:** alerta para anos com total < 50% ou > 200% da média da estação e discordantes das vizinhas. Exemplos do TCC: Costa Marques, Pimenteiras. Vão para revisão, porque extremos reais existem (ex.: seca de 2005, El Niño).
9. **Período:** use sempre a série mais longa e registre o período. Lavras deu 4.865, 5.403 ou 6.843 conforme o período usado.

## 6. Cálculo por propriedade

1. Polígono do CAR → reprojeção → centroide e área.
2. **Estações:**
   - raio de 50 km; com menos de 3, amplie para 100 e depois 150 km, registrando a ampliação;
   - prefira séries ≥ 20 anos e acima do mínimo de Mokus;
   - prefira o **mesmo Köppen**;
   - em relevo acidentado, filtre por altitude (±300 m), por causa do efeito orográfico.
3. **Interpolação** do R e dos 12 EI mensais:
   - **IDW** (potência 2, 3–8 estações) como padrão;
   - **krigagem ordinária** como superfície pré-calculada offline, se houver densidade:
     - modelo escolhido por validação cruzada; teste anisotropia;
     - grau de dependência `C/(C0+C)`: > 75% forte, < 25% fraca;
     - mínimo de ~30 pontos. No RJ, 36 pluviógrafos deram pepita pura; só com 93 pontos surgiu dependência (alcance ~43 km);
     - devolva a **variância de krigagem**;
   - **fase 2:** covariáveis lat/lon/altitude, por regressão-krigagem ou rede neural (em MG, r² de 0,73–0,92);
   - estação dentro da propriedade ou a < 5 km, com boa série → peso dominante.
4. **Propriedade > 5.000 ha:** grade de 1 km dentro do polígono, com média, mínimo e máximo.
5. **Normalização:** ajuste os EI mensais e decendiais à soma do R e calcule % e % acumulada (base do fator C).
6. **Faixa de incerteza:** combine a variação dentro do polígono, a variância de krigagem, a sensibilidade entre equações e o IC do R médio (§7).

## 7. Estatísticas

- **Período de retorno empírico (Weibull):** `T = (N+1)/m` e `Pr = 100/T`, com a série em ordem decrescente.
- **Distribuição teórica — escolha por série:**
  - candidatas: Normal, LN2, LN3, Gama, Gumbel, Weibull, GEV;
  - parâmetros por máxima verossimilhança ou momentos-L;
  - aderência por KS e χ², com Anderson-Darling e Filliben de apoio;
  - na literatura, a log-normal dominou para o R anual (Fortaleza, Teodoro Sampaio, São Manuel, Rio Doce); no mensal de Lavras, LN3/Gama/Gumbel;
  - meses secos com muitos zeros: distribuição mista, ou não reporte o T mensal.
- **Fórmulas:**
  - log-normal: `X_T = X̄·(1 + Cv·k)`;
  - Gumbel–Chow: `k = −(√6/π)·[0,5772 + ln ln(T/(T−1))]` e `X_T = X̄ + k·S`.
- **IC:** IC do R médio = `R̄ ± t(0,025; N−1)·S/√N` (USACE). Para X_T, IC por bootstrap ou Jackknife.
- **Probabilidade de superar o R médio:** costuma ficar entre 34% e 48% (T de 2 a 3 anos).
- **Mínimo de anos (Mokus):** `Y = (4,30·t·log10(θ))² + 6`, com θ = X₁₀₀/X₂. Exemplos: Cuiabá 10/16 anos; Piraju 12,1/19,2 (p < 0,10 / p < 0,02).
- **Variabilidade:** mostre os percentis 10/50/90 do R anual.
  - No Sul, o El Niño elevou as perdas de solo em 12% e a La Niña as reduziu em 54%.
  - Um único evento (I30 = 126 mm/h) causou a perda de um ano inteiro de La Niña (Amado, 2002).
- **Chuva máxima diária (opcional; terraços com TR 10–15 anos):**
  - **GEV por momentos-L** quando t3/t4 se afastarem de (0,1699; 0,1504) (Silva & Clarke, 2004).
  - **Desagregação DAEE-CETESB:**

    | Relação | Coef. | Relação | Coef. |
    |---|---|---|---|
    | 24h / 1 dia | 1,14 | 30 min / 1h | 0,74 |
    | 12h / 24h | 0,85 | 25 min / 30 min | 0,91 |
    | 10h / 24h | 0,82 | 20 min / 30 min | 0,81 |
    | 8h / 24h | 0,78 | 15 min / 30 min | 0,70 |
    | 6h / 24h | 0,72 | 10 min / 30 min | 0,54 |
    | 1h / 24h | 0,42 | 5 min / 30 min | 0,34 |

    O erro chega a 44% frente a IDF de pluviograma.
  - **Bell:** `P(T,t) = (0,21·lnT + 0,52)(0,54·t^0,25 − 0,50)·P(10,60)`.
  - **Pfafstetter** (98 postos): `P = K[a·t + b·log(1 + c·t)]`, com `K = T^(α + β/T^0,25)`. Valores de α por duração: 5 min 0,108; 15 min 0,122; 30 min 0,138; 1 h 0,156; 2 h 0,166; 4 h 0,174; 8 h 0,176; 24 h 0,170. β = 0 em 5 min e 0,08 nas demais.
  - **Isozonas:** subestimaram em ≥ 10% em Manaus; use só como último recurso.

## 8. Classificação e confiança

- **Classes** (Carvalho, 1994, CPRM — confirmado):

  | R (MJ mm ha⁻¹ h⁻¹ ano⁻¹) | Classe |
  |---|---|
  | < 2.452 | baixa |
  | 2.452–4.905 | média |
  | 4.905–7.357 | média a forte |
  | 7.357–9.810 | forte |
  | > 9.810 | muito forte |

- **Mês crítico:** EI > 500 (Rufino, 1986).
- **Período crítico:** o menor bloco de meses consecutivos com ≥ 70% do R. Referências:
  - Rondônia, out–abr: ~96%;
  - Cuiabá: 87%;
  - São Borja: 76%;
  - Santa Rosa: 60% (chuva bem distribuída).
- **Texto ao produtor (opcional):**
  - Em RO, outubro é ~388% mais erosivo que setembro e coincide com o plantio.
  - Palhada: 2 t/ha reduz a perda em ~50%; 8 t/ha, em ~90%.
  - Plantio direto: −99% de perda de solo.
  - Contorno: −53% a −97%.
  - Queimadas de pasto em agosto–setembro deixam o solo descoberto na entrada das chuvas.
- **Confiança (alta/média/baixa), sempre com os motivos.** Critérios:
  - nº de estações e distância da mais próxima;
  - série frente a 20 anos e ao mínimo de Mokus;
  - % e método do preenchimento;
  - equação: regional verificada, transferência validada ou padrão;
  - Rc fora da faixa de calibração;
  - **clima Cfa/Cfb ou Nordeste com dois regimes → confiança no máximo "média"** no método Rc;
  - flags de dupla massa, tendência, outlier e anomalia;
  - método direto ou Rc;
  - sensibilidade entre equações > 25% e variância de krigagem.

## 9. API e interface

- **Endpoints:**
  - `POST /api/erosividade/propriedade {car}` (com cache);
  - `GET /api/erosividade/estacoes?bbox=`;
  - admin: rodar o ETL, reprocessar estação, conferir/ativar equação, teste de similaridade.
- **Tela:**
  - mapa com o polígono, as estações (raio, peso, Köppen) e a superfície;
  - card com R, faixa, classe e confiança;
  - barras do EI mensal com curva da % acumulada e linha de 500; aba de decêndios;
  - tabela de período de retorno com IC;
  - painel de sensibilidade;
  - seção "Metodologia e fontes";
  - exportação em PDF/CSV;
  - unidades sempre visíveis.

## 10. Extensão futura: perda de solo (só preparar as estruturas)

- **Fórmulas:** `PNE = R·K·LS` e `A = R·K·LS·C·P`.
- **LS:**
  - `0,00984·L^0,63·S^1,18` (Bertoni & Lombardi);
  - parcela: `(L^0,5/100)(1,36 + 0,975S + 0,1385S²)`;
  - S da USLE: `0,065 + 4,56 senθ + 65,41 sen²θ`;
  - MDE: `(AF·l/22,13)^0,4·(senθ/0,0896)^1,3`, com SRTM/Copernicus 30 m.
- **K** (Mg h MJ⁻¹ mm⁻¹):
  - faixas de Denardin: B latossólico 0,002–0,034; B textural 0,004–0,044;
  - exemplos: LV distroférrico 0,0032–0,0091; LE 0,002; PV 0,033; Argissolo arênico 0,033; Cambissolo 0,0355–0,0356; Litossolo 0,0458.
- **C:**
  - por uso: mata 0,001; reflorestamento 0,004; campo 0,01; solo exposto 1,0;
  - culturas: por estádio, ponderado pela % do EI por decêndio.
- **P:** morro abaixo 1,0; contorno 0,5; capinas alternadas + contorno 0,4; cordões 0,2.
- **Tolerância (T):** h = profundidade efetiva até 1.000 mm. Para t/ha·ano: mm × 10 × densidade.
  - **Método I:** `T = h·r/1000`, com r pela relação textural B/A (argila): < 1,5 → 1,0; 1,5–2,5 → 0,75; > 2,5 → 0,5.
  - **Método II:** troca r por ra, conforme a relação textural e a argila do horizonte A:

    | Relação B/A | Argila A > 40% | 20–40% | < 20% |
    |---|---|---|---|
    | < 1,5 | 1,0 | 0,9 | 0,8 |
    | 1,5–2,0 | 0,8 | 0,7 | 0,6 |
    | > 2,0 | 0,6 | 0,5 | 0,4 |

  - **Método III:** `T = h·ra·m·p/1000`.
    - m (matéria orgânica, 0–20 cm): > 2% → 1,15; 1–2% → 1,00; < 1% → 0,85;
    - p (permeabilidade): rápida 1,15; moderada 1,00; lenta 0,85.
  - **Referências (t/ha·ano):**
    - sul do AM: Argissolos 7,3–8,9; Latossolos 12,5–13,1; Cambissolos 13,2–15,2;
    - SP: Latossolos 9,6–15;
    - Lavras: Cambissolo 5,6; Latossolo 12,7;
    - FAO: 12 em solos profundos; 2–4 em rasos.

## 11. Testes obrigatórios

**T1 — Variante (B) com a equação padrão** (médias da Tabela 2 do TCC; tolerância ±0,1%):

| Município | Médias jan→dez (mm) | P anual | R(B) |
|---|---|---|---|
| Cacoal | 266,5; 265,4; 257,9; 136,4; 44,1; 23,6; 13,6; 11,4; 61,9; 162,0; 198,3; 233,0 | 1674,2 | **8.544,95** (jan 1.628,62) |
| Vilhena | 348,3; 327,9; 300,5; 179,7; 70,3; 13,5; 8,5; 40,6; 75,8; 185,3; 247,8; 275,8 | 2073,9 | **10.170,92** |
| Min. Andreazza | 367,5; 332,8; 295,6; 159,4; 62,1; 13,2; 14,9; 15,2; 65,6; 140,0; 196,5; 287,1 | 1949,9 | **10.098,73** |
| Costa Marques | 141,2; 170,7; 165,5; 66,3; 27,4; 10,2; 12,7; 11,0; 27,4; 85,5; 101,5; 145,8 | 928,9 | **5.644,18** |

Em Costa Marques, a soma dos meses (965,2) ≠ P informado. O teste usa o P informado, e o ETL deve sinalizar a inconsistência.

**T2 — Variante (A):**
- R publicados no TCC: 8.836,76; 10.538,32; 10.473,55; 5.811,88;
- com as séries da ANA, R(A) > R(B) em ~2–6%;
- out–abr concentra ~95–97% do R.

**T3 — Weibull:**
- N = 30, m = 1 → T = 31,0; Pr = 3,2%;
- N = 30, m = 30 → T = 1,03;
- N = 20, m = 1 → T = 21,0; Pr = 4,8%.

**T4 — Razão das normais:** Nx = 1.155; vizinhas 126/1.323, 105/1.104 e 144/1.416 → **Px = 112,44**.

**T5 — Energia cinética:**
- Foster: I = 10 → 0,2063; I = 50 → 0,2673; I ≥ 76 → 0,283;
- W&M: I = 50 → 0,2626; I = 100 → 0,2743.

**T6 — LS de parcela:**
- L = 9, S = 15% → 1,414;
- L = 9, S = 12% → 0,990;
- (22,13; 9%) → ≈ 1,00.

**T7 — Robustez:**
- p = 0 → EI = 0;
- equações em p respeitam `p_min`;
- ano incompleto fica fora da variante (A);
- preenchimento pela média do posto → o teste falha;
- nenhuma estação em 150 km → erro claro;
- CAR inválido → erro do módulo existente.

**T8 — Integração:** um CAR da região de Rolim de Moura dá R ≈ 8.000–10.500, com confiança coerente.

**T9 — Sensibilidade** (médias de Cacoal, variante B, ±0,5%):

| Equação | R | Equação | R |
|---|---|---|---|
| Padrão | 8.544,9 | Canarana | 12.392,3 |
| Cuiabá | 9.755,5 | S. J. Rio Claro | 6.670,9 |
| Cáceres | 7.616,9 | Poxoréo | 8.759,6 |
| Rondonópolis | 6.113,6 | Mococa | 8.332,1 |
| Vera | 14.424,0 | Piraju | 9.166,9 |

**T10 — Equações com Rc = 20:**
- padrão 859,50; Cuiabá 1.016,32; Mococa 881,07; São Borja 1.523,88; Uruguaiana 1.538,22;
- Piraju com Rc = 25,85 → 1.146,90.

**T11 — Faixa de calibração:**
- Uruguaiana quadrática com Rc = 40 → recusada;
- Vera com Rc < `rc_min` → aplica a regra de §2.6 e grava alerta.

**T12 — Conversão:** 600,63 → 5.892,18; 6,866 → 67,355; 198 → 1.942,38.

**T13 — Gumbel–Chow:** k(10) = 1,3046; k(100) = 3,1367.

**T14 — Mokus:** θ = 15.852/8.442, t = 1,740 → Y ≈ 10,2 anos.

**T15 — Grubbs-Beck:** X̄ = 20,01; S² = 27,83; T = 2,883 → limite inferior 4,80.

**T16 — Chuvas intensas:**
- CETESB: 1 dia = 100 mm → 24 h = 114,0; 1 h = 47,88; 30 min = 35,43;
- Bell: fator 1,0065 para T = 10 e t = 60;
- Pfafstetter: K(10; 1 h) = 1,5885.

**T17 — Tolerância (Método I):** h = 1.200 (limitado a 1.000), relação B/A = 1,25, densidade 1,2 → 12,0 t/ha·ano.

**T18 — IC do R médio:** R̄ = 8.810, S = 2.244, N = 18, t = 2,110 → 7.694 a 9.926.

## 12. Regras

- Não invente números. Sem dado → erro ou confiança baixa, com o motivo.
- Não use dado horário para I30. Não preencha dado diário. Não preencha com a média do posto. Não extrapole equações; polinômio nunca.
- Confira toda equação no original antes de ativar.
- Todo parâmetro fica em configuração ou tabela, com a referência.
- Registre a proveniência: versão e data dos dados, nível de consistência, % e método de preenchimento.
- Testes unitários para cada fórmula e teste de integração CAR → R.
- README com metodologia, fontes e limitações:
  - a USLE dá média de longo prazo, não evento isolado;
  - não considera deposição;
  - o Rc mede volume, não intensidade.

## 13. Ordem de entrega

1. Plano + migrações + carga da biblioteca (só a padrão ativa).
2. Cliente da ANA (REST + SOAP) + INMET + importador CSV.
3. ETL de qualidade (§5) + job agendado.
4. R por estação (A/B/C, decêndios, Mokus) + testes T1–T5 e T9–T18.
5. Seleção de equação e sensibilidade + cálculo por propriedade + estatísticas + confiança.
6. API e interface.
7. Fase 2: EI30 direto, calibração local, krigagem e covariáveis, ENOS, extensão USLE.

Ao fim de cada etapa, rode os testes e me mostre um resumo do que mudou.

## 14. Referências (resumidas)

- **Rondônia, MT e Amazônia:**
  - Moreira, TCC UNIR 2014;
  - Almeida et al., RBEAA 2011 (Cuiabá) e 2012 (MT);
  - Nunes et al., Ambiência 2012 (tolerância, AM);
  - Moline et al., 2011 (palhada, RO);
  - Plano Territorial Central-RO;
  - Silva Filho et al., 2009 (SIPAM);
  - Pontes & Fernandes (isozonas);
  - Moraes et al., 2007 (PA).
- **Equações:**
  - Lombardi Neto & Moldenhauer, Bragantia 1992;
  - Silva & Dias / Dias & Silva, RBCS 2003;
  - Roque, RBCS 2001; Colodro, RBCS 2002; Moreti, RBCS 2003;
  - Cassol, RBCS 2008; Bazzano, RBCS 2007; Hickmann, RBCS 2008; Mazurana, RBEAA 2009;
  - Bertol, PAB 1993 e RBCS 2002;
  - Mello et al., PAB 2007;
  - Evangelista, Irriga 2006; Aquino, Rev. Ceres 2014;
  - Oliveira, Ciênc. Agrotec. 2009;
  - Marques et al., RBCS 1997 e PAB 1998; Boaretto, Rev. Ceres 1998;
  - Carvalho et al., RBEAA 2005; Machado et al., RBCS 2008;
  - Montebeller, Eng. Agríc. 2007; Moreira, Eng. Agric. 2009 (redes neurais);
  - Checchia (Rio Negrinho); Albuquerque, RBCS 1998 e RBEAA 2002;
  - Carvalho, *Hidrossedimentologia prática* 1994;
  - Foster et al., JSWC 1981; Wischmeier & Smith, 1978;
  - Rufino, RBCS 1993; Trindade, PAB 2016.
- **Perdas e manejo:**
  - Amado, RBCS 2002 (El Niño); Cogo, RBCS 2003; Eltz, RBCS 2001;
  - Hernani, RBCS 1999; Garbiate, RBCS 2011;
  - Margolis 1991; Santos, PAB 1998; Thomazini 2012; Ranzini & Lima 2002; Bertol 2011.
- **Chuva e estatística:**
  - Oliveira et al., RBEAA 2010 (falhas); Wanderley, RBMet 2012; Oliveira (semiárido, UFAL);
  - Silva & Clarke, RBMet 2004; Sansigolo, RBMet 2008; Beijo (Lavras);
  - Catalunha (FDPs MG); Ribeiro 2007; Mello & Silva, RBEAA 2009 e *Hidrologia estatística*;
  - Sentelhas, RBMet 1998; Back, RBEAA 2009;
  - Oliveira, IDF Goiás 2005/2008; Genovez & Zuffo, RBRH 2000; Martinez Jr.; Vieira 1998;
  - Silva 2009 (PE); Diniz 2013 (PB); Longo 2006 (Cascavel);
  - DNIT (Pfafstetter); Bertoni & Tucci; USACE, *Statistical Methods in Hydrology*, 1962;
  - ANA, Manual HidroWebService.
