# OpenClaw Substrate Readiness Checklist

## Statut

ACTIVE

## But

Verifier que la fondation `OpenClaw` sur le noeud OVH est suffisamment propre pour commencer ensuite:

- l'integration entreprise
- le bridge d'execution
- les lanes plus avancees

Sans confondre:

- un substrate pret
- et un produit complet

## Perimetre

Cette checklist s'applique a:

- `/srv/project-os/apps/openclaw-upstream`
- l'infra locale du noeud
- les surfaces admin privees
- la separation `upstream / canon`

## Checklist

### A. Noeud

- [x] VPS provisionne et accessible
- [x] SSH admin par cle operationnel
- [x] `ufw` actif
- [x] `fail2ban` actif
- [x] reboot post-upgrade realise
- [x] kernel charge a jour

### B. Base runtime serveur

- [x] Docker fonctionne
- [x] `postgres` tourne et est `healthy`
- [x] `redis` tourne et est `healthy`
- [x] `vm.overcommit_memory = 1` pose pour Redis

### C. Surfaces admin privees

- [x] `Tailscale` connecte au tailnet
- [x] `code-server` accessible via URL privee Tailscale
- [x] acces mobile 5G confirme

Note:

- le conteneur `code-server` peut apparaitre `unhealthy` si son healthcheck utilise `wget` absent de l'image
- dans ce cas, l'etat fonctionnel reel doit etre juge par:
  - l'URL privee effective
  - les logs
  - la reponse web
- ne pas conclure a une panne sans verifier ces 3 points
- sur notre noeud, ce healthcheck a ete corrige pour utiliser `curl` et le conteneur est maintenant `healthy`

### D. Separation des repos

- [x] `openclaw-upstream` clone a part
- [x] `project-os-core` garde son role canon docs / contrats / migration
- [x] aucun melange physique impose entre les deux

### E. Pin upstream

- [x] remote upstream officiel confirme
- [x] version stable retenue
- [x] commit exact documente
- [x] HEAD detache assume pour eviter le drift implicite

Valeurs retenues:

- repo: `openclaw/openclaw`
- tag: `v2026.3.13-1`
- commit: `61d171ab0b2fe4abc9afe89c518586274b4b76c2`

### F. Pre-readiness OpenClaw

A valider avant de dire "OpenClaw runtime pret":

- [x] racine d'etat `OpenClaw` dediee definie
- [x] fichier de config serveur `OpenClaw` defini
- [x] bind runtime docker + publication host privee retenus pour le gateway
- [x] auth gateway retenue explicitement
- [x] workspace `OpenClaw` retenu explicitement
- [x] politique d'exposition distante retenue (`Tailscale` host d'abord)

Etat reel maintenant:

- `/srv/project-os/config/env/openclaw/main.env` pose
- `/srv/project-os/data/openclaw/main/openclaw.json` pose
- `/srv/project-os/compose/openclaw/main/docker-compose.yml` pose
- `openclaw-main-gateway` demarre et passe `healthz` / `readyz`
- contrat UID runtime aligne avec le owner host (`1001:1001`) pour eviter les `EACCES` sur la lane data
- route Tailscale dediee du dashboard pas encore publiee sur le host

Reference:

- `docs/roadmap/OPENCLAW_MAIN_LANE_BOOTSTRAP_SPEC.md`
- `docs/roadmap/OPENCLAW_MAIN_LANE_CONFIG_SPEC.md`

### G. Interdits encore actifs

- [x] pas de couche entreprise injectee dans le coeur upstream
- [x] pas de memoire d'entreprise confondue avec la memoire runtime OpenClaw
- [x] pas de fork structurel premature
- [x] pas de surface publique admin ouverte juste pour accelerer

## Gate de passage vers la suite

On peut passer a la suite si:

1. la checklist `A -> E` reste vraie
2. les points `F` sont explicitement poses
3. les interdits `G` restent respectes

## Commandes de verification

```bash
# pin upstream
cd /srv/project-os/apps/openclaw-upstream
git remote get-url origin
git describe --tags --exact-match
git rev-parse HEAD

# infra
docker ps
docker compose -f /srv/project-os/compose/base/docker-compose.yml ps
sudo ufw status
sudo systemctl status fail2ban --no-pager

# tailscale
tailscale status
tailscale ip -4
```
