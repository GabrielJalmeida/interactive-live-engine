# Interactive Live Engine

Infraestrutura modular e reutilizável para desenvolver experiências interativas controladas por eventos de transmissões ao vivo.

**Estado atual:** Fase 2 — Runtime e contrato de Experience. O projeto inclui os contratos de domínio, registro explícito de factories, ciclo de vida de uma Experience ativa, roteamento de eventos e endpoints de consulta do Runtime. Provider TikTok, pipeline de ingestão, persistência, Dev API e WebSocket ainda não foram implementados.

## Princípios

- O projeto é independente do repositório `live-tiktok`/WORLD001.
- Nenhum módulo do projeto antigo é importado.
- O Core deverá receber e normalizar eventos; cada Experience decidirá seu significado.
- O projeto começa como monólito modular, com dependências explícitas e testes por fatia vertical.
- O endpoint atual é de liveness da aplicação: ele **não** afirma que provider, Runtime ou banco estão operacionais.

## Requisitos

- Python 3.12, 3.13 ou 3.14.
- Windows, macOS ou Linux.

## Setup local — Windows CMD

Execute os comandos a partir da raiz deste repositório:

```bat
py -3 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
copy .env.example .env
python -m pytest -q
```

Se estiver usando PowerShell, ative o ambiente com:

```powershell
.venv\Scripts\Activate.ps1
```

As dependências diretas estão fixadas em versões exatas nos arquivos `requirements*.txt`. A instalação e a resolução transitiva devem ser verificadas em clone limpo na máquina-alvo antes de considerar o bootstrap reproduzível.

## Executar a API

```bat
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

Health endpoint: <http://127.0.0.1:8000/api/v1/health>

OpenAPI: <http://127.0.0.1:8000/docs>

## Testes e qualidade

```bat
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

## Estado do roadmap

- [x] Factory da aplicação e composição inicial sem integrações globais de gameplay.
- [x] Configuração central validada.
- [x] `GET /api/v1/health`.
- [x] Smoke tests para endpoint e validação da configuração.
- [ ] Validar instalação/testes a partir de clone limpo no ambiente-alvo.
- [ ] Inicializar Git e registrar o primeiro commit.
- [x] Definir `EventType`, `EventProvider`, `Viewer`, `LiveEvent` e `OutputEvent`.
- [x] Validar timestamps UTC, schemas estritos e limites iniciais de JSON.
- [x] Documentar o contrato e registrar ADR-002.
- [x] Definir `InteractiveExperience` e `ExperienceContext` com contexto consistente no lifecycle.
- [x] Implementar `ExperienceLoader`, `ExperienceManager`, `EventRouter` e `EngineRuntime`.
- [x] Adicionar `GET /api/v1/engine/state` e `GET /api/v1/experiences`.
- [x] Validar lifecycle, erros, metadados e outputs com FakeExperience restrita aos testes.
- [ ] Registrar o checkpoint Git da Fase 2 após validação no ambiente-alvo.

## Segurança e escopo

Não há provider ativo, conexão externa, banco, Dev API ou comandos de gameplay nesta fase. Não adicione segredos ao `.env.example`; o arquivo `.env` local é ignorado pelo Git.
