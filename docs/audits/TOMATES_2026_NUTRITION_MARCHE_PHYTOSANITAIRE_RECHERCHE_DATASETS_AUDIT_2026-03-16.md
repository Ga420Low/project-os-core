# Tomates 2026 - nutrition, marche, phytosanitaire, recherche et jeux de donnees de reference

## Statut

- `completed`
- genere le 2026-03-16T01:20:00+01:00
- type: `audit`
- seo_slug: `tomates-2026-nutrition-marche-phytosanitaire-recherche-et-jeux-de-donnees-de-reference`

## Question de recherche

- demande initiale: `recherche approfondie legeres sur les tomates`
- objectif recadre: produire un dossier humain-first, bien source, lisible sur mobile, puis garder une lecture `Project OS` en fin de document

## Synthese executive

- Pour une vue factuelle et a jour sur la tomate en 2026, les meilleures sources primaires sont `USDA SNAP-Ed` et `FoodData Central` pour la nutrition, `USDA NASS` pour le signal marche/industrie aux Etats-Unis, `APHIS` et `EPPO` pour le phytosanitaire, puis `UC Davis`, `UC ANR` et la litterature scientifique recente pour la genetique, la culture et la resilience climatique.
- La donnee marche la plus concrete et la plus fraiche cote US est le rapport `USDA NASS` du `2026-01-23`: la Californie anticipe `9.8 millions de tonnes` de tomates de transformation sous contrat en 2026, soit `11 %` de moins que l'estimation d'aout 2025.
- La donnee nutrition la plus simple a retenir pour un lecteur humain est celle de `USDA SNAP-Ed`: `1 tomate moyenne = 123 g = 22 kcal = 19 mg de vitamine C`.
- Le point reglementaire critique a ne pas rater en 2026: `APHIS` a leve au `2024-06-17` les contraintes sur le fruit destine a la consommation, mais a maintenu les exigences sur `semences`, `transplants` et plus largement le materiel de multiplication pour `ToBRFV`.
- Le point recherche le plus clair en 2025-2026: la tomate reste un terrain tres actif sur `tolerance a la chaleur`, `qualite post-recolte`, `genetique` et `gestion des maladies`, avec une valeur pratique immediate pour la selection varietale et l'agronomie.
- Pour `Project OS`, ce sujet doit rester un `dossier documentaire + veille legere`. La bonne extension logicielle, si un jour elle devient utile, n'est pas un nouveau produit tomate, mais une couche de `refresh documentaire`, plus un satellite image/data type `PlantCV`.

## Tableau rapide

| Lane | Ce qu'il faut retenir | Pourquoi c'est utile | Sources de base |
| --- | --- | --- | --- |
| Nutrition | `1 tomate moyenne = 123 g = 22 kcal = 19 mg vitamine C` | Base simple, stable et humainement lisible | USDA SNAP-Ed, FoodData Central |
| Marche | `9.8 millions de tonnes` de tomates de transformation sous contrat en Californie pour 2026 | Meilleur signal court terme pour l'industrie tomate US | USDA NASS |
| Global | Le pipeline `FAO -> OWID` reste le meilleur point d'entree public pour les series longues; la page tomate OWID etait `last updated 2025-03-17`, `1961-2023`, et FAO a diffuse une release `2010-2024` fin 2025 | Permet de distinguer signal instantane US et historique mondial | FAO, Our World in Data |
| Phytosanitaire | `ToBRFV` reste critique sur les semences et transplants; `Ralstonia` reste une menace severe | Evite de raconter des choses obsoletes sur l'import ou les risques | APHIS, EPPO |
| Recherche | La vraie frontiere 2025-2026 est `heat stress`, `genetique`, `postharvest`, `resistance` | Oriente la veille agronomie et la lecture des papiers | UC Davis, UC ANR, PubMed |
| Data / software | `PlantCV` est le seul satellite logiciel vraiment mature; `PlantVillage` et `tomatOD` sont surtout des datasets | Bon tri entre toolkit reutilisable et repo demo | PlantCV docs, GitHub |

## Pourquoi ce dossier merite un vrai audit

- Le sujet a l'air simple, mais il bascule vite dans le flou si on melange `nutrition`, `marche`, `culture`, `sanitaire` et `benchmarks ML`.
- Plusieurs affirmations courantes sur la tomate deviennent trompeuses sans dates absolues. Exemple: apres le `2024-06-17`, les regles APHIS ne sont plus les memes pour `fruit pour consommation` et pour `materiel de propagation`.
- Pour un lecteur humain, un bon dossier tomate doit distinguer `ce qui est stable`, `ce qui change vite` et `ce qui n'est qu'un signal de recherche`.
- Pour `Project OS`, c'est aussi un bon test de discipline: produire un excellent rapport hors coeur produit sans sur-integrer de code inutile.

## Lane 1 - Nutrition et valeur alimentaire

### Ce qui est solide

- `USDA SNAP-Ed` donne une base claire et utilisable sans surpromesse: `1 medium tomato (123 g)`, `22 calories`, `19 mg` de vitamine C.
- `FoodData Central` reste le backend de reference pour l'infrastructure nutritionnelle USDA. La page de telechargement affiche un `full download` date `12/2025`, ce qui montre que la base de donnees continue d'etre maintenue et redistribuee a grande echelle.
- La tomate est surtout un aliment `faible en calories`, `riche en eau`, utile pour l'apport en vitamine C et interessant pour sa teneur en carotenoides, notamment le `lycopene`.

### Ce qu'il faut dire avec prudence

- La litterature 2024-2025 sur `tomate`, `lycopene` et sante reste active, mais il faut separer `association statistique`, `essais d'intervention`, et `conseil medical`.
- Une meta-analyse prospective indexee PubMed en 2025 rapporte une association modeste entre apports eleves en `tomate/lycopene` et risque global de cancer legerement plus bas, mais ce n'est pas une preuve de causalite suffisante pour transformer la tomate en promesse therapeutique.
- Une meta-analyse d'essais d'intervention sur `tomate/lycopene` et deterioration cutanee UV existe aussi, mais la bonne lecture reste: `la recherche est active`, pas `la tomate soigne`.

### Lecture pratique

| Point | Donnee utile | Lecture raisonnable |
| --- | --- | --- |
| Portion | `1 medium tomato = 123 g` | Un repere simple pour lecture mobile |
| Energie | `22 kcal` | Aliment leger, densite energetique basse |
| Vitamine C | `19 mg` | Contribution utile, sans surjouer l'effet sante |
| Lycopene | sujet de recherche actif | A presenter comme axe de recherche, pas comme claim marketing brut |

## Lane 2 - Marche, industrie et donnees de production

### Signal court terme le plus fort

- Le rapport `USDA NASS California Processing Tomato Report`, publie le `2026-01-23`, annonce `9.8 million tons` sous contrat en 2026 en Californie.
- Le meme rapport precise que cela represente `11 %` de moins que l'estimation d'aout 2025.
- Pour une lecture industrie, ce chiffre est plus utile qu'une moyenne mondiale abstraite: il donne un vrai signal sur la tomate de transformation.

### Signal serie longue / monde

- `Our World in Data` expose une page dediee `Tomato production - UN FAO`, `last updated March 17, 2025`, avec une plage `1961-2023`.
- Cette page cite comme source d'origine `Food and Agriculture Organization of the United Nations - Production: Crops and livestock products (2025)`.
- En parallele, `FAO Statistics` a publie fin 2025 une release `Agricultural production statistics 2010-2024`, indiquant que le domaine production couvre les commodites agricoles `up to 2024`.

### Lecture pratique

- Si tu veux un `etat du marche tres actuel`, commence par `USDA NASS`.
- Si tu veux un `historique long, global et comparable`, passe par `FAO / OWID`.
- Si tu veux parler du monde sans inventer des chiffres fragiles, mieux vaut dire explicitement `serie FAO jusqu'a 2024; page OWID tomate 1961-2023, maj 2025-03-17`.

## Lane 3 - Reglementaire et phytosanitaire

### Ce qui a change et ce qui n'a pas change

- La page FAQ `APHIS Tomato Brown Rugose Fruit Virus Federal Import Order FAQs` est `Last Modified: September 16, 2025`.
- Elle rappelle que le `Federal Order` continue de s'appliquer aux `seed lots` et `transplants` de tomate et de piment provenant de tous pays.
- Elle rappelle aussi qu'`APHIS revised the Federal Order June 17, 2024 to remove import requirements for tomato and/or pepper fruit while continuing import requirements unchanged for propagative material`.

### Autres risques sanitaires a ne pas oublier

- La page `APHIS Ralstonia Solanacearum Race 3 Biovar 2` est `Last Modified: January 13, 2026`.
- `APHIS` y rappelle que `R. solanacearum` est un pathogene du sol qui menace plus de `200` especes, dont `tomatoes`, `potatoes` et `eggplant`.
- Cette page souligne aussi que la race `3 biovar 2` est consideree comme `select agent` en raison de sa severite potentielle pour la sante vegetale.

### Signal international EPPO

- La page `EPPO Global Database` pour `ToBRFV` montre encore des articles de reporting en `2025` et `2026`, notamment `2026/025` et `2026/018`.
- Le PDF `EPPO Reporting Service 2026 no. 2` mentionne encore des signaux sur `ToBRFV` et `ToCV`.
- La datasheet `ToCV` EPPO rappelle que le virus peut causer des dommages considerables en culture de tomate sous serre dans la region EPPO.

### Lecture pratique

| Question | Reponse courte 2026 |
| --- | --- |
| Le fruit tomate pour consommation est-il toujours bloque comme avant ? | `Non`. La revision `2024-06-17` a leve ces contraintes specifiques |
| Les semences et transplants restent-ils sous exigences ? | `Oui` |
| Le risque sanitaire tomate est-il fini ? | `Non`. `ToBRFV`, `ToCV` et `Ralstonia` restent des sujets vivants |

## Lane 4 - Genetique, agronomie et recherche

### Sources institutionnelles les plus solides

- Le `Tomato Genetics Resource Center` (`UC Davis`) a une page `About the TGRC` mise a jour le `2026-03-11`.
- Cette ressource reste la reference la plus simple pour `germplasm`, `wild species`, `mutants`, `seed stocks` et documentation genetique tomate.
- Le `California Processing Tomato Industry Pilot Plant` (`UC Davis`) a une page mise a jour le `2024-08-02` qui indique `8000 square feet of research space` pour education, recherche academique et R&D industrielle.
- Le portail `UC ANR IPM` sur la tomate reste une tres bonne entree pratique pour la taxonomie `pests / diseases / disorders`.

### Ce que montre la recherche recente

- La tomate reste un cas d'ecole pour la `tolerance a la chaleur`. Une review 2025 et des travaux 2025 sur traits racinaires, physiologie, pollen, photosynthese et rendement convergent tous vers la meme idee: il faut selectionner des cultivars plus resilients aux stress thermiques.
- La recherche `postharvest` reste active en 2026, avec un accent sur la fraicheur, les champignons d'alteration, le conditionnement et la duree de vie commerciale.
- La resistance aux ravageurs et maladies reste un front classique mais non clos: les reviews 2024 rappellent que la qualite de la selection genetique reste un des vrais leviers a long terme.

### Lecture pratique

- Pour un lecteur `agronomie / breeding`, commence par `TGRC`, `UC ANR`, puis la litterature 2025 sur `heat stress`.
- Pour un lecteur `industrie`, ajoute le `pilot plant UC Davis`.
- Pour un lecteur `veille generaliste`, il suffit de retenir que `climat`, `genetique`, `maladies` et `postharvest` sont les quatre axes qui bougent vraiment.

## Lane 5 - Data, logiciels et GitHub

### Le seul satellite logiciel vraiment serieux

- `PlantCV` est le seul objet logiciel qui sorte clairement du bruit pour un usage plante generaliste.
- La doc `stable` explique qu'il supporte les images `RGB`, `NIR`, `thermal` et `chlorophyll fluorescence`.
- La page GitHub du projet le presente comme un toolkit open source de phenotypage vegetal par vision.

### Ce qui est utile mais limite

- `PlantVillage-Dataset` reste un dataset tres visible pour la maladie foliaire, mais ce n'est pas une brique produit.
- `tomatOD` est un petit dataset specialise tomate pour `localization + ripening classification`, utile en benchmark, pas en systeme general.

### Lecture Project OS

- Si `Project OS` devait un jour faire de la veille image sur des cultures, `PlantCV` serait la seule vraie piste `ADAPT`.
- `PlantVillage` et `tomatOD` restent `DEFER` ou `REJECT` tant qu'il n'existe ni verticale agronomie ni profil image dedie.

## Ce que le precedent audit faisait bien, et ce qu'il fallait corriger

- Le precedent audit etait bon comme `test de protocole`.
- Il etait moins bon comme `rapport tomate pour humain`, parce qu'il parlait trop de la maniere dont `Project OS` devait traiter le sujet.
- La version presente renverse cet ordre: d'abord le contenu tomate, ensuite seulement la traduction `Project OS`.

## Translation Project OS

- Sujet a garder en `docs/audits/`, pas dans `runtime`, `gateway`, `router` ou `session`.
- Sortie durable recommandee:
  - `Markdown` dans le repo
  - `PDF` en cold archive pour lecture mobile
  - `manifest` et sources dans l'archive froide
- Si tu veux une veille recurrente, la bonne mecanique est:
  - `scheduler` pour refresh leger
  - `memory` pour stocker les deltas dates / chiffres / regles
  - `aucune` nouvelle verticale metier tant qu'il n'existe pas un cas d'usage tomate ou agronomie reel

## Decision grid

| Element | Decision | Pourquoi |
| --- | --- | --- |
| USDA SNAP-Ed + FoodData Central | `KEEP` | base nutrition claire et institutionnelle |
| USDA NASS California Processing Tomato Report | `KEEP` | meilleur signal marche court terme |
| APHIS + EPPO | `KEEP` | seules verites reglementaires/phytosanitaires a jour |
| TGRC + UC ANR + UC Davis Pilot Plant | `KEEP` | meilleur mix genetique / agronomie / industrie |
| PlantCV | `ADAPT` | seul satellite logiciel assez serieux si un jour un besoin image apparait |
| PlantVillage / tomatOD | `DEFER` ou `REJECT` | bons datasets, mauvais fit produit aujourd'hui |

## Risques et angles morts

- Le risque principal est de sur-vendre la partie sante. La bonne formule est `valeur nutritionnelle claire + recherche active`, pas `tomate miracle`.
- Le risque n 2 est reglementaire: un dossier qui ne distingue pas `fruit pour consommation` et `propagative material` sera vite faux.
- Le risque n 3 est methodologique: beaucoup de repos tomate sur GitHub sont surtout des demos de classification de feuilles, pas des briques robustes.
- Le risque n 4 est documentaire: les series mondiales ont des horizons de mise a jour differents selon `FAO`, `OWID`, `USDA`; il faut toujours ecrire la date et la plage couverte.

## Questions ouvertes

- Veux-tu un `vrai dossier tomate` purement documentaire, ou une `veille recurrente tomate` avec refresh automatique des sources USDA / APHIS / EPPO ?
- Faut-il etendre ce dossier avec une annexe `prix / commerce international / transformation`, ou la version actuelle suffit-elle ?
- Souhaites-tu une annexe separee `Project OS x agronomie x computer vision`, centree sur `PlantCV`, `PlantVillage` et `tomatOD` ?

## Sources primaires et principales

- [Tomatoes | SNAP-Ed](https://snaped.fns.usda.gov/resources/nutrition-education-materials/seasonal-produce-guide/tomatoes) - USDA Food and Nutrition Service - accessed 2026-03-16 - portion et nutrition simple pour lecteur humain
- [FoodData Central Downloadable Data](https://fdc.nal.usda.gov/download-datasets/) - USDA National Agricultural Library / ARS - accessed 2026-03-16 - montre la maintenance et les releases de la base nutritionnelle USDA
- [2026 California Processing Tomato Report](https://www.nass.usda.gov/Statistics_by_State/California/Publications/Specialty_and_Other_Releases/Tomatoes/2026/PTOMInt_0126.pdf) - USDA NASS - 2026-01-23 - signal marche/industrie le plus concret pour 2026
- [Tomato production - Our World in Data](https://ourworldindata.org/grapher/tomato-production) - FAO data processed by Our World in Data - last updated 2025-03-17, date range 1961-2023 - serie longue publique tomate
- [Agricultural production statistics 2010-2024](https://www.fao.org/statistics/highlights-archive/highlights-detail/agricultural-production-statistics-2010-2024/) - FAO Statistics - 2025-12-23 - confirme le perimetre temporel recent des donnees de production
- [Tomato Brown Rugose Fruit Virus Federal Import Order FAQs](https://www.aphis.usda.gov/plant-imports/how-to-import/import-federal-orders/tomato-brown-rugose-fruit-virus-federal-import) - USDA APHIS - last modified 2025-09-16 - statut import semences/transplants
- [APHIS Protects Domestic Fruit Production and Deregulates Tomato Brown Rugose Fruit Virus in Fruit for Consumption](https://direct.aphis.usda.gov/news/agency-announcements/aphis-protects-domestic-fruit-production-deregulates-tomato-brown-rugose) - USDA APHIS - 2024-06-17 - revision cle sur le fruit destine a la consommation
- [Ralstonia Solanacearum Race 3 Biovar 2](https://direct.aphis.usda.gov/plant-pests-diseases/ralstonia) - USDA APHIS - last modified 2026-01-13 - risque severe pour la tomate
- [Tobamovirus fructirugosum (TOBRFV) Reporting Service Articles](https://gd.eppo.int/taxon/TOBRFV/reporting) - EPPO Global Database - accessed 2026-03-16 - suivi 2025-2026 des signalements ToBRFV
- [EPPO Reporting Service 2026 no. 2](https://gd.eppo.int/media/data/reporting/rs-2026-02-en.pdf) - EPPO - 2026-02 - signaux 2026 sur ToBRFV et autres agents
- [Crinivirus tomatichlorosis (ToCV) Datasheet](https://gd.eppo.int/taxon/TOCV00/datasheet) - EPPO Global Database - accessed 2026-03-16 - impact serre / culture tomate
- [About the TGRC](https://tgrc.ucdavis.edu/about-us) - UC Davis - 2026-03-11 - reference genetique tomate
- [California Processing Tomato Industry Pilot Plant](https://caes.ucdavis.edu/research/facilities/plant) - UC Davis - 2024-08-02 - capacite R&D industrie tomate
- [Managing Pests in Gardens: Vegetables: Tomato](https://ipm.ucanr.edu/home-and-landscape/tomato/index.html) - UC ANR IPM - accessed 2026-03-16 - taxonomie terrain des ravageurs/maladies/desordres
- [Integrative Trait Analysis for Enhancing Heat Stress Resilience in Tomato](https://pubmed.ncbi.nlm.nih.gov/40006792/) - PubMed - 2025-02-10 - signal recent sur la tolerance a la chaleur
- [Heat stress in tomato plants: current challenges and future directions for sustainable agriculture](https://www.tandfonline.com/doi/abs/10.1080/01140671.2024.2432624) - New Zealand Journal of Crop and Horticultural Science - 2025 volume issue - review sur stress thermique
- [Dietary intake of tomato and lycopene, blood levels of lycopene, and risk of total and specific cancers in adults](https://pubmed.ncbi.nlm.nih.gov/40013157/) - PubMed - 2025 - meta-analyse prospective, a lire avec prudence
- [The effect of tomato and lycopene on clinical characteristics and molecular markers of UV-induced skin deterioration](https://pubmed.ncbi.nlm.nih.gov/36606553/) - PubMed - 2024-06 - meta-analyse essais d'intervention
- [PlantCV documentation](https://docs.plantcv.org/en/stable/) - PlantCV docs - accessed 2026-03-16 - toolkit image plante mature
- [danforthcenter/plantcv](https://github.com/danforthcenter/plantcv) - GitHub - accessed 2026-03-16 - repo satellite logiciel le plus serieux
- [spMohanty/PlantVillage-Dataset](https://github.com/spMohanty/PlantVillage-Dataset) - GitHub - accessed 2026-03-16 - dataset amont tres visible mais non produit
- [up2metric/tomatOD](https://github.com/up2metric/tomatOD) - GitHub - accessed 2026-03-16 - petit dataset specialise tomate
