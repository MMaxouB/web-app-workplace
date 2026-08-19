# Démarrer Vault Web

## Lancer

```bash
cd "/home/maxime/Documents/document semaine camping/vault_web" && ./lancer.sh
```

Le navigateur s'ouvre tout seul sur **<http://127.0.0.1:8765>**.

Au tout premier lancement, le script installe l'environnement Python
(une trentaine de secondes). Les fois suivantes, le démarrage est
immédiat.

## Arrêter

`Ctrl + C` dans le terminal où tourne le script.

Si le terminal a été fermé sans arrêter le serveur :

```bash
pkill -f "uvicorn api.app:app"
```

## Vérifier que ça tourne

```bash
curl -s http://127.0.0.1:8765/api/health
```

Réponse attendue — le chemin du Vault et le nombre de notes lues :

```json
{"vault":"/home/maxime/Documents/document semaine camping/travail","existe":true,"notes":59}
```

## Si ça ne marche pas

**« Address already in use »** — un serveur tourne déjà. Soit il est
déjà ouvert dans un onglet, soit il faut l'arrêter avec le `pkill`
ci-dessus.

**Lancer sur un autre port :**

```bash
VAULT_WEB_PORT=9000 ./lancer.sh
```

**La page s'affiche mais reste vide** — regarde ce que dit
`/api/health`. Si `"existe": false`, le Vault n'a pas été trouvé ;
l'application le cherche dans le dossier `travail/` voisin. Pour le
désigner explicitement :

```bash
OBSIDIAN_VAULT_PATH="/chemin/vers/le/vault" ./lancer.sh
```

**Une modification faite dans Obsidian n'apparaît pas** — regarde la
pastille en bas à gauche de la barre latérale. Verte, le Vault est
surveillé et les changements arrivent tout seuls. Grise, le lien est
coupé : recharge la page, ou utilise `⟳` en haut à droite.

## Bon à savoir

Le serveur n'écoute que sur `127.0.0.1` : il est **inaccessible depuis
le réseau**, y compris depuis un autre appareil de la maison. C'est
voulu — le Vault contient tes vraies données et l'application n'a pas
de mot de passe.

Obsidian peut rester ouvert pendant que l'application tourne. Mieux :
une note modifiée dans Obsidian apparaît dans le navigateur **sans
rien cliquer**. Et si une note est modifiée des deux côtés en même
temps, l'application refuse d'écrire et te le dit, plutôt que
d'écraser ce que tu viens de taper.

Rien n'est jamais supprimé : le bouton « Archiver » déplace la note
dans `Archives` et change son statut, le fichier Markdown reste.

## Raccourcis

| Touches | Effet |
|---|---|
| `Ctrl + K` | rechercher dans tout le Vault |
| `Ctrl + N` | nouvelle tâche |
| `Échap` | fermer la fenêtre ouverte |

## Ce qu'on peut faire

Depuis la page **Tâches**, trois vues au choix — liste, kanban,
calendrier.

- **Kanban** : glisser une carte d'une colonne à l'autre change son
  statut et déplace le fichier dans le bon dossier.
- **Calendrier** : glisser une tâche sur un autre jour déplace son
  échéance et recalcule le délai.
- **Fiches** : cliquer sur une propriété la modifie sur place.
- **Activité** : le fil de tout ce qui a changé, jour par jour. Il est
  lu dans les notes elles-mêmes — rien n'est stocké à côté.
- **Graph** : la carte des relations. Les notes en pointillés ne sont
  rattachées à rien — souvent une faute de frappe dans un champ.

Et pour ce qu'on apprend plutôt que ce qu'on fait :

- **Connaissances** : l'arborescence à gauche suit les dossiers de
  `06-Connaissances`, les filtres portent sur la sorte de note et sa
  maturité, et les tags traversent tout ça. Une note qui annonce un
  domaine et vit dans un autre dossier se signale sur sa fiche.
- **Notes** : les notes de `07-Notes`, groupées par projet. Les cases
  se cochent directement dans la liste — elles sont écrites dans le
  fichier, et rien d'autre n'y bouge. On les retrouve aussi dans le
  dashboard de leur projet, à côté de ses tâches.
- **Journal** : le champ en haut de la page ajoute une ligne à la
  journée du jour. Le bouton `✎ Noter au journal` de la barre latérale
  fait la même chose depuis n'importe quel écran.

Les connaissances et les notes se **créent dans Obsidian**, avec leurs
templates : ils rangent le fichier et posent le bon squelette. Ici,
on les lit, on les filtre et on coche.

## En cas de doute

Le Vault est un dépôt git. Pour voir ce qui a changé, puis tout
annuler si besoin :

```bash
git -C "/home/maxime/Documents/document semaine camping/travail" diff
```

```bash
git -C "/home/maxime/Documents/document semaine camping/travail" checkout .
```

---

Le détail technique — API, organisation du code, choix d'architecture —
est dans [README.md](README.md).
