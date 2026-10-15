# ADR-005 — Ingestão central e Dev Event API

- **Status:** Aceito para MVP
- **Fase:** 4 — Ingestão e Dev Event API

## Contexto

A Engine precisa de um caminho único para encaminhar `LiveEvent` normalizado ao Runtime e publicar os `OutputEvent` produzidos pela Experience. O desenvolvimento não deve depender de uma LIVE real, mas ferramentas de simulação não podem ficar expostas em produção.

## Decisão

- `EventIngestionService` recebe `EngineRuntime` e um port de deduplicação por injeção.
- A reserva da chave elegível `(provider, provider_event_id)` acontece antes do dispatch. Sem ID externo, o evento não é deduplicado.
- Eventos duplicados retornam `200` com `status: "duplicate"` e não chamam a Experience novamente.
- Se o dispatch falhar, a reserva é liberada para permitir retry; se o processamento terminar e a publicação falhar, a reserva é mantida para reduzir o risco de reaplicar efeitos de gameplay.
- `POST /api/v1/dev/events` constrói `provider=simulator` e `event_id` no servidor. O cliente não pode escolher provider nem identificador interno.
- A rota é registrada somente nos ambientes `development` e `test`; em `production` ela não é incluída.
- Nesta fase, `InMemoryEventDeduplicationStore` é uma implementação temporária, apropriada apenas ao processo local/teste. A Fase 5 substituirá esse port por persistência e unicidade no banco.

## Alternativas consideradas

- Fazer cada rota despachar diretamente ao Runtime: rejeitado porque duplica orquestração e regras de falha.
- Conectar eventos simulados diretamente à Experience: rejeitado porque deixaria de validar o mesmo fluxo usado pelo provider.
- Fingir deduplicação durável com um conjunto em memória: rejeitado; a implementação explicita que perde estado em reinícios e não promete exactly-once.
- Registrar a Dev API em todos os ambientes e apenas escondê-la no cliente: rejeitado porque ausência de UI não é uma barreira de segurança.

## Consequências e limitações

- Testes podem validar ingestão sem rede externa, TikTok ou banco.
- A resposta informa `processed`/`duplicate`, identificador do evento, outputs e contagem de clientes alcançados pelo transport.
- O fluxo de processamento e o transporte de outputs permanecem separados. Não há transação comum entre gameplay e WebSocket; durabilidade/outbox ficam para evolução posterior se requisitos e testes a justificarem.
- O app base não inclui uma Experience. A rota retorna `409 NO_ACTIVE_EXPERIENCE` até que uma Experience seja registrada e iniciada pela composição da aplicação.
