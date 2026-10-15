# ADR-004 — OutputEvent e transporte realtime

- **Status:** Aceito
- **Fase:** 3 — Output e WebSocket

## Contexto

Experiences produzem envelopes `OutputEvent`, mas não devem administrar conexões nem depender de WebSocket. A Engine precisa entregar essas mensagens a clientes conectados sem transformar o runtime em código de transporte específico.

## Decisão

- Definir um `OutputPublisher` como porta injetada no `EngineRuntime`.
- Manter `dispatch()` e `publish()` separados. O pipeline futuro decidirá publicar somente depois de concluir as etapas de processamento/persistência exigidas.
- Implementar `RealtimeManager` como broadcast em memória por WebSocket, serializando chamadas de broadcast e enviando para clientes em paralelo com timeout individual.
- Enviar `SYSTEM_READY` ao conectar e expor `WS /ws/events` como canal server-to-client.
- Recusar mensagens de aplicação enviadas pelo cliente e exigir same-origin quando o cabeçalho `Origin` estiver presente.
- Disponibilizar um harness de desenvolvimento fora de `production`.

## Alternativas consideradas

- **Experience publica socket diretamente:** rejeitado porque mistura gameplay e transporte.
- **Uma tarefa de envio sequencial para todos os sockets:** rejeitada porque cliente lento atrasaria os demais.
- **Fila/outbox durável agora:** adiada; a fase atual valida broadcast local e não exige replay nem persistência.

## Consequências

- O Runtime depende de uma porta, não da implementação WebSocket.
- Uma falha individual remove somente a conexão afetada.
- `publish()` mede envios aceitos pelo transporte, não processamento confirmado no cliente.
- Desconexões e reinícios podem perder outputs; entrega durável e ACK são problemas futuros documentados.
- O servidor deve permanecer em loopback durante o MVP; exposição remota exigirá autenticação e uma política de origem/segurança apropriada.
