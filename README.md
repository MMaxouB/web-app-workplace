# Vault Web

Interface web locale au-dessus du Vault Obsidian.

Le Vault reste la **source de vérité**. L'application le lit, l'affiche
et y écrit — toujours à travers le `VaultWriter`, jamais en réécrivant
un fichier entier. Rien n'y est jamais supprimé.

```text
NAVIGATEUR  →  API FastAPI  →  Services / Repository  →  Vault Writer  →  OBSIDIAN
```

## Lancer

```bash
./lancer.sh
```

Le script crée l'environnement Python au premier démarrage, lance le
serveur et ouvre le navigateur sur <http://127.0.0.1:8765>.

L'écoute est volontairement bouclée sur `127.0.0.1` : le Vault contient
des données personnelles et l'API n'a aucune authentification.

> Démarrage, arrêt, dépannage : **[DEMARRER.md](DEMARRER.md)**.
> Ce fichier-ci décrit le fonctionnement interne.

## Tester

```bash
.venv/bin/python -m pytest
```

546 tests. Le socle vient du cœur métier du bot Discord — writer,
vault, repository, services, analytics — auquel s'ajoutent 76 tests
d'API, 29 d'écriture, 20 pour la surveillance du Vault et 31 pour le
fil d'activité.

Le branchement des connaissances en a apporté 149, dont 28 pour la
navigation dans la base, 25 pour le journal, 20 pour les notes de
projet et 14 pour la lecture des cases et des liens.

Aucun test n'écrit dans le vrai Vault. Ceux qui écrivent construisent
un Vault temporaire ; deux fichiers (`test_vault.py`,
`test_repository.py`) lisent le vrai Vault sans jamais le modifier.

## Organisation

```text
vault_web/
├── core/                 cœur métier, repris de l'archive du bot
│   ├── config.py         chemin du Vault, port, étiquette de source
│   ├── obsidian/         vault, repository, writer, models
│   ├── services/         tasks, projects, collaborators, notes,
│   │                     connaissances, notes_projet, journal,
│   │                     analytics, historique
│   ├── utils/            text (comparaison tolérante), markdown
│   │                     (cases à cocher, liens [[...]])
│   └── surveillance.py   file watcher du Vault (§28)
├── api/
│   ├── app.py            routes de lecture, montage du frontend
│   ├── ecriture.py       création, modification, archivage
│   └── schemas.py        modèles → JSON, encodage des identifiants
├── web/
│   ├── index.html
│   └── static/           style.css, app.js
├── tests/
└── lancer.sh
```

## Configuration

Tout est optionnel — sans configuration, le Vault voisin `travail/` est
utilisé.

| Variable | Défaut | Rôle |
|---|---|---|
| `OBSIDIAN_VAULT_PATH` | `../travail` | emplacement du Vault |
| `VAULT_WEB_PORT` | `8765` | port d'écoute |
| `VAULT_WEB_HOST` | `127.0.0.1` | interface d'écoute |
| `VAULT_WEB_SOURCE` | `depuis la web app` | étiquette écrite dans l'historique des notes |

Elles se placent dans l'environnement ou dans un fichier `.env` à la
racine du projet.

## API

### Lecture

```text
GET /api/dashboard                  compteurs, progression, urgences, santé
GET /api/tasks                      ?status= &priority= &platform= &project=
                                    &collaborator= &open_only=
GET /api/tasks/{id}                 fiche + contenu Markdown
GET /api/projects                   ?status=   (progression incluse)
GET /api/projects/{id}              fiche + tâches rattachées + note
GET /api/projects/{id}/stats        répartitions par statut et priorité
GET /api/collaborators              ?status=
GET /api/collaborators/{id}         fiche + tâches
GET /api/knowledge                  ?domaine= &sujet= &categorie=
                                    &maturite= &tag=
GET /api/knowledge/{id}             fiche + Markdown + liens résolus
GET /api/notes                      ?project= &archivees=  (points inclus)
GET /api/notes/{id}                 fiche + Markdown + points
GET /api/journal                    journées, de la plus récente
GET /api/search?q=                  les cinq types de notes
GET /api/activity                   fil des changements ?limite= &type=
                                    &genre= &changements=
GET /api/graph                      relations ?inclure_terminees=
                                    &inclure_connaissances=
GET /api/meta                       valeurs acceptées par les formulaires
GET /api/health                     état du Vault
```

### Écriture

```text
POST   /api/tasks                   créer une tâche
POST   /api/tasks/capture           capture rapide → _Inbox
PATCH  /api/tasks/{id}              status, priority, platform, project,
                                    collaborator, deadline (libellé),
                                    due_date (date précise, calendrier)
DELETE /api/tasks/{id}              ARCHIVE (ne supprime jamais)

POST   /api/projects                créer un projet
PATCH  /api/projects/{id}           status, priority, category, deadline,
                                    repository
DELETE /api/projects/{id}           ARCHIVE

POST   /api/collaborators           créer une fiche
PATCH  /api/collaborators/{id}      status (3 valeurs), role, company,
                                    discord, email, github, website, timezone

POST   /api/{genre}/{id}/notes      ajouter un texte sous « ## Notes »

POST   /api/journal                 une ligne dans la journée en cours
PATCH  /api/notes/{id}/points/{n}   cocher / décocher un point
```

### Deux règles d'écriture

**`DELETE` archive, il ne supprime pas.** La note passe en `archived`
et rejoint son dossier `Archives`. Aucun fichier Markdown n'est jamais
effacé par l'application — un bouton dans un navigateur ne doit pas
pouvoir détruire une source de vérité.

**Les écritures concurrentes sont détectées.** Chaque note expose une
`version` (sa date de modification). Si le client la renvoie et qu'elle
a changé entre-temps — typiquement parce qu'Obsidian était ouvert —
l'écriture est refusée avec un **409** au lieu d'écraser silencieusement.
La `version` est facultative : sans elle, aucun contrôle n'est fait.

Un `PATCH` qui renvoie une valeur déjà en place la saute silencieusement.
Les services du bot refusaient ce cas ; depuis un formulaire, qui poste
tous ses champs, ce refus ferait échouer un enregistrement légitime.

### Identifiants

L'identifiant d'une note est son chemin relatif au Vault, encodé en
base64 URL-safe. Il permet de retrouver le fichier Markdown sans base
de données ni table de correspondance.

Un identifiant forgé ne donne accès à rien : le chemin décodé passe par
`_check_path`, qui refuse tout ce qui sort du Vault ou n'est pas du
Markdown. Trois tests couvrent ce point.

## Interface

- **Dashboard** — compteurs, progression, échéances, santé, à faire maintenant, répartitions
- **Inbox** — captures à trier, tâches sans projet, tâches sans échéance
- **Tâches** — trois vues : liste filtrable, kanban, calendrier
- **Fiche tâche** — propriétés éditables au clic, contenu Markdown rendu
- **Projets** — cartes avec progression
- **Fiche projet** — progression, répartitions, tâches liées, note
- **Collaborateurs** — liste et profils
- **Activité** — fil des changements, groupé par jour, filtrable par genre
- **Graph** — relations projets ↔ tâches ↔ collaborateurs, zoomable
- **Connaissances** — arborescence domaine → sujet, filtres par sorte
  et par maturité, nuage de tags, fiche avec liens résolus
- **Notes** — notes de projet groupées par projet, points cochables
- **Journal** — capture en haut de page, journées de la plus récente
- **Recherche** — globale, et palette `Ctrl+K`
- Thème sombre par défaut, thème clair disponible

### Actions

| Geste | Effet |
|---|---|
| `+ Nouvelle tâche` ou `Ctrl+N` | modale de création (§10) |
| `+ Projet`, `+ Nouveau` | modale de création |
| `⚡ Capture rapide` | dépose dans `_Inbox` sans rien décider (§19) |
| Clic sur une propriété | édition sur place, enregistrée aussitôt (§11) |
| Glisser une carte du kanban | change le statut, déplace le fichier (§8) |
| Glisser une tâche du calendrier | déplace l'échéance, recalcule le délai (§9) |
| `Marquer terminée` | change le statut **et** déplace le fichier |
| `Ajouter une note` | écrit sous `## Notes`, sans toucher à l'historique |
| `Archiver` | passe en `archived`, après confirmation |
| `✎ Noter au journal` | une ligne dans la journée du jour, sans quitter la page |
| Clic sur un point de note | coche la case dans le fichier, met `mis_a_jour` à jour |
| Clic sur un tag | filtre la base de connaissances sur ce tag |

Chaque écriture répercute trois choses, comme le faisait le bot : le
frontmatter (qui fait foi), la ligne correspondante du tableau dans le
corps de la note, et une entrée dans `## Historique`.

## Graphiques

Camemberts en SVG pur — chaque part est un arc tracé au
`stroke-dasharray`, aucune bibliothèque. On en trouve :

| Où | Quoi | Centre |
|---|---|---|
| Dashboard | priorités des tâches ouvertes | nombre d'ouvertes |
| Dashboard | répartition par plateforme | nombre de domaines |
| Dashboard | échéances des tâches ouvertes | nombre à faire |
| Fiche projet | état des tâches du projet | % terminé |
| Fiche projet | priorités ouvertes | — |
| Fiche collaborateur | charge ouverte par priorité | — |

Les couleurs portent une information (§24) : rouge pour ce qui est en
retard ou critique, orange pour ce qui presse, bleu pour ce qui est en
cours, vert pour ce qui est fait, gris pour le neutre. Les axes sans
hiérarchie — plateformes, projets — utilisent une palette qualitative
d'intensité comparable, pour qu'aucune part ne paraisse plus grave
qu'une autre.

### Ce que les graphiques comptent

**Les tâches archivées n'apparaissent nulle part** : ni dans les
graphiques, ni dans le calendrier, ni dans la progression. Une tâche
archivée est abandonnée ou sans objet — elle n'est ni faite ni à
faire, et la compter gonflerait des chiffres qui ne correspondent à
aucun travail. Archiver une tâche ne fait donc pas chuter le
pourcentage d'avancement.

**Les tâches terminées ne comptent que dans le bloc « Avancement »**,
dont c'est précisément l'objet. Les répartitions de charge — priorités,
plateformes, projets, échéances — ne montrent que le travail restant.

Le calendrier garde les tâches terminées, barrées et estompées : c'est
utile pour se rappeler ce qu'on a fini cette semaine. Le nombre
d'archivées masquées y est annoncé — masquer sans le dire ferait croire
à un calendrier incomplet.

Une ligne de répartition à zéro s'affiche en pointillés estompés plutôt
qu'en barre pleine grise, qui se lisait comme un graphique cassé.

## Kanban et calendrier

La page Tâches propose trois vues : **Liste**, **Kanban**, **Calendrier**.

**Kanban** (§8) — trois colonnes `active` / `waiting` / `completed`.
Glisser une carte change son statut, donc déplace le fichier dans le
dossier correspondant. Le glisser-déposer utilise l'API HTML5 native,
sans bibliothèque.

**Calendrier** (§9) — grille mensuelle sur le champ `due`, navigation
mois par mois. Glisser une tâche sur un autre jour déplace son échéance.

### Le libellé de délai déduit de la date

`deadline` ne stocke que des libellés (`7j`, `14j`) et `due` la date
correspondante ; les conventions du Vault veulent que les deux restent
cohérents. Poser une date au calendrier fait donc l'inverse du chemin
habituel : la date est donnée, le libellé en est déduit.

Déposer une tâche à neuf jours d'ici écrit `deadline: 9j` — le format
du Vault est respecté même quand la valeur ne fait pas partie des
délais proposés à la création. L'heure de l'échéance d'origine est
conservée : seule la date change, comme le geste le laisse attendre.

Une date dans le passé garde l'ancien libellé plutôt que d'écrire
`-3j`, qui ne voudrait rien dire.

## Synchronisation avec Obsidian (§28)

Le serveur surveille le dossier du Vault et prévient le navigateur dès
qu'une note change. Modifier une note dans Obsidian met l'interface à
jour toute seule, sans rien cliquer.

```text
Obsidian → fichier modifié → watchfiles (inotify) → SSE → interface rafraîchie
```

`watchfiles` arrive avec `uvicorn[standard]` : aucune dépendance
supplémentaire. C'est le noyau qui signale les changements, il n'y a
aucun parcours périodique du disque.

Une pastille en bas de la barre latérale indique l'état : verte quand
le Vault est surveillé, grise si le flux est coupé. `EventSource` se
reconnecte tout seul.

### Ce qui est ignoré, et pourquoi

| Ignoré | Raison |
|---|---|
| `.obsidian/` | Obsidian y réécrit `workspace.json` en continu — chaque déplacement de curseur ferait clignoter l'écran |
| `.nom.md.tmp` | le fichier temporaire de notre propre writer : sans ce filtre, chaque écriture serait annoncée deux fois |
| tout sauf `.md` | images, pièces jointes, fichiers de configuration |

### Les fichiers de l'interface ne sont pas mis en cache

`app.js` et `style.css` sont servis avec `Cache-Control: no-cache`.
L'application étant locale, il n'y a rien à gagner à les mettre en
cache, et beaucoup à perdre : après une modification du code, le
navigateur continuait de servir l'ancienne version — y compris après
un rechargement, ce qui donne l'impression que le correctif n'a pas
été appliqué.

### Deux précautions côté navigateur

**Nos propres écritures ne se rejouent pas.** Après un `PATCH`, la vue
est déjà rafraîchie ; l'événement qui suit dans la foulée est ignoré.

**Une saisie en cours n'est jamais interrompue.** Si une modale est
ouverte ou une propriété en cours d'édition, le rafraîchissement est
mis de côté et rattrapé dès que l'utilisateur a terminé — les notes
concernées sont accumulées pour que le message final dise ce qui a
réellement bougé.

## Fil d'activité (§29)

Le cahier des charges propose de stocker l'historique « dans une zone
système du Vault si nécessaire ». Ce n'était pas nécessaire, et cela
aurait contredit le §33 : chaque note tient déjà son propre
`## Historique`, écrit à chaque modification. La page Activité les
relit et les fusionne.

**Aucune donnée n'est créée à côté.** Effacer un historique dans
Obsidian le fait disparaître du fil — c'est le propre d'une vue, pas
d'un journal parallèle.

### Deux formats, deux natures

Les sous-titres datés existent sous deux formes, héritées des services :

```text
### 17/08/2026 16:15     tâches — une entrée par modification
### 2026-08-17           projets, collaborateurs — puces groupées
```

Les deux sont lus. Une date impossible (`31/02/2026`) fait ignorer le
groupe plutôt qu'échouer sur tout le Vault.

Chaque entrée est ensuite **classée** selon sa forme : `statut`,
`priorite`, `echeance`, `champ`, `creation` — ou `note` quand elle a
été rédigée à la main. La distinction compte : sur le Vault réel, 86
des 167 entrées sont des comptes rendus manuscrits, dont certains font
dix lignes. Un seul suffit à enterrer vingt changements réels, d'où
le filtre « Changements » proposé par défaut.

## Vue Graph (§22, §23)

Les relations du Vault, dessinées : projets, tâches et collaborateurs,
reliés par les rattachements que le Repository sait déjà déduire.

Deux sortes de liens, tous deux tirés de champs en **texte libre** :
une tâche appartient à un projet quand son champ `project` correspond
au nom ou au nom de fichier de celui-ci ; elle est confiée à quelqu'un
quand son champ `collaborator` correspond à une fiche. La comparaison
est tolérante — sans accents, sans casse, sans ponctuation.

### La disposition est déterministe

Les positions viennent d'une simulation par forces écrite à la main —
répulsion entre tous les nœuds, ressorts sur les liens, rappel vers le
centre. Une trentaine de nœuds ne justifie pas une bibliothèque.

Le départ est une spirale d'angle d'or, **sans aucun tirage au sort** :
deux affichages successifs donnent exactement le même dessin. Un graphe
qui se réarrange à chaque visite oblige à réapprendre la carte à chaque
fois.

### Ce que la vue rend visible

Les nœuds **sans aucune relation** sont dessinés en pointillés. C'est
l'information la plus utile de cette page : sur le Vault réel, elle a
fait apparaître une tâche rattachée à « Refonte espace de tr**v**ail »
— une faute de frappe qui la détachait silencieusement de son projet.

Les tâches archivées ne sont jamais dans le graphe. Les terminées sont
écartées par défaut, mais un bouton les ramène : voir ce qu'un projet a
produit est un usage légitime.

Survoler un nœud estompe tout sauf son voisinage, cliquer ouvre la
fiche, la molette zoome et le glisser déplace.

## Connaissances, notes et journal (§16)

Trois types de notes se sont ajoutés au Vault avec leurs conventions
(`03-Documentation/Base de connaissances.md` et `Notes et journal.md`).
L'application les lit désormais tous les trois.

```text
06-Connaissances/    type: knowledge   navigation domaine → sujet
07-Notes/            type: note        points cochables
07-Notes/Journal.md  type: journal     capture rapide
```

### Ici, le dossier ne suit pas le statut

C'est la seule différence qui compte, et toute l'organisation en
découle. Pour une tâche, changer `status:` **oblige** à déplacer le
fichier. Pour une connaissance, le dossier dit le **sujet**, jamais
l'avancement : elle ne déménage jamais — sinon les liens `[[...]]`
casseraient — et ce qui évolue, c'est son champ `maturite`.

Conséquence directe : il n'y a ni bouton « Archiver » ni changement de
statut sur ces écrans. La navigation descend `domaine → sujet`, les
filtres portent sur `categorie` et `maturite`, et les tags traversent
l'arborescence.

### Le frontmatter fait foi, le dossier dépanne

`domaine` et `sujet` sont lus dans le frontmatter — c'est lui que
lisent les requêtes Dataview. Quand le champ manque, le dossier prend
le relais : une note incomplète reste rangée quelque part plutôt que
de tomber dans un fourre-tout.

Quand les deux se contredisent, la fiche le dit. Ce n'est pas une
erreur — la note reste parfaitement lisible — mais elle sera
introuvable là où on la cherchera. C'est le contrôle Dataview des
conventions, ramené à l'écran, et un test le rejoue sur le vrai Vault
à chaque exécution de la suite.

### Les compteurs ne suivent pas les filtres

L'arborescence, les catégories, les maturités et les tags comptent
toujours sur la **base entière**. Des compteurs qui rétrécissent avec
la sélection finissent par ne plus rien proposer, et on ne peut plus
changer de filtre sans tout remettre à zéro.

### Une note de projet n'a aucune criticité

Ni priorité, ni statut, ni échéance : rien à décider en l'écrivant,
rien à tenir à jour ensuite. Son avancement se lit dans ses cases
cochées, et nulle part ailleurs.

Les points sont donc **cochables là où on les lit** — dans la liste,
dans la fiche, et dans le dashboard du projet — et seule la carte
concernée se redessine. Un rendu complet de la page ferait sauter
l'écran à chaque clic.

Une case cochée met `mis_a_jour` au jour même, une seule fois par
jour : les conventions présentent ce champ comme la date de dernière
modification, et une requête Dataview trie dessus. Recocher une case
déjà cochée n'écrit rien du tout.

**Le libellé du point voyage avec le clic.** L'interface renvoie le
texte qu'elle affichait ; s'il ne correspond plus, le serveur répond
409 au lieu de cocher la mauvaise ligne. Une note réorganisée dans
Obsidian décale ses points, et rien ne le signalerait autrement.

### Le nom de projet qui n'existe pas

Les notes sont groupées par le champ `project` **tel qu'il est
écrit** — c'est ce qui fait apparaître « Refonte espace de tr**v**ail »
juste à côté de « Refonte espace de travail ». Le serveur, lui, dit si
ce nom retombe sur un vrai projet, et le groupe se signale sinon.

Les conventions confient explicitement ce contrôle à l'application :
Dataview ne sait pas confronter deux ensembles de notes dans une même
requête, « la comparaison tolérante, sans accents ni casse, reste le
travail de la web app ».

### Le journal s'écrit à la fin

C'est l'inverse des historiques de fiches, rangés du plus récent au
plus ancien. Ici l'ordre du fichier est chronologique, parce que le
geste décrit par les conventions est « `Ctrl + Fin`, écrire une ligne,
fermer ». L'écran, lui, montre d'abord la journée du jour.

La puce vide que le gabarit dépose sous chaque nouvelle date est
**remplacée**, pas doublée : ce n'est pas une ligne du journal, c'est
un endroit où écrire.

Le fichier est trouvé par son `type: journal`, jamais par son nom. Les
conventions prévoient qu'il devienne `Journal 2026.md` le jour où il
sera trop gros, en précisant que rien ne dépend de son nom — coder le
chemin en dur aurait démenti cette phrase à la première archive. Et
aucun fichier n'est créé : sans note `type: journal`, l'écran le dit
et renvoie au gabarit d'Obsidian.

### Ce qui reste dans Obsidian

Les connaissances et les notes se **créent** dans Obsidian, par leurs
templates Templater. Ils posent le frontmatter, rangent le fichier
selon le domaine et proposent le squelette de la catégorie choisie ;
le menu des projets d'une note est lu dans le Vault, ce qui évite la
faute de frappe qui la détacherait de son projet. Deux chemins de
création finiraient par diverger — l'application se contente donc de
lire, de filtrer et de cocher.

### Dans la vue graph

Deux types de nœuds et une troisième sorte de lien s'ajoutent.

Les **notes de projet** se rattachent comme les tâches, par leur champ
`project` et la même comparaison tolérante. C'est le seul contrôle
simple contre la faute de frappe qui détache silencieusement une note
de son projet — celle-là même que la vue avait déjà révélée sur une
tâche.

Les **connaissances** se relient par leurs `[[liens]]`, lus dans le
corps des notes puisque c'est le seul endroit où ils existent. Une
connaissance pèse ce que pèsent ses liens, ce qui fait ressortir les
notes pivots d'un domaine ; une note sans lien pèse zéro et se dessine
en pointillés, comme le reste des isolés.

Les fiches classiques ne sont pas dépouillées de la sorte : leurs
`[[Alice]]` de courtoisie doubleraient des rattachements déjà déduits
des champs, sans rien apprendre. Un bouton écarte les connaissances du
dessin le jour où la base sera trop fournie pour rester lisible.

## Ce qui reste à faire

Cette version couvre les **phases 1 à 5** du cahier des charges
(`03-Documentation/architecture_obsidian_web_app.md`).

Le **§16** s'y ajoute : la base de connaissances, les notes de projet
et le journal sont branchés.

### Ensuite

- **§7** — classification automatique, recherche sémantique. Après
  stabilisation, comme prévu.
- **Créer une connaissance ou une note depuis l'application.** Écarté
  pour l'instant : les templates Templater font mieux, et deux chemins
  de création finiraient par diverger. À rouvrir si le besoin se fait
  sentir hors d'Obsidian.
- **Modifier `maturite` depuis la fiche.** L'écriture existe déjà
  (`set_frontmatter_field`) ; ce qui manque, c'est de décider si une
  maturité se change d'un clic ou après relecture — le champ est un
  engagement, pas un statut.
- **Promouvoir une ligne du journal en tâche ou en note.** Prévu par
  les conventions, pas encore fait.
- **Backlinks sur une fiche de connaissance.** Les liens sortants sont
  résolus ; les entrants demandent un parcours de tous les corps, donc
  l'index mémoire ci-dessous.
- **§27** — index mémoire. À 58 notes, un tableau de bord complet coûte
  31 ms. Inutile aujourd'hui, à reprendre vers 400 notes. Le
  surveillant est l'endroit où le brancher : il sait déjà quelles notes
  ont changé.

## Origine du code

`core/` vient de l'archive du bot Discord
(`obsidian-discord-bot-archive-2026-08-16.tar.gz`), conformément à la
§32 du cahier des charges : « le cœur métier doit être réutilisé ».

Modifications apportées à l'extraction :

- paquet `bot/` renommé `core/`, dépendance à `bot.config.settings`
  (qui exigeait un token Discord) remplacée par `core/config.py` ;
- modules Discord écartés : `journal.py`, `security/permissions.py`,
  `services/dashboard.py`, `services/channels.py` ;
- « depuis Discord » remplacé par une étiquette configurable ;
- `ObsidianRepository._collect_all()` ajouté : `workspace()` et
  `search()` relisaient le Vault trois fois — une fois par type de
  note. Un seul parcours donne le même résultat trois fois plus vite
  (54 ms → 18 ms sur 42 notes).
