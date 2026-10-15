# Persistência e retenção

## Componentes

- `backend/app/persistence/database.py`: normalização de URL, engine SQLite com foreign keys/busy timeout e fábrica de sessões.
- `backend/app/persistence/models.py`: `LiveEventRecord`, `EventDeduplicationKey` e tipos UTC.
- `backend/app/persistence/event_repository.py`: reserva atômica, atualização de status, consulta diagnóstica e purge por cutoff.
- `backend/alembic/`: migrations da estrutura do schema.

## Fluxo de evento

1. `reserve(event)` grava a tentativa como `RECEIVED` e cria a chave externa, quando existe.
2. A chave `(provider, provider_event_id)` é única no banco. Uma colisão consulta e devolve o `event_id` original para a resposta `duplicate`.
3. Se o dispatch da Experience falhar, a tentativa fica `FAILED` e somente a chave pertencente a essa tentativa é removida. Outra tentativa poderá adquirir a chave sem destruir o histórico da falha.
4. Se o dispatch tiver sucesso, o registro muda para `PROCESSED` antes de tentar publicar outputs.
5. Se a publicação falhar, o registro continua `PROCESSED` e a chave é mantida. O evento não volta a executar gameplay automaticamente.

## Retenção e privacidade

O valor inicial de `EVENT_RECORD_RETENTION_DAYS` é 7 dias, com intervalo configurável entre 1 e 365. O comando `python -m scripts.purge_expired_event_records` elimina os registros anteriores ao cutoff; a FK com `ON DELETE CASCADE` remove as chaves de deduplicação relacionadas. Agendamento automático ainda depende do ambiente operacional e não é ativado silenciosamente pelo processo web.

A persistência inclui payload normalizado e dados minimizados de viewer para diagnóstico. O operador deve avaliar quais campos a Experience/provider realmente precisa, proteger o arquivo/banco local e executar a política de retenção. Logs técnicos não devem copiar conteúdo de comentário nem payloads completos.

## Migrations

```bat
python -m alembic upgrade head
python -m alembic check
```

Migration inicial deve funcionar em banco vazio. `Base.metadata.create_all()` é usado somente em testes isolados; não substitui migration no ambiente da aplicação.

## Limites conhecidos

- SQLite testa o comportamento e a constraint local, mas não substitui um teste concorrente em PostgreSQL.
- Eventos sem ID externo utilizável não podem ser deduplicados entre redeliveries com novo `event_id`.
- O pipeline não dispõe de outbox transacional. `PROCESSED` significa que a Experience concluiu; não significa que cada cliente WebSocket recebeu o output.
