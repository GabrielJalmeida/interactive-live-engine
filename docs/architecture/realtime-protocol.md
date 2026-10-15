# Protocolo realtime — versão 1

## Endpoint e direção

- Endpoint: `WS /ws/events`.
- Transporte: JSON sobre WebSocket.
- Direção: server → client; o cliente não envia comandos de gameplay por este canal.
- Origem no browser: same-origin com o host/esquema da requisição. Clientes não-browser sem cabeçalho `Origin` são aceitos; a exposição da aplicação deve continuar em loopback durante o MVP.

## Mensagem inicial

Após aceitar a conexão, a Engine envia:

```json
{
  "protocol_version": 1,
  "type": "SYSTEM_READY",
  "occurred_at": "2026-10-15T20:00:00Z"
}
```

O timestamp é gerado pela Engine em UTC. Depois dessa mensagem, o servidor entrega envelopes `OutputEvent` sem reinterpretar o campo `data`.

## OutputEvent

O schema canônico está em `backend/app/domain/events.py`. Inclui `protocol_version`, `message_id`, `type`, `experience`, `occurred_at` e `data`. A versão atual é `1`; o payload é validado como JSON limitado antes da publicação.

Mensagens de tipo desconhecido no cliente devem ser ignoradas ou registradas de forma controlada, sem interromper a conexão. O cliente deve tratar reconexão e estado de conexão explicitamente.

## Broadcast e falhas

`RealtimeManager` envia para as conexões em paralelo, com timeout individual. Uma conexão que falha ou excede o timeout é removida; ela não impede que as demais recebam a mensagem. Chamadas de broadcast são serializadas para preservar a ordem das mensagens enviadas por chamadas concorrentes dentro do processo.

A contagem retornada por `publish()` é o número de envios bem-sucedidos, não confirmação de que a aplicação cliente processou a mensagem.

## Limites de garantia

A entrega é em memória e best-effort. Não há fila durável, replay, ACK de cliente, snapshot ou garantia de entrega em caso de desconexão/reinício. Outbox transacional e ressincronização ficam para fase futura, conforme a necessidade real.

## Harness

Em `development` e `test`, abrir `http://127.0.0.1:8000/dev/realtime-harness`. O harness usa apenas APIs DOM seguras (`textContent`), exibe no máximo as últimas 100 mensagens e não envia comandos para o servidor. A rota retorna 404 em `production`.
