# ADR-006 — Persistência de eventos e reserva idempotente

- **Status:** Aceito
- **Fase:** 5 — Persistência

## Contexto

A deduplicação em memória não resiste ao reinício do processo e não coordena corretamente múltiplas instâncias. O pipeline também precisa registrar recebimento, sucesso e falha para diagnóstico.

## Decisão

- Usar SQLAlchemy 2.x com sessões curtas e independentes; operações síncronas do driver são encaminhadas para `asyncio.to_thread` pelo adapter para não bloquear diretamente o event loop da API.
- Usar Alembic para todas as alterações de schema; a aplicação não executa `create_all` automaticamente.
- Guardar cada tentativa em `live_event_records`, com status controlado `RECEIVED`, `PROCESSED` ou `FAILED`.
- Manter a reserva de unicidade em `event_deduplication_keys`, cuja chave primária é `(provider, provider_event_id)`. Separar a reserva do histórico permite preservar uma falha e liberar somente sua chave para retry.
- Persistir `PROCESSED` antes da publicação de outputs. Se a publicação falhar, manter a reserva para evitar executar novamente os efeitos da Experience em uma redelivery.
- Manter uma política explícita de retenção de eventos, configurada por `EVENT_RECORD_RETENTION_DAYS` e aplicada pelo script manual de limpeza.

## Consequências e limites

- A constraint composta, e não apenas uma consulta prévia, decide qual solicitação concorrente adquire a chave.
- IDs externos ausentes não podem ser deduplicados entre eventos internos diferentes.
- Processamento de gameplay e publicação não são uma única transação; ainda não existe outbox e não há garantia geral `exactly once`.
- SQLite é adequado para validação local, mas a concorrência no PostgreSQL precisa ser executada no ambiente-alvo antes de operação sustentada.
- A retenção libera chaves antigas quando o histórico é purgado; redeliveries após esse prazo podem ser processadas novamente.
