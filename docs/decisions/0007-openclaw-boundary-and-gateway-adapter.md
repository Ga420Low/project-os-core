# ADR 0007 - OpenClaw Boundary And Gateway Adapter

## Decision

`OpenClaw` est retenu comme facade operateur riche.
Il porte les canaux, l'inbox, le pairing, `WebChat` et `Control UI`.

`Project OS` garde la verite machine, la memoire canonique, le `Mission Router`, les workers, les profiles et les preuves.

Le branchement se fait via un adaptateur `OpenClaw -> GatewayService`, jamais via des appels directs du shell operateur vers les workers ou la memoire.

## Why

- eviter une seconde source de verite
- eviter que la facade operateur decide la politique d'execution
- garder un point d'entree unique pour `Discord`, `WebChat` et plus tard la voix

## Consequences

- `OpenClaw` n'ecrit jamais dans la memoire canonique seul
- `OpenClaw` ne contourne jamais le `Mission Router`
- le coeur Python expose d'abord des contrats stables (`ChannelEvent`, `GatewayDispatchResult`, `OperatorReply`) avant le branchement live
