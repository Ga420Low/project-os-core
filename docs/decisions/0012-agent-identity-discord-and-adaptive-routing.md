# 0012 - Agent Identity, Discord, And Adaptive Routing

## Statut

DECISION CONFIRMED

## Decision

`Project OS` doit fonctionner comme un seul agent systeme a travers:

- `Claude API`
- gros runs `GPT API`
- `Discord`
- futures surfaces

Le systeme retient:

1. une identite canonique unique
2. un overlay par canal, sans changement de personnalite
3. une memoire partagee et selective
4. un routage adaptatif des modeles selon banal / standard / critique / exceptionnel

## Routing retenu

- banal Discord -> `Claude API` pour discussion/traduction si LLM necessaire
- operateur standard -> `gpt-5.4 high`
- critique / ambigu -> `gpt-5.4 xhigh`
- exceptionnel -> `gpt-5.4-pro` seulement sur approval explicite

## Pourquoi

- garder un meme agent reconnaissable
- limiter la facture sur les banalites
- garder la force maximale pour les points durs
- rendre le workflow Discord viable a long terme

## Consequences

- il faut des docs d'identite et de handoff claires
- `Discord` ne devient pas une memoire parallele
- les promotions memoire doivent etre selectives
- le `Mission Router` devra a terme appliquer cette policy automatiquement

## References

- `PROJECT_OS_MASTER_MACHINE.md`
- `docs/architecture/AGENT_IDENTITY_AND_CHANNEL_MODEL.md`
- `docs/architecture/HANDOFF_MEMORY_POLICY.md`
- `docs/integrations/DISCORD_OPERATING_MODEL.md`
