# Legeres Sur Les Tomates

## Statut

- `completed`
- genere le 2026-03-15T23:19:03.763178+00:00
- type: `audit`

## Question de recherche

- recherche appronfondie legeres sur les tomates

## Synthese

- Le sujet « tomates » est très faiblement couplé au cœur actuel de Project OS. La meilleure sortie cohérente avec le snapshot repo est donc un audit documentaire court, appuyé sur des sources officielles USDA, APHIS, EPPO et UC Davis, et non une intégration produit. Les signaux frais réellement utiles sont bien documentés en 2026 : FoodData Central continue d’être mis à jour jusqu’au 2026-03-12, le rapport NASS Californie a été publié le 2026-01-23, les règles APHIS sur le matériel de multiplication restent en vigueur, et la page TGRC de UC Davis a été mise à jour le 2026-03-11. Côté GitHub, aucun repo tomate de niche ne justifie une entrée dans les packages cœur ; le seul satellite logiciel nettement plus sérieux que ces petits repos est PlantCV, mais il reste hors périmètre Project OS aujourd’hui. ([fdc.nal.usda.gov](https://fdc.nal.usda.gov/log/))

## Pourquoi on fait ca

- Le sujet est un bon test de discipline repo-first : montrer que Project OS sait produire une recherche propre sur un domaine hors mission sans sur-intégrer du code. Les points de fraîcheur utiles existent bien au 2026-01-23, 2026-03-11 et 2026-03-12. ([nass.usda.gov](https://www.nass.usda.gov/Statistics_by_State/California/Publications/Specialty_and_Other_Releases/Tomatoes/2026/PTOMInt_0126.pdf))
- Si l’audit doit parler d’état actuel sur la tomate, il faut tenir compte des règles APHIS toujours actives sur semences et transplants, ainsi que des signalements phytosanitaires EPPO 2026 ; sinon la note devient vite trompeuse. ([aphis.usda.gov](https://www.aphis.usda.gov/plant-imports/how-to-import/import-federal-orders/tomato-brown-rugose-fruit-virus-federal-import))
- Le paysage GitHub est bruyant : beaucoup de démos tomato/PlantVillage existent, mais les objets réellement solides sont surtout des datasets de benchmark ou un toolkit générique comme PlantCV. Cela justifie un tri dur entre ADAPT, DEFER et REJECT. ([github.com](https://github.com/spMohanty/PlantVillage-Dataset))

## Coherence Project OS

- Le snapshot repo montre un cœur orienté copilote PC local-first, avec des packages comme api_runs, gateway, learning, memory, runtime, scheduler et session, plus un brouillon déjà ouvert dans docs/audits/LEGERES_SUR_LES_TOMATES_AUDIT_2026-03-15.md.
- Aucun package cœur ne suggère aujourd’hui une verticale agronomie ou food/ag. La bonne intégration est donc documentaire, avec éventuellement mémorisation légère des sources, pas une nouvelle capacité produit.
- Les docs locales DEEP_RESEARCH_PROTOCOL.md, SYSTEM_DOSSIER_AUTHORING_STANDARD.md et docs/systems/README.md cadrent déjà le bon mode de sortie : repo-first, sources primaires, classement KEEP/ADAPT/DEFER/REJECT et preuves de revue.

## Point de depart repo

- branche active: `project-os/roadmap-freeze-lot4`
- packages coeur detectes:
  - `api_runs`
  - `gateway`
  - `github`
  - `learning`
  - `memory`
  - `mission`
  - `orchestration`
  - `router`
  - `runtime`
  - `scheduler`
  - `session`
- fichiers modifies observes:
  - `?? docs/audits/LEGERES_SUR_LES_TOMATES_AUDIT_2026-03-15.md`

## A faire

### Pack officiel USDA nutrition + marché tomate

Etat:

- `ADAPT`

Pourquoi il compte:

- Le rapport NASS du 2026-01-23 donne le signal marché le plus concret et le plus frais pour une note légère : les transformateurs californiens anticipent 9.8 millions de tonnes contractées en 2026, soit 11 % de moins que l’estimation d’août 2025. ([nass.usda.gov](https://www.nass.usda.gov/Statistics_by_State/California/Publications/Specialty_and_Other_Releases/Tomatoes/2026/PTOMInt_0126.pdf))
- FoodData Central continue d’être mis à jour en 2026-03, ce qui en fait une base nutritionnelle plus crédible qu’un blog ou un article secondaire figé. ([fdc.nal.usda.gov](https://fdc.nal.usda.gov/log/))
- La fiche USDA SNAP-Ed fournit une granularité suffisante pour un audit léger : 1 tomate moyenne = 123 g, 22 kcal, 19 mg de vitamine C. ([snaped.fns.usda.gov](https://snaped.fns.usda.gov/seasonal-produce-guide/tomatoes))

Ce qu'on recupere:

- Hiérarchie de sources très simple : NASS pour production/marché, FoodData Central et SNAP-Ed pour nutrition. ([nass.usda.gov](https://www.nass.usda.gov/Statistics_by_State/California/Publications/Specialty_and_Other_Releases/Tomatoes/2026/PTOMInt_0126.pdf))
- Un tableau claim -> source_url -> date_source -> lane dans le dossier d’audit.
- Une écriture courte et datée, sans dériver vers conseils culturaux ou santé non demandés.

Ce qu'on n'importe pas:

- Ne pas transformer ces données en fonctionnalité métier dans runtime, router ou gateway.
- Ne pas mélanger chiffres marché, nutrition et conseils agronomiques dans une seule section non typée.

Signal forks / satellites:

- Aucun fork ou satellite n’est plus fort que l’upstream ici : la vérité utile vient directement des pages USDA officielles, pas de wrappers ou mirrors. ([nass.usda.gov](https://www.nass.usda.gov/Statistics_by_State/California/Publications/Specialty_and_Other_Releases/Tomatoes/2026/PTOMInt_0126.pdf))

Ou ca entre dans Project OS:

- docs/audits/LEGERES_SUR_LES_TOMATES_AUDIT_2026-03-15.md
- docs/workflow/DEEP_RESEARCH_PROTOCOL.md
- learning
- memory

Preuves a obtenir:

- GET les trois URLs sources et vérifier un code HTTP 200 ; consigner published_at ou last updated exact dans le dossier.
- Ajouter un tableau de claims où chaque ligne contient claim, source_url, date_source et lane ; refuser la review si une ligne n’a ni date explicite ni mention accessed 2026-03-15.
- Rejouer un refresh à J+7 ; si le titre, la date ou le chiffre NASS/FoodData change, ouvrir une note de delta au lieu d’écraser silencieusement.

Sources primaires:

- [2026 California Processing Tomato Report](https://www.nass.usda.gov/Statistics_by_State/California/Publications/Specialty_and_Other_Releases/Tomatoes/2026/PTOMInt_0126.pdf) - USDA National Agricultural Statistics Service | 2026-01-23 - Baseline marché/production la plus fraîche et la plus concrète pour 2026.
- [FoodData Central Inventory and Update Log](https://fdc.nal.usda.gov/log/) - USDA National Agricultural Library / Agricultural Research Service | 2026-03-12 (latest entry on page) - Prouve que l’infrastructure nutrition USDA reste activement maintenue en 2026.
- [Tomatoes | SNAP-Ed Connection](https://snaped.fns.usda.gov/resources/nutrition-education-materials/seasonal-produce-guide/tomatoes) - USDA Food and Nutrition Service | accessed 2026-03-15; page undated - Fiche nutritionnelle et portions simples, suffisantes pour un audit léger.

### Veille phytosanitaire APHIS + EPPO pour la tomate

Etat:

- `ADAPT`

Pourquoi il compte:

- L’APHIS précise que l’ordre d’import ToBRFV s’applique toujours aux lots de semences et transplants de tomate et de piment, avec certificat phytosanitaire et preuve d’absence du virus. ([aphis.usda.gov](https://www.aphis.usda.gov/plant-imports/how-to-import/import-federal-orders/tomato-brown-rugose-fruit-virus-federal-import))
- L’APHIS a bien desserré les exigences sur les fruits destinés à la consommation à partir du 2024-06-17, mais a maintenu les garde-fous sur le matériel de multiplication, car le risque passe surtout par cette voie. ([direct.aphis.usda.gov](https://direct.aphis.usda.gov/news/agency-announcements/aphis-protects-domestic-fruit-production-deregulates-tomato-brown-rugose))
- La page APHIS Ralstonia modifiée le 2026-01-13 rappelle qu’il s’agit d’un risque sérieux pour la tomate via le flétrissement bactérien, et l’EPPO Reporting Service 2026 no. 2 documente encore des signaux ToBRFV/ToCV récents. ([direct.aphis.usda.gov](https://direct.aphis.usda.gov/plant-pests-diseases/ralstonia))

Ce qu'on recupere:

- Une lane réglementaire/sanitaire séparée du reste, avec champs rule, pathway, jurisdiction et effective_date.
- Des dates absolues et des juridictions explicites dans le dossier, pour éviter les phrases floues du type « récemment » ou « actuellement ». ([aphis.usda.gov](https://www.aphis.usda.gov/plant-imports/how-to-import/import-federal-orders/tomato-brown-rugose-fruit-virus-federal-import))
- Une mémorisation légère des règles et alertes dans memory si une révision périodique est demandée.

Ce qu'on n'importe pas:

- Ne pas produire de conseil de traitement, de conformité opérationnelle ou d’automatisation terrain sans humain expert.
- Ne pas brancher de logique d’import/compliance dans gateway pour ce sujet documentaire.

Signal forks / satellites:

- Aucun fork ou satellite pertinent n’est plus fort que les upstreams APHIS et EPPO ; ce sont les sources de vérité à citer telles quelles. ([aphis.usda.gov](https://www.aphis.usda.gov/plant-imports/how-to-import/import-federal-orders/tomato-brown-rugose-fruit-virus-federal-import))

Ou ca entre dans Project OS:

- docs/audits/LEGERES_SUR_LES_TOMATES_AUDIT_2026-03-15.md
- memory
- scheduler
- learning

Preuves a obtenir:

- HEAD ou GET sur les URLs APHIS FAQ, APHIS Ralstonia et EPPO PDF = 200.
- Créer dans memory trois enregistrements canonisés avec jurisdiction, effective_date, pathway et source_url.
- Si scheduler est utilisé, un dry-run doit produire la prochaine vérification à J+14 et ne rien écrire hors du dossier sans validation humaine.

Sources primaires:

- [Tomato Brown Rugose Fruit Virus Federal Import Order FAQs](https://www.aphis.usda.gov/plant-imports/how-to-import/import-federal-orders/tomato-brown-rugose-fruit-virus-federal-import) - USDA APHIS | 2025-09-16 - Source réglementaire de vérité sur semences, transplants et exigences documentaires.
- [APHIS Protects Domestic Fruit Production and Deregulates Tomato Brown Rugose Fruit Virus in Fruit for Consumption](https://direct.aphis.usda.gov/news/agency-announcements/aphis-protects-domestic-fruit-production-deregulates-tomato-brown-rugose) - USDA APHIS | 2024-06-17 - Explique le changement de politique sur le fruit destiné à la consommation.
- [Ralstonia Solanacearum Race 3 Biovar 2](https://direct.aphis.usda.gov/plant-pests-diseases/ralstonia) - USDA APHIS | 2026-01-13 - Risque sanitaire actuel, toujours pertinent pour la tomate.
- [EPPO Reporting Service 2026 no. 2](https://gd.eppo.int/media/data/reporting/rs-2026-02-en.pdf) - European and Mediterranean Plant Protection Organization | 2026-02 - Fournit des signaux 2026 sur ToBRFV, ToCV et autres agents liés à la tomate.

## A etudier

### Pack UC Davis + UC ANR pour approfondissement agronomie

Etat:

- `DEFER`

Pourquoi il compte:

- Le TGRC de UC Davis, mis à jour le 2026-03-11, est une source primaire forte pour la génétique, le germplasm et les stocks tomate ; il documente espèces sauvages, mutants monogéniques et stocks téléchargeables. ([tgrc.ucdavis.edu](https://tgrc.ucdavis.edu/about-us))
- Le California Processing Tomato Industry Pilot Plant de UC Davis fournit une base crédible si l’on veut approfondir le versant transformation/industrie, avec 8000 sq ft de recherche et R&D. ([caes.ucdavis.edu](https://caes.ucdavis.edu/research/facilities/plant))
- UC ANR fournit une taxonomie claire des ravageurs, maladies et désordres environnementaux de la tomate, utile pour une annexe agronomique structurée. ([ipm.ucanr.edu](https://ipm.ucanr.edu/home-and-landscape/tomato/index.html))

Ce qu'on recupere:

- Une annexe approfondissement si le dossier doit couvrir cultivar, germplasm, transformation ou taxonomie des maladies.
- Le réflexe source primaire universitaire : TGRC pour génétique, pilot plant pour transformation, UC ANR pour taxonomie pratique. ([tgrc.ucdavis.edu](https://tgrc.ucdavis.edu/about-us))

Ce qu'on n'importe pas:

- Ne pas convertir ces ressources en base interne structurée tant qu’aucun besoin métier Project OS n’existe.
- Ne pas présenter des pages UC Davis ou UC ANR comme équivalents réglementaires APHIS/EPPO.

Signal forks / satellites:

- Pas de fork ou de satellite plus fort que les upstreams UC Davis et UC ANR sur ce créneau ; la valeur est déjà dans les institutions sources. ([tgrc.ucdavis.edu](https://tgrc.ucdavis.edu/about-us))

Ou ca entre dans Project OS:

- docs/audits/LEGERES_SUR_LES_TOMATES_AUDIT_2026-03-15.md
- docs/systems/README.md
- learning

Preuves a obtenir:

- Le dossier doit citer explicitement la date de mise à jour TGRC 2026-03-11 et la date du pilot plant 2024-08-02, pas écrire « récent » sans date.
- Review gate : si cette lane dépasse 30 % du volume d’un audit léger, la déplacer en annexe.
- Si un dossier système séparé est créé plus tard, il reste documentaire et ne touche aucun package cœur.

Sources primaires:

- [About the TGRC](https://tgrc.ucdavis.edu/about-us) - University of California, Davis | 2026-03-11 - Référence primaire sur ressources génétiques tomate et documentation associée.
- [California Processing Tomato Industry Pilot Plant](https://caes.ucdavis.edu/research/facilities/plant) - University of California, Davis | 2024-08-02 - Source institutionnelle sur la capacité R&D transformation tomate.
- [Managing Pests in Gardens: Vegetables: Tomato](https://ipm.ucanr.edu/home-and-landscape/tomato/index.html) - University of California Agriculture and Natural Resources | accessed 2026-03-15; page undated - Taxonomie claire des ravageurs, maladies et désordres de la tomate.

### PlantCV comme satellite logiciel sérieux, mais hors scope actuel

Etat:

- `DEFER`

Pourquoi il compte:

- PlantCV est nettement plus mature que les petits repos tomate : 9495 commits, licence MPL-2.0, 55 releases et dernière release v4.10.2 le 2026-01-28. ([github.com](https://github.com/danforthcenter/plantcv))
- La documentation officielle montre un toolkit image modulaire couvrant RGB, NIR, thermique, fluorescence, hyperspectral et workflows parallélisés, donc un vrai satellite de phénotypage, pas une simple démo. ([docs.plantcv.org](https://docs.plantcv.org/))
- Cela reste néanmoins hors mission immédiate de Project OS, qui n’a pas aujourd’hui de profil applicatif plant-science dans le snapshot repo. ([github.com](https://github.com/danforthcenter/plantcv))

Ce qu'on recupere:

- Le signal architectural : si un jour Project OS doit traiter des images de plantes, partir d’un toolkit générique et maintenu plutôt que d’une démo tomate isolée. ([github.com](https://github.com/danforthcenter/plantcv))
- Une note en annexe a_etudier comme satellite plus fort que les petits repos tomate. ([github.com](https://github.com/danforthcenter/plantcv))

Ce qu'on n'importe pas:

- Ne pas intégrer PlantCV dans runtime, gateway ou session tant qu’aucun profil applicatif plant-science n’existe.
- Ne pas importer sa pile de dépendances image dans le cœur pour ce dossier tomate.

Signal forks / satellites:

- Ici, il existe bien un satellite plus fort que les upstreams tomate de niche : PlantCV est plus maintenu et plus large que tomatOD ou les démos PlantVillage, mais cela reste un DEFER pour Project OS aujourd’hui. ([github.com](https://github.com/danforthcenter/plantcv))

Ou ca entre dans Project OS:

- docs/systems/README.md
- docs/audits/LEGERES_SUR_LES_TOMATES_AUDIT_2026-03-15.md
- learning

Preuves a obtenir:

- Vérifier que la note de dossier mentionne explicitement PlantCV v4.10.2 et la date 2026-01-28.
- Aucun pip install plantcv ni dépendance équivalente ne doit être ajouté au repo sans ADR ou profil applicatif dédié.
- Si un spike est ouvert plus tard, il doit vivre hors packages cœur et démontrer une entrée/sortie locale sur un mini jeu d’images d’essai.

Sources primaires:

- [danforthcenter/plantcv](https://github.com/danforthcenter/plantcv) - Donald Danforth Plant Science Center / GitHub | accessed 2026-03-15; repo page shows latest release 2026-01-28 - Signal principal de maturité, licence, activité et releases.
- [PlantCV Documentation](https://docs.plantcv.org/en/stable/) - Donald Danforth Plant Science Center | accessed 2026-03-15 - Montre la portée fonctionnelle réelle et la modularité du toolkit.

## A rejeter pour maintenant

### Repos GitHub tomate de niche (tomatOD, PlantVillage-derived demos, lightweight tomato leaf classifiers)

Etat:

- `REJECT`

Pourquoi il compte:

- tomatOD reste un petit dataset de benchmark : 277 images, 2418 fruits annotés, 11 forks et aucune release publiée. C’est utile pour publication ou benchmark, pas pour Project OS aujourd’hui. ([github.com](https://github.com/up2metric/tomatOD))
- Le repo PlantVillage est plus connu, mais il reste d’abord un dataset. Son README recommande désormais l’usage via Hugging Face, tandis que la base code mentionne encore un environnement Python 2.7 pour certains outils. ([github.com](https://github.com/spMohanty/PlantVillage-Dataset))
- TensorFlow Datasets précise en plus que la source originale n’est plus disponible depuis l’origine et que TFDS republie une variante non augmentée ; cela renforce l’idée qu’on parle ici de benchmark/diffusion de dataset, pas de brique Project OS. ([tensorflow.org](https://www.tensorflow.org/datasets/catalog/plant_village?utm_source=openai))
- Les papiers de lightweight tomato disease classification sont intéressants académiquement, mais restent orientés benchmark ML et non intégration système dans un copilote PC local-first. ([arxiv.org](https://arxiv.org/abs/2109.02394?utm_source=openai))

Ce qu'on recupere:

- Garder seulement deux signaux pour justifier le rejet : limites du dataset et maturité réelle du repo. ([github.com](https://github.com/up2metric/tomatOD))
- Utiliser ces repos comme contre-exemples dans l’audit : excitants en surface, faibles en fit Project OS.

Ce qu'on n'importe pas:

- Ne pas brancher de code Python 2.7, notebooks YOLO ou datasets benchmark dans runtime, learning, session ou gateway.
- Ne pas confondre performance sur PlantVillage ou greenhouse avec robustesse terrain et valeur produit.

Signal forks / satellites:

- Aucun fork n’apparaît plus fort que l’upstream sur tomatOD, et la vraie valeur autour de PlantVillage vient plutôt de distributions satellites comme TFDS ou Hugging Face, pas de forks code destinés à Project OS. ([github.com](https://github.com/up2metric/tomatOD))

Ou ca entre dans Project OS:

- docs/audits/LEGERES_SUR_LES_TOMATES_AUDIT_2026-03-15.md
- docs/systems/README.md
- learning

Preuves a obtenir:

- Noter noir sur blanc REJECT avec motif hors mission + maturité insuffisante dans le dossier.
- Review gate : aucune dépendance issue de ces repos ne peut entrer tant qu’un use case Project OS n’est pas nommé, testable et approuvé.
- Si un spike est quand même proposé, il doit prouver compatibilité Python 3 actuelle, licence claire et résultat sur données non-benchmark ; sinon rejet automatique.

Sources primaires:

- [up2metric/tomatOD](https://github.com/up2metric/tomatOD) - GitHub / up2metric | accessed 2026-03-15; repo page - Montre la petite taille du dataset, le faible signal de maintenance et l’absence de releases.
- [spMohanty/PlantVillage-Dataset](https://github.com/spMohanty/PlantVillage-Dataset) - GitHub / SP Mohanty | accessed 2026-03-15; repo page - Dataset amont le plus visible, mais toujours centré benchmark et avec outillage hérité.
- [plant_village | TensorFlow Datasets](https://www.tensorflow.org/datasets/catalog/plant_village) - Google TensorFlow Datasets | 2024-06-01 - Explique les conditions de republication et la non-disponibilité de la source originale.
- [Less is More: Lighter and Faster Deep Neural Architecture for Tomato Leaf Disease Classification](https://arxiv.org/abs/2109.02394) - arXiv | 2021-09-06 - Exemple clair d’intérêt académique réel, mais hors fit Project OS.

## Preuves transverses a obtenir

- Finaliser docs/audits/LEGERES_SUR_LES_TOMATES_AUDIT_2026-03-15.md en trois lanes : nutrition/marché, réglementaire/sanitaire, recherche/agronomie.
- Limiter toute action Project OS à des vérifications de sources, de fraîcheur et de traçabilité ; ne rien brancher dans runtime ou gateway pour un sujet tomate.
- Si une veille récurrente est souhaitée, la brancher comme refresh documentaire léger via scheduler + memory, pas comme nouvelle verticale métier.
- Conserver séparément les repos GitHub tomate, PlantVillage et PlantCV comme annexes évaluées avec une décision explicite DEFER ou REJECT.

## Risques et angles morts

- Risque principal : sur-intégrer un sujet hors mission et créer une seconde vérité métier dans le cœur Project OS alors que la matière utile tient surtout dans un dossier documentaire.
- Risque de dérive temporelle sur le sanitaire et le réglementaire : APHIS et EPPO évoluent ; une note sans dates absolues deviendra vite trompeuse. ([aphis.usda.gov](https://www.aphis.usda.gov/plant-imports/how-to-import/import-federal-orders/tomato-brown-rugose-fruit-virus-federal-import))
- Risque méthodologique : les repos tomato CV surestiment la transférabilité terrain ; tomatOD est petit, et TFDS rappelle que la source originale PlantVillage n’est plus directement disponible. ([github.com](https://github.com/up2metric/tomatOD))

## Questions ouvertes

- Le sujet « tomates » est-il un simple test du mode deep research, ou doit-il déboucher sur une veille récurrente ?
- Souhaitez-vous un audit strictement US-centric centré USDA/APHIS/UC, ou un dossier plus international avec FAO/EPPO en première classe ?
- Faut-il mémoriser ce dossier dans memory comme exemple canonique de recherche hors-domaine, ou le laisser uniquement dans docs/audits ?

## Sources globales

- [2026 California Processing Tomato Report](https://www.nass.usda.gov/Statistics_by_State/California/Publications/Specialty_and_Other_Releases/Tomatoes/2026/PTOMInt_0126.pdf) - USDA National Agricultural Statistics Service | 2026-01-23 - Source primaire la plus utile pour le signal marché/production 2026.
- [FoodData Central Inventory and Update Log](https://fdc.nal.usda.gov/log/) - USDA National Agricultural Library / Agricultural Research Service | 2026-03-12 (latest entry on page) - Prouve la fraîcheur de l’infrastructure nutritionnelle USDA.
- [Tomato Brown Rugose Fruit Virus Federal Import Order FAQs](https://www.aphis.usda.gov/plant-imports/how-to-import/import-federal-orders/tomato-brown-rugose-fruit-virus-federal-import) - USDA APHIS | 2025-09-16 - Source réglementaire de vérité sur semences et transplants.
- [Ralstonia Solanacearum Race 3 Biovar 2](https://direct.aphis.usda.gov/plant-pests-diseases/ralstonia) - USDA APHIS | 2026-01-13 - Rappel sanitaire actuel pertinent pour la tomate.
- [EPPO Reporting Service 2026 no. 2](https://gd.eppo.int/media/data/reporting/rs-2026-02-en.pdf) - European and Mediterranean Plant Protection Organization | 2026-02 - Donne les signaux récents internationaux sur ToBRFV, ToCV et autres agents.
- [About the TGRC](https://tgrc.ucdavis.edu/about-us) - University of California, Davis | 2026-03-11 - Référence primaire la plus solide côté génétique et ressources tomate.
- [danforthcenter/plantcv](https://github.com/danforthcenter/plantcv) - Donald Danforth Plant Science Center / GitHub | accessed 2026-03-15; repo page shows latest release 2026-01-28 - Montre quel satellite logiciel est réellement mature si un jour un besoin image végétale émerge.
