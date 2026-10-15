# ADR-001 — Engine independente de gameplay

- **Status:** Aceito
- **Data:** 2026-10-15

## Contexto

O repositório `live-tiktok` contém um jogo funcional (WORLD001) e responsabilidades de infraestrutura que cresceram junto do gameplay. Transformar esse repositório diretamente em Engine aumentaria o risco de regressão e manteria acoplamentos históricos.

## Decisão

Criar `interactive-live-engine` como repositório e aplicação independentes. O projeto antigo permanece preservado e serve apenas como referência comportamental. Não são permitidos imports de runtime, merge de histórico ou cópia indiscriminada de módulos do jogo antigo.

## Consequências

- A arquitetura e os contratos começam explícitos e testáveis.
- O bootstrap não depende de conta TikTok, LIVE real ou banco externo.
- Alguns comportamentos terão de ser reimplementados e comprovados por testes.
- Qualquer portabilidade futura deve justificar generalidade, origem/licença e teste de comportamento.
