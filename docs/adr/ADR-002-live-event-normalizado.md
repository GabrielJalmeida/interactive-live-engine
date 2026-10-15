# ADR-002 — Contrato interno de evento normalizado

- **Status:** Aceito
- **Fase:** 1 — Contratos de evento

## Contexto

A Engine precisa receber eventos de um provider externo e encaminhá-los a uma Experience sem expor o SDK do provider nem incorporar regras de gameplay ao domínio central.

## Decisão

Definir `EventType`, `EventProvider`, `Viewer`, `LiveEvent` e `OutputEvent` em `backend.app.domain.events`, usando modelos Pydantic estritos. Timestamps devem ser timezone-aware e são normalizados para UTC. Payloads são objetos JSON limitados por tamanho e profundidade. Campos não declarados são rejeitados. Rose permanece no tipo genérico `GIFT`.

## Alternativas consideradas

- **Usar diretamente os objetos TikTokLive:** rejeitado porque acopla Runtime e Experiences ao provider.
- **Usar dicionários sem contrato:** rejeitado porque enfraquece validação, documentação e testes.
- **Criar schemas específicos de cada jogo no Core:** rejeitado porque regras e significados pertencem à Experience.

## Consequências

- Contratos podem ser testados sem rede, API, banco ou TikTok LIVE.
- O adapter deve converter dados externos explicitamente.
- Providers novos exigirão adicionar/confirmar seus identificadores controlados e atualizar os testes.
- Limites atuais de payload são conservadores e podem ser revisados com evidência.
