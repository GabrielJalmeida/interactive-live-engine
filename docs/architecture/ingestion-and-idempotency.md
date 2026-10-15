# Ingestão e idempotência — MVP

## Fluxo

```text
Dev Event API / provider adapter
        ↓
LiveEvent validado
        ↓
EventIngestionService
        ↓
reservar (provider, provider_event_id), se disponível
        ↓
EngineRuntime.dispatch(event)
        ↓
outputs validados pela Experience
        ↓
EngineRuntime.publish(outputs)
        ↓
EventIngestionResult
```

O provider adapter ainda será implementado em uma fase posterior. Nesta fase a Dev Event API exerce o papel de origem simulada do evento e encaminha ao mesmo serviço de ingestão.

## Request

`POST /api/v1/dev/events` aceita `type`, `provider_event_id` opcional, `session_id` opcional, `occurred_at` opcional, `viewer` opcional e `payload` JSON. `event_id`, `provider` e `received_at` são definidos no servidor. Campos extras são rejeitados.

O payload deve ser JSON serializável, ter até 16 KiB e profundidade máxima de oito níveis. Para campos comuns usados pelo simulador, texto COMMENT é obrigatório e limitado a 4.000 caracteres; se `quantity` estiver presente deve ser inteiro entre 1 e 10.000; para LIKE, `count`, quando presente, deve ser inteiro entre 1 e 1.000.000. Esses checks pertencem ao schema do simulador e não atribuem semântica de gameplay ao Core.

A rota existe apenas em `development` e `test`. Ela não aparece no OpenAPI nem na tabela de rotas em `production`. O app base não registra Experience concreta, portanto eventos em uma app sem Experience ativa retornam `409 NO_ACTIVE_EXPERIENCE`.

## Response

Sucesso ou duplicidade reconhecida retorna `200`:

```json
{
  "status": "processed",
  "event_id": "UUID-do-evento-de-entrada",
  "duplicate_of_event_id": null,
  "outputs": [],
  "delivered_clients": 0
}
```

Para uma duplicidade, `status` é `duplicate`, `outputs` é vazio e `duplicate_of_event_id` aponta para o primeiro ID interno registrado para aquela chave nesta execução.

Erros públicos seguem o envelope `{ "error": { "code": "...", "message": "..." } }`. Validação retorna `422 INVALID_REQUEST`; falta de Experience ativa retorna `409 NO_ACTIVE_EXPERIENCE`; erro de processamento retorna `500 EVENT_PROCESSING_FAILED`; erro do publisher retorna `500 OUTPUT_PUBLICATION_FAILED`. As respostas não incluem stack trace nem payload bruto.

## Deduplicação da Fase 4

`InMemoryEventDeduplicationStore` implementa o port usado pelo serviço e protege reservas concorrentes com lock assíncrono. Só é possível deduplicar quando o provider oferece `provider_event_id`. O identificador externo é combinado com o provider normalizado.

O estado é volátil e ilimitado dentro do processo atual; ele se perde no reinício. Essa implementação serve para demonstrar o fluxo e testar o contrato, não para operação sustentada. Na Fase 5, o port será implementado com repository, transação e constraint de unicidade no banco de dados. Não se promete exactly-once.

Se a Experience falhar durante o dispatch, o serviço libera sua reserva para permitir uma tentativa posterior. Depois que a Experience retorna outputs com sucesso, a reserva é mantida mesmo que o publisher gere uma falha: repetir o evento poderia reaplicar efeitos do jogo. Como não existe outbox nesta fase, uma falha de publicação pode exigir intervenção; a limitação é explícita e não deve ser confundida com entrega durável.
