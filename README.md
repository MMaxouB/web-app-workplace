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

397 tests : 276 hérités du cœur métier du bot Discord (writer,
vault, repository, services, analytics), 41 pour l'API de lecture,
29 pour les écritures, 20 pour la surveillance du Vault et
31 pour le fil d'activité.

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
│   │                     analytics, historique
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
GET /api/search?q=                  projets, tâches, collaborateurs
GET /api/activity                   fil des changements ?limite= &type=
                                    &genre= &changements=
GET /api/graph                      relations ?inclure_terminees=
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

## Ce qui reste à faire

Cette version couvre les **phases 1 à 5** du cahier des charges
(`03-Documentation/architecture_obsidian_web_app.md`).

### Ensuite

- **§16** — knowledge base. Reportée d'un commun accord : ses types
  (`knowledge`, `resource`) n'existent pas encore dans le Vault, il
  faudrait d'abord décider de l'arborescence.
- **§27** — index mémoire. À 43 notes, un parcours complet coûte 18 ms.
  Inutile aujourd'hui, à reprendre vers 400 notes. Le surveillant est
  l'endroit où le brancher : il sait déjà quelles notes ont changé.
- **§7** — classification automatique, recherche sémantique. Après
  stabilisation, comme prévu.

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
