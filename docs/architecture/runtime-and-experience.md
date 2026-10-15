# Runtime e contrato de Experience

## Responsabilidades

- `InteractiveExperience` define lifecycle, tratamento de `LiveEvent`, estado e health.
- `ExperienceContext` é criado para uma ativação e fornece slug, configuração e logger.
- `ExperienceLoader` mantém somente factories registradas explicitamente; não importa código pedido por clientes.
- `ExperienceManager` possui no máximo uma Experience ativa, controla start/stop e valida outputs.
- `EventRouter` encaminha `LiveEvent` ao manager sem interpretar gameplay.
- `EngineRuntime` oferece a fachada de lifecycle/dispatch e estado conciso.

## Decisões de lifecycle

- `start` enquanto outra Experience está iniciando/ativa/parando falha com `ExperienceLifecycleError`.
- Se `start` falhar, o manager tenta `stop` como limpeza, preserva a exceção original e marca o estado `failed`.
- `stop` sem Experience ativa é um no-op idempotente que retorna `False`.
- `stop` da Experience ativa sempre remove a referência ativa; se falhar, a falha propaga e o manager fica `failed`.
- Dispatch sem Experience ativa falha de forma explícita.
- `handle_event` deve retornar `list[OutputEvent]`; cada output deve identificar a Experience que o produziu.
- Estado e health são dicionários JSON e são validados antes de retornados.

## Integração HTTP

- `GET /api/v1/engine/state` retorna Runtime, slug ativa e status do lifecycle sem revelar estado de gameplay.
- `GET /api/v1/experiences` lista apenas factories registradas no processo; não é catálogo e não executa imports dinâmicos.
- A aplicação padrão não registra uma Experience concreta. Jogos futuros e testes fazem registro na composição que os possui.

## Limites atuais

Não há provider, ingestion pipeline, persistência, realtime/WebSocket, comando de inicialização automática por `ACTIVE_EXPERIENCE` ou experiência de demonstração embarcada. Essas etapas terão seus próprios slices e critérios de aceite.
