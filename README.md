# Interactive Live Engine

Infraestrutura modular e reutilizável para desenvolver experiências interativas controladas por eventos de transmissões ao vivo.

**Estado atual:** Fase 4 — ingestão e Dev Event API. O projeto inclui contratos de domínio, Runtime/Experience, WebSocket server-to-client, `EventIngestionService` e endpoint de simulação restrito a development/test. A deduplicação nesta fase vive em memória; persistência, provider TikTok e entrega durável ainda não foram implementados.

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

Harness WebSocket (development/test): <http://127.0.0.1:8000/dev/realtime-harness>

Dev Event API: `POST /api/v1/dev/events` (somente development/test). O endpoint exige uma Experience ativa e retorna `409 NO_ACTIVE_EXPERIENCE` quando nenhuma está ativa. O repositório não inclui uma Experience de demonstração; o fluxo completo é validado com fakes restritos aos testes.

WebSocket: `ws://127.0.0.1:8000/ws/events` (use `wss://` quando servido por HTTPS). A conexão recebe `SYSTEM_READY` e depois `OutputEvent`. O canal é somente server-to-client; mensagens de aplicação enviadas pelo cliente são encerradas com código `1008`. Browser origins devem ser same-origin. Mantenha o servidor no loopback por enquanto; não o exponha à rede pública sem autenticação, política de origem e configuração operacional próprias.

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
- [x] Inicializar Git e registrar commits independentes por fatia.
- [x] Definir `EventType`, `EventProvider`, `Viewer`, `LiveEvent` e `OutputEvent`.
- [x] Validar timestamps UTC, schemas estritos e limites iniciais de JSON.
- [x] Documentar o contrato e registrar ADR-002.
- [x] Definir `InteractiveExperience` e `ExperienceContext` com contexto consistente no lifecycle.
- [x] Implementar `ExperienceLoader`, `ExperienceManager`, `EventRouter` e `EngineRuntime`.
- [x] Adicionar `GET /api/v1/engine/state` e `GET /api/v1/experiences`.
- [x] Validar lifecycle, erros, metadados e outputs com FakeExperience restrita aos testes.
- [x] Registrar o checkpoint Git da Fase 2 após validação no ambiente-alvo.
- [x] Implementar `RealtimeManager` com timeout de envio e falha isolada por conexão.
- [x] Adicionar `WS /ws/events` com envelope inicial `SYSTEM_READY` e canal unidirecional.
- [x] Ligar `EngineRuntime.publish()` ao publisher injetado sem acoplar o Runtime ao WebSocket concreto.
- [x] Adicionar harness browser local, restrito a development/test.
- [x] Testar broadcast, desconexão, timeout, erro individual e fluxo Runtime→WebSocket.
- [x] Implementar `EventIngestionService` com Runtime e deduplicação injetados.
- [x] Adicionar `POST /api/v1/dev/events`, schemas estritos e resposta `processed`/`duplicate`.
- [x] Restringir Dev Event API aos ambientes development/test, omitindo-a em production.
- [x] Cobrir dispatch, publicação, duplicidade, payload inválido, falha, retry e ausência de Experience.
- [ ] Substituir deduplicação volátil pela persistência/constraint de banco na Fase 5.
- [ ] Registrar o checkpoint Git da Fase 3 após os testes locais.
- [ ] Validar ingestão no ambiente-alvo e registrar o checkpoint Git da Fase 4.

## Segurança e escopo

Não há provider TikTok ativo nem persistência nesta fase. A deduplicação do Dev Event API é apenas em memória e será perdida quando o processo reiniciar. O realtime usa entrega em memória e best-effort: desconexão significa que uma mensagem pode ser perdida; replay, outbox e entrega durável continuam fora do MVP atual. Não adicione segredos ao `.env.example`; o arquivo `.env` local é ignorado pelo Git.
