# Interactive Live Engine

Infraestrutura modular e reutilizável para desenvolver experiências interativas controladas por eventos de transmissões ao vivo.

**Estado atual:** Fase 6 — adaptador TikTok LIVE implementado com testes locais; validação com transmissão real pendente para uma sessão agendada. O provider permanece desabilitado por padrão. A entrega durável de outputs ainda não foi implementada.

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

As dependências diretas estão fixadas em versões exatas nos arquivos `requirements*.txt`. `requirements-provider.txt` adiciona o adaptador externo opcional TikTokLive sem obrigar a instalação dessa dependência nos ambientes que só usam o Core. A instalação e a resolução transitiva devem ser verificadas em clone limpo na máquina-alvo.

## Executar a API

```bat
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

Health endpoint: <http://127.0.0.1:8000/api/v1/health>

OpenAPI: <http://127.0.0.1:8000/docs>

Harness WebSocket (development/test): <http://127.0.0.1:8000/dev/realtime-harness>

Dev Event API: `POST /api/v1/dev/events` (somente development/test). O endpoint exige uma Experience ativa e retorna `409 NO_ACTIVE_EXPERIENCE` quando nenhuma está ativa. O repositório não inclui uma Experience de demonstração; o fluxo completo é validado com fakes restritos aos testes.

WebSocket: `ws://127.0.0.1:8000/ws/events` (use `wss://` quando servido por HTTPS). A conexão recebe `SYSTEM_READY` e depois `OutputEvent`. O canal é somente server-to-client; mensagens de aplicação enviadas pelo cliente são encerradas com código `1008`. Browser origins devem ser same-origin. Mantenha o servidor no loopback por enquanto; não o exponha à rede pública sem autenticação, política de origem e configuração operacional próprias.

## Provider TikTok LIVE — Fase 6

A integração usa `TikTokLive==7.0.1` como dependência opcional, sem obrigar sua instalação nos ambientes que utilizam somente o Core. O SDK é importado sob demanda, quando `TIKTOK_LIVE_ENABLED=true`. Por padrão, nenhum listener é iniciado nem há conexão com o TikTok. A biblioteca é um cliente de terceiros não oficial, baseado no Webcast interno e sujeito a mudanças do TikTok. Embora o pacote declare `Requires-Python >=3.10`, seus classifiers publicados chegam ao Python 3.13. Neste ambiente com Python 3.14, a instalação e o teste básico de importação foram concluídos com sucesso; a compatibilidade operacional com uma transmissão real ainda precisa ser validada na sessão agendada. Fonte: https://pypi.org/project/TikTokLive/.

Para preparar o ambiente (não abre uma live nem conecta ao TikTok):

```bat
python -m pip install -r requirements-provider.txt
python -c "from TikTokLive import TikTokLiveClient; from TikTokLive.events import CommentEvent, GiftEvent; print('TikTokLive import OK')"
python -m pytest -q
```

Mantenha `TIKTOK_LIVE_ENABLED=false` durante o desenvolvimento normal. Somente no dia reservado para o teste real, configure no `.env` de desenvolvimento:

```dotenv
TIKTOK_LIVE_DIAGNOSTICS_ENABLED=true
TIKTOK_LIVE_ENABLED=true
TIKTOK_LIVE_USERNAME=seu_usuario_sem_arroba
```

Com `TIKTOK_LIVE_DIAGNOSTICS_ENABLED=true`, a aplicação registra e ativa a Experience de diagnóstico **antes** de iniciar o listener. Ela emite `PROVIDER_EVENT_RECEIVED` com resumo sanitizado, sem reproduzir texto de comentários nem identidade do usuário. Essa Experience é uma ferramenta de teste, não gameplay, e o modo diagnóstico é recusado em `APP_ENV=production`.

No dia do teste, inicie a sua transmissão primeiro e, em outra janela, rode `python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`. Depois abra <http://127.0.0.1:8000/dev/realtime-harness> e observe os outputs; consulte <http://127.0.0.1:8000/api/v1/providers/tiktok> para comparar eventos recebidos e processados. Se o canal estiver offline ou o provider falhar ao iniciar, a inicialização da aplicação falha deliberadamente em vez de fingir que a conexão está pronta. No fim da sessão, desligue o servidor e volte `TIKTOK_LIVE_ENABLED=false` e `TIKTOK_LIVE_DIAGNOSTICS_ENABLED=false`. Não habilite essas opções antes do dia de teste.

Para simular sem uma live, mantenha `TIKTOK_LIVE_ENABLED=false`, inicie a aplicação e use `POST /api/v1/dev/provider-diagnostics/start`; então envie evento(s) ao `POST /api/v1/dev/events`. Essas rotas não existem em production.

O estado operacional fica disponível em `GET /api/v1/providers/tiktok`, com estado e contadores de eventos normalizados/processados/falhos; o endpoint não retorna comentários, nomes de usuários nem payloads. Eventos sem identificador de mensagem confiável não recebem um ID sintético e não podem ser deduplicados com segurança. Atualizações intermediárias de streak de presentes são ignoradas; o evento final preserva a quantidade final.

**Dados e retenção:** eventos normalizados seguem a política de persistência da Engine. Comentários e identidade mapeada do viewer podem ficar gravados em `live_event_records` até a expiração da retenção padrão de 7 dias. Proteja o arquivo do banco e seus backups, e execute o script de expurgo documentado. A Experience de diagnóstico não repete o texto do comentário nem o nome/identidade do usuário nos outputs, mas isso não significa que esses dados sejam removidos da persistência.

**Limite conhecido:** a Engine não inclui uma Experience de gameplay padrão. Para o primeiro teste real, `TIKTOK_LIVE_DIAGNOSTICS_ENABLED=true`, em development/test, permite registrar e iniciar automaticamente uma Experience de diagnóstico quando nenhuma outra está ativa. Esse modo verifica o fluxo de eventos sem implementar gameplay. Para jogar de verdade, será necessário desenvolver, registrar e iniciar uma Experience própria. Esta fase possui testes automatizados com fakes, mas ainda não valida conectividade real, recebimento de eventos reais, comportamento após mudanças no TikTok ou reconexão automática. A estratégia de reconexão/backoff será decidida com base nas evidências do primeiro teste real.

**Licença da dependência:** TikTokLive informa uma licença modificada AGPL-3.0. Antes de distribuir uma aplicação comercial/fechada que a incorpore, revise a licença completa e sua exceção de integração com aconselhamento apropriado; a dependência opcional isolada não elimina essa obrigação.

## Banco e migrations

A aplicação usa SQLite local por padrão. Caminhos relativos de SQLite são resolvidos a partir da raiz do repositório, independentemente da pasta atual do CMD. Em development/production, a store SQLAlchemy é composta pela aplicação; em `APP_ENV=test`, a store em memória é usada por padrão para manter testes isolados, podendo ser substituída por injeção explícita.

Depois de instalar as dependências e criar o `.env`, aplique o esquema do banco:

```bat
python -m alembic upgrade head
python -m alembic check
```

Para retornar ao esquema vazio durante desenvolvimento local, use `python -m alembic downgrade base` (isso remove as tabelas geridas pela migration). Não use downgrade em um banco com dados que precisem ser preservados.

O histórico `live_event_records` preserva tentativas e estados `RECEIVED`, `PROCESSED` ou `FAILED`. A tabela `event_deduplication_keys` mantém uma chave única `(provider, provider_event_id)` para eventos elegíveis. Quando o dispatch falha, a tentativa permanece registrada como `FAILED`, e apenas sua chave de deduplicação é liberada para retry. IDs externos ausentes não podem ser deduplicados com segurança.

A retenção inicial é de 7 dias (`EVENT_RECORD_RETENTION_DAYS`, configurável entre 1 e 365). A limpeza não roda silenciosamente dentro do servidor: execute `python -m scripts.purge_expired_event_records` por agendador operacional ou manualmente. Faça backup antes de qualquer manutenção em um banco que contenha dados importantes.

O SQLite valida a lógica funcional local. A concorrência e as constraints do banco-alvo PostgreSQL ainda devem ser verificadas antes de declarar a persistência pronta para operação sustentada. Não há garantia geral de exactly-once nem outbox nesta fase.

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
- [x] Substituir deduplicação volátil pela store SQLAlchemy e constraint composta na Fase 5.
- [x] Validar o realtime no ambiente-alvo e recuperar a estrutura canônica do projeto.
- [x] Testar migrations a partir de banco vazio e persistência/deduplicação no SQLite.
- [ ] Executar testes e lint/format desta fase no ambiente-alvo.
- [ ] Validar concorrência no PostgreSQL antes de operação sustentada.

## Segurança e escopo

O provider TikTok permanece desativado por padrão e sua conexão real ainda não foi validada. A Experience `provider-diagnostics` é uma ferramenta opt-in de desenvolvimento/teste, nunca registrada automaticamente no setup normal e indisponível em production. A deduplicação é persistente no banco configurado quando usada a store SQLAlchemy; testes podem usar a store em memória. O realtime usa entrega em memória e best-effort: desconexão significa que uma mensagem pode ser perdida; replay, outbox e entrega durável continuam fora do MVP atual. Não adicione segredos ao `.env.example`; o arquivo `.env` local é ignorado pelo Git.

### Fase 6 — TikTok LIVE provider

- [x] Normalizador de eventos TikTokLive desacoplado do Core.
- [x] Listener injetável, ciclo de vida startup/shutdown e estado operacional.
- [x] Configuração opt-in; listener desativado por padrão.
- [x] Testes automatizados sem conexão real.
- [x] Instalar e verificar a dependência opcional no ambiente Python atual.
- [ ] Ativar uma Experience adequada e validar conexão/eventos em uma live real numa sessão agendada.
- [ ] Decidir reconexão/backoff com evidência do primeiro teste real.
