# ADR-003 — Runtime genérico e Experience registrada explicitamente

- **Status:** Aceito
- **Fase:** 2 — Runtime e Experience de teste

## Contexto

A Engine precisa gerenciar lifecycle e encaminhar eventos sem conhecer classes de jogos específicos. Imports dinâmicos ou singletons de gameplay tornariam o Core dependente da implementação do jogo.

## Decisão

Definir `InteractiveExperience` como contrato assíncrono; fornecer um `ExperienceContext` por ativação; registrar factories explicitamente no `ExperienceLoader`; controlar uma única instância ativa pelo `ExperienceManager`; delegar encaminhamento ao `EventRouter`; e expor uma fachada `EngineRuntime`. A aplicação padrão não inclui nem registra gameplay.

## Consequências

- O lifecycle é testável sem provider, rede, banco ou jogo real.
- Slugs e metadados são validados e factories precisam retornar instâncias compatíveis.
- Outputs são validados e devem identificar a Experience ativa.
- O contrato do contexto é fornecido de forma consistente em start, stop, dispatch, state e health.
- Inicialização integrada e configuração obrigatória de `ACTIVE_EXPERIENCE` serão conectadas quando o pipeline/lifecycle da aplicação for implementado, sem adicionar uma Experience concreta ao Core.
