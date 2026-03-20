# OpenClaw UI Keep 1:1 And Extend Matrix

## Statut

ACTIVE

## But

Figer sans ambiguite:

- ce qu'on garde 1:1 dans l'UI `OpenClaw`
- ce qu'on etend tout de suite pour `Project OS`
- ce qu'on remet plus tard pour eviter un fork frontend sale trop tot

## Regle de lecture

- `KEEP 1:1` = on garde l'upstream tel quel comme surface operateur V1
- `EXTEND NOW` = on ajoute notre couche par-dessus sans casser l'upstream
- `EXTEND LATER` = utile, mais pas au prix d'un detour ou d'une fausse promesse V1

## Matrice

| Surface / capacite | Decision | Horizon | Pourquoi |
| --- | --- | --- | --- |
| shell global Control UI | `KEEP 1:1` | maintenant | deja solide, riche et exploitable |
| chat principal | `KEEP 1:1` | maintenant | suffisant pour operer la fondation |
| sessions / cron / skills / nodes / logs / config | `KEEP 1:1` | maintenant | gros gain gratuit, inutile de re-ecrire |
| navigation operateur de base | `KEEP 1:1` | maintenant | le cockpit upstream fait deja le travail |
| dictée vocale navigateur dans le chat | `KEEP 1:1` | maintenant | deja presente via le bouton micro et les APIs navigateur |
| bridge `OpenClaw -> Project OS -> Codex CLI` | `EXTEND NOW` | prochain lot | la vraie execution code/shell/patch doit sortir vers `Codex CLI` |
| taches / memoire / liens / decisions / approvals / evidence | `EXTEND NOW` | prochain lot | c'est la valeur proprietaire `Project OS` |
| panneaux metier `Project OS` dans la surface operateur | `EXTEND NOW` | prochain lot | meilleure voie que casser l'UI existante |
| vraie auth applicative unifiee `Project OS` | `EXTEND LATER` | apres fondation | la surface privee Tailscale suffit pour la V1 substrate |
| vrai call web/mobile full-duplex depuis le lien VPS | `EXTEND LATER` | apres bridge et memoire | ce n'est pas ce que l'upstream livre aujourd'hui sur cette lane |
| restyle / branding fort du frontend | `EXTEND LATER` | apres valeur metier | la logique metier prime sur la peinture |

## Voix via le lien VPS aujourd'hui

Ce qui existe vraiment maintenant:

- ouvrir `OpenClaw` sur l'URL Tailscale privee du VPS
- aller dans le chat
- utiliser le bouton micro `Voice input`

Ce que cela fait:

- dictée navigateur -> texte
- pas un vrai call voix temps reel
- pas un bus audio canonique `Project OS`

Dependances reelles:

- permission micro du navigateur
- support navigateur de `SpeechRecognition` / `webkitSpeechRecognition`
- surface privee Tailscale ouverte

Conclusion:

- pour "envoyer un vocal" au sens dicter un message operateur, oui
- pour "appeler directement" au sens conversation audio temps reel via le lien VPS, non pas encore

## Lien `Codex CLI` a poser

Le lien cible retenu est:

`OpenClaw UI -> OpenClaw runtime -> Project OS bridge -> Codex CLI runner`

Regles:

1. `OpenClaw` garde le cockpit
2. `Project OS` garde la verite metier
3. `Codex CLI` garde l'execution code/shell/patch
4. le bridge doit etre visible dans l'UI sans transformer `OpenClaw` en fork metier

## Ce qu'on ne fait pas

1. forker tout le frontend maintenant
2. re-ecrire le cockpit upstream
3. pretendre que le lien VPS current fournit deja un vrai call vocal web
4. injecter brutalement la logique `Project OS` dans le coeur UI upstream

## Resultat vise

La trajectoire retenue est:

1. garder l'excellent cockpit upstream
2. brancher nos capacites proprietaires la ou elles apportent vraiment de la valeur
3. retoucher le style plus tard, quand les objets metier sont vrais
