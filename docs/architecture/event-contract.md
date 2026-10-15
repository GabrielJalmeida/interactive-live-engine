# Contratos de evento — v1

Este documento descreve os contratos implementados em `backend/app/domain/events.py`.

## Fronteira do domínio

`EventType`, `EventProvider`, `Viewer`, `LiveEvent` e `OutputEvent` são contratos internos. Eles não importam FastAPI, SQLAlchemy ou TikTokLive. A biblioteca externa será conhecida somente pelo adapter correspondente, que normalizará seus objetos para `LiveEvent`.

## LiveEvent

- `event_id`: UUID interno gerado por padrão pela Engine. Uma nova construção gera um novo ID.
- `type`: um dos tipos internos `COMMENT`, `GIFT`, `LIKE`, `FOLLOW`, `SHARE`, `JOIN`, `CONNECT` ou `DISCONNECT`.
- `provider`: enumeração controlada neste slice: `tiktok` ou `simulator`.
- `provider_event_id`: opcional; só será preenchido quando a origem fornecer um identificador utilizável. Não é fabricado para prometer deduplicação.
- `session_id`: opcional, quando a sessão de LIVE for conhecida.
- `occurred_at`: obrigatório e timezone-aware; é normalizado para UTC. Se o provider não fornecer horário do evento, o adapter deverá usar um horário UTC observado na recepção e documentar essa limitação.
- `received_at`: horário timezone-aware gerado por padrão no momento da construção do contrato e normalizado para UTC.
- `viewer`: opcional; se informado, precisa conter pelo menos uma informação de identidade/apresentação. O ID estável do provider é preferível a nome de usuário ou nome de exibição.
- `payload`: objeto JSON, genérico e sem regras de gameplay.

Os modelos rejeitam campos não declarados. `payload` deve serializar como JSON, ter no máximo 16 KiB em UTF-8 e profundidade máxima de oito níveis. Esses limites são defaults iniciais do contrato e devem ser revistos com evidência, antes de aumentá-los. A validação do HTTP também deverá limitar o corpo da requisição na camada de entrega; validar o modelo não substitui limites de transporte.

## Viewer

Todos os campos são opcionais individualmente, mas um `Viewer` não pode estar totalmente vazio. `avatar_url`, quando presente, precisa ser HTTP ou HTTPS. Informações pessoais devem ser minimizadas na persistência e nos logs.

## OutputEvent

Envelope server-to-client versionado com `protocol_version`, `message_id`, `type`, `experience`, `occurred_at` e `data`. A versão implementada é `1`. `type` usa um identificador de protocolo maiúsculo (por exemplo, `GAME_EVENT`); `experience` usa slug minúsculo com hífens. `data` é transportado sem interpretação de gameplay, serializável como JSON, limitado a 16 KiB e oito níveis de profundidade.

## Semântica

- Rose é um `GIFT` normal. Seu significado pertence à Experience.
- `CONNECT` e `DISCONNECT` descrevem eventos normalizados; a aplicação ainda precisará distinguir lifecycle do provider das entradas que encaminha à Experience.
- Timestamps sem timezone são rejeitados; não se assume silenciosamente que representam UTC.
- Campos desconhecidos são rejeitados para evitar que erros de integração sejam ignorados.
- O contrato não afirma que todo tipo de evento tem ID externo estável nem oferece garantia `exactly once`.
