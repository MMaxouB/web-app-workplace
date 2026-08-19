"""API HTTP au-dessus du Vault Obsidian.

Routes de lecture de la §26 du cahier des charges. Aucune écriture
pour l'instant : la phase 1 se limite à afficher les vraies données
(§34).

Le Vault reste la source de vérité. Rien n'est mis en cache entre
deux requêtes : une note modifiée dans Obsidian est visible au
rafraîchissement suivant, sans file watcher (§28, prévu en phase 6).
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from api.schemas import (
    case_to_dict,
    collaborator_to_dict,
    decode_id,
    encode_id,
    knowledge_to_dict,
    note_to_dict,
    progression_to_dict,
    project_to_dict,
    task_to_dict,
)
from core.config import PROJECT_ROOT, VAULT_PATH
from core.obsidian.repository import (
    ObsidianRepository,
    belongs_to,
    count_tasks,
    same_reference,
    sort_tasks,
)
from core.obsidian.vault import ObsidianVault
from core.utils.text import normalize
from core.services import (
    analytics,
    connaissances,
    historique,
    notes_projet,
)
from core.services.journal import JournalError, JournalService
from core.utils.markdown import lire_liens
from core.surveillance import SurveillantVault


logger = logging.getLogger(__name__)


vault = ObsidianVault(VAULT_PATH)
repository = ObsidianRepository(vault)

surveillant = SurveillantVault(VAULT_PATH)


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    """Démarre la surveillance du Vault avec le serveur (§28)."""
    await surveillant.demarrer()

    try:
        yield
    finally:
        await surveillant.arreter()


app = FastAPI(
    title="Vault Web",
    version="0.3.0",
    lifespan=cycle_de_vie,
)

WEB_DIR = PROJECT_ROOT / "web"


# Routes d'écriture (création, modification, archivage). Déclarées
# avant le montage du frontend, qui capture tout le reste.
from api.ecriture import router as routeur_ecriture  # noqa: E402
from api.ecriture import version_de  # noqa: E402

app.include_router(routeur_ecriture)


# =====================================================
# Utilitaires
# =====================================================


def _note_path(note_id: str) -> Path:
    """Chemin d'une note à partir de son identifiant, ou 404.

    Le chemin décodé traverse `_check_path`, qui refuse tout ce qui
    sort du Vault ou n'est pas du Markdown : un identifiant forgé ne
    donne pas accès au reste du disque.
    """
    try:
        chemin = decode_id(note_id, VAULT_PATH)

        return vault._check_path(chemin)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error


def _ensure_exists(path: Path) -> Path:
    if not path.is_file():
        raise HTTPException(404, f"Note introuvable : {path.name}")

    return path


def _match(valeur: str | None, attendu: str | None) -> bool:
    """Filtre insensible à la casse, neutre si le filtre est absent."""
    if not attendu:
        return True

    return (valeur or "").casefold() == attendu.casefold()


def _tasks_of(collaborator_name: str, taches: list) -> list:
    """Tâches rattachées à un collaborateur.

    Le champ `collaborator` d'une tâche est du texte libre, et il
    contient parfois plusieurs personnes (« Me + ZIPZOP »). Une
    égalité stricte n'y retrouve personne : on réutilise la
    comparaison tolérante du Repository, celle qui rattache déjà les
    tâches aux projets.
    """
    return [
        task
        for task in taches
        if same_reference(task.collaborator, collaborator_name)
    ]


def _points_de(chemin: Path) -> list:
    """Cases à cocher d'une note, ou liste vide si elle est illisible.

    Une note abîmée ne doit pas vider tout l'écran : elle apparaît
    sans avancement, ce qui se voit et se corrige.
    """
    try:
        return notes_projet.points(vault.read_body(chemin))
    except (OSError, ValueError):
        logger.warning("Points illisibles : %s", chemin)

        return []


def _note_avec_points(note, projets: list | None = None) -> dict:
    """Une note de projet, avec ses points et leur avancement.

    `projets` sert à dire si le champ `project` retombe sur un vrai
    projet du Vault. Les conventions confient ce contrôle à la web
    app : Dataview ne sait pas confronter deux ensembles de notes, et
    c'est le seul garde-fou contre la faute de frappe qui détache
    silencieusement une note de son projet.
    """
    cases = _points_de(note.path)

    donnees = note_to_dict(note, VAULT_PATH)

    donnees["points"] = [case_to_dict(case) for case in cases]
    donnees["progression"] = progression_to_dict(
        notes_projet.progression(cases)
    )

    if projets is None:
        projets = repository.get_projects()

    donnees["orpheline"] = bool(
        note.project
        and not any(belongs_to(note, projet) for projet in projets)
    )

    return donnees


def _index_des_notes(contenu) -> dict[str, dict]:
    """Nom de fichier normalisé → de quoi fabriquer un lien.

    Sert à résoudre les `[[liens]]` d'Obsidian, qui désignent une
    note par son nom de fichier. La comparaison est normalisée —
    sans accents, sans casse — comme partout ailleurs.
    """
    index: dict[str, dict] = {}

    lots = (
        (contenu.projects, "project"),
        (contenu.tasks, "task"),
        (contenu.collaborators, "collaborator"),
        (contenu.knowledge, "knowledge"),
        (contenu.notes, "note"),
    )

    for fiches, type_note in lots:
        for fiche in fiches:
            index.setdefault(
                normalize(fiche.filename),
                {
                    "id": encode_id(fiche.path, VAULT_PATH),
                    "type": type_note,
                    "nom": fiche.filename,
                },
            )

    return index


# =====================================================
# Tableau de bord
# =====================================================


@app.get("/api/dashboard")
def get_dashboard():
    """Tout ce dont l'écran d'accueil a besoin, en un seul appel.

    Un parcours du Vault, plusieurs vues dessus : c'est l'intérêt de
    `workspace()`, qui lit et trie les notes en une passe.
    """
    ws = repository.workspace()

    # Les tâches archivées sont abandonnées ou sans objet : elles ne
    # sont ni faites ni à faire. Les compter dans les répartitions
    # gonflerait des chiffres qui ne correspondent à aucun travail.
    vivantes = [
        task
        for task in ws.all_tasks
        if (task.status or "").casefold() != "archived"
    ]

    echeances = analytics.echeances(vivantes)
    progression = analytics.progression(vivantes)
    indicateurs = analytics.sante(
        ws.all_projects,
        ws.all_tasks,
        ws.all_collaborators,
    )

    return {
        "compteurs": {
            "taches_ouvertes": ws.tasks.open,
            "taches_urgentes": ws.tasks.urgent,
            "projets_actifs": ws.projects.active,
            "en_retard": len(echeances.en_retard),
        },
        "progression": progression_to_dict(progression),
        "urgent": [
            task_to_dict(task, VAULT_PATH) for task in ws.urgent
        ],
        "echeances": {
            "compteurs": [
                {"libelle": libelle, "valeur": valeur}
                for libelle, valeur in echeances.compteurs()
            ],
            "pressantes": [
                task_to_dict(task, VAULT_PATH)
                for task in echeances.pressantes
            ],
        },
        "repartitions": {
            "priorites": [
                {"libelle": libelle, "valeur": valeur}
                for libelle, valeur in analytics.repartition_priorites(
                    vivantes
                )
            ],
            # Le seul axe qui compte les tâches terminées : montrer
            # l'avancement est précisément son objet.
            "statuts": [
                {"libelle": libelle, "valeur": valeur}
                for libelle, valeur in analytics.repartition_statuts(
                    vivantes
                )
                if libelle != "Archived"
            ],
            "plateformes": [
                {"libelle": libelle, "valeur": valeur}
                for libelle, valeur in analytics.repartition_plateformes(
                    vivantes
                )
            ],
            "projets": [
                {"libelle": libelle, "valeur": valeur}
                for libelle, valeur in analytics.charge_par_projet(
                    ws.all_projects,
                    vivantes,
                )
            ],
        },
        "sante": {
            "niveau": analytics.niveau_global(indicateurs),
            "indicateurs": [
                {
                    "domaine": ind.domaine,
                    "niveau": ind.niveau,
                    "detail": ind.detail,
                }
                for ind in indicateurs
            ],
        },
        "totaux": {
            "taches": ws.tasks.total,
            "projets": ws.projects.total,
            "collaborateurs": ws.collaborators.total,
        },
    }


# =====================================================
# Tâches
# =====================================================


@app.get("/api/tasks")
def get_tasks(
    status: str | None = None,
    priority: str | None = None,
    platform: str | None = None,
    project: str | None = None,
    collaborator: str | None = None,
    open_only: bool = False,
):
    taches = repository.get_tasks()

    if open_only:
        taches = [task for task in taches if task.is_open]

    taches = [
        task
        for task in taches
        if _match(task.status, status)
        and _match(task.priority, priority)
        and _match(task.platform, platform)
        and _match(task.project, project)
        and _match(task.collaborator, collaborator)
    ]

    return {
        "total": len(taches),
        "items": [
            task_to_dict(task, VAULT_PATH)
            for task in sort_tasks(taches)
        ],
    }


@app.get("/api/tasks/{note_id}")
def get_task(note_id: str):
    chemin = _ensure_exists(_note_path(note_id))

    try:
        task = vault.read_task(chemin)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error

    donnees = task_to_dict(task, VAULT_PATH)
    donnees["body"] = vault.read_body(chemin)
    donnees["version"] = version_de(chemin)

    return donnees


# =====================================================
# Projets
# =====================================================


@app.get("/api/projects")
def get_projects(status: str | None = None):
    projets = [
        projet
        for projet in repository.get_projects()
        if _match(projet.status, status)
    ]

    taches = repository.get_tasks()

    items = []

    for projet in projets:
        liees = [task for task in taches if belongs_to(task, projet)]

        donnees = project_to_dict(projet, VAULT_PATH)

        donnees["progression"] = progression_to_dict(
            analytics.progression(liees)
        )

        donnees["taches"] = count_tasks(liees).__dict__

        items.append(donnees)

    return {"total": len(items), "items": items}


@app.get("/api/projects/{note_id}")
def get_project(note_id: str):
    chemin = _ensure_exists(_note_path(note_id))

    try:
        projet = vault.read_project(chemin)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error

    taches = repository.get_tasks_for_project(projet)

    donnees = project_to_dict(projet, VAULT_PATH)
    donnees["body"] = vault.read_body(chemin)
    donnees["version"] = version_de(chemin)
    donnees["progression"] = progression_to_dict(
        analytics.progression(taches)
    )
    donnees["taches"] = [
        task_to_dict(task, VAULT_PATH) for task in taches
    ]
    donnees["stats"] = count_tasks(taches).__dict__

    # Collaborateurs cités par les tâches du projet.
    noms = {
        task.collaborator
        for task in taches
        if task.collaborator and task.collaborator.casefold() != "moi"
    }

    donnees["collaborateurs"] = sorted(noms)

    # Les notes du projet, à côté de ses tâches : ce sont les points
    # qu'on ne veut pas perdre sans pour autant en faire un suivi.
    donnees["notes"] = [
        _note_avec_points(note, [projet])
        for note in repository.get_notes_for_project(projet)
        if not note.is_archived
    ]

    return donnees


@app.get("/api/projects/{note_id}/stats")
def get_project_stats(note_id: str):
    chemin = _ensure_exists(_note_path(note_id))

    try:
        projet = vault.read_project(chemin)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error

    taches = repository.get_tasks_for_project(projet)

    # Même règle qu'au tableau de bord : une tâche archivée n'est ni
    # faite ni à faire, elle ne dit rien de l'avancement du projet.
    vivantes = [
        task
        for task in taches
        if (task.status or "").casefold() != "archived"
    ]

    return {
        "progression": progression_to_dict(
            analytics.progression(vivantes)
        ),
        "taches": count_tasks(taches).__dict__,
        "priorites": [
            {"libelle": libelle, "valeur": valeur}
            for libelle, valeur in analytics.repartition_priorites(
                vivantes
            )
        ],
        "statuts": [
            {"libelle": libelle, "valeur": valeur}
            for libelle, valeur in analytics.repartition_statuts(
                vivantes
            )
            if libelle != "Archived"
        ],
    }


# =====================================================
# Collaborateurs
# =====================================================


@app.get("/api/collaborators")
def get_collaborators(status: str | None = None):
    collaborateurs = [
        collaborateur
        for collaborateur in repository.get_collaborators()
        if _match(collaborateur.status, status)
    ]

    taches = repository.get_tasks()

    items = []

    for collaborateur in collaborateurs:
        liees = _tasks_of(collaborateur.name, taches)

        if not liees and collaborateur.filename != collaborateur.name:
            # « parth » est stocké dans ZIPZOP.md, et les tâches
            # citent parfois le nom du fichier plutôt que le nom.
            liees = _tasks_of(collaborateur.filename, taches)

        donnees = collaborator_to_dict(collaborateur, VAULT_PATH)

        donnees["taches"] = len(liees)
        donnees["taches_actives"] = sum(
            1 for task in liees if task.is_open
        )

        items.append(donnees)

    return {"total": len(items), "items": items}


@app.get("/api/collaborators/{note_id}")
def get_collaborator(note_id: str):
    chemin = _ensure_exists(_note_path(note_id))

    try:
        collaborateur = vault.read_collaborator(chemin)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error

    toutes = repository.get_tasks()

    taches = _tasks_of(collaborateur.name, toutes) or _tasks_of(
        collaborateur.filename,
        toutes,
    )

    donnees = collaborator_to_dict(collaborateur, VAULT_PATH)
    donnees["body"] = vault.read_body(chemin)
    donnees["version"] = version_de(chemin)
    donnees["taches"] = [
        task_to_dict(task, VAULT_PATH) for task in sort_tasks(taches)
    ]

    return donnees


# =====================================================
# Connaissances (§16)
# =====================================================


@app.get("/api/knowledge")
def get_connaissances(
    domaine: str | None = None,
    sujet: str | None = None,
    categorie: str | None = None,
    maturite: str | None = None,
    tag: str | None = None,
):
    """La base de connaissances, filtrable sur ses quatre axes.

    Les compteurs qui accompagnent la liste — arborescence,
    catégories, maturités, tags — portent sur la **base entière**,
    jamais sur le résultat filtré. C'est délibéré : des compteurs
    qui rétrécissent avec la sélection finissent par ne plus rien
    proposer, et on ne peut plus changer de filtre sans tout
    remettre à zéro.
    """
    toutes = repository.get_knowledge()

    retenues = connaissances.filtrer(
        toutes,
        VAULT_PATH,
        domaine=domaine,
        sujet=sujet,
        categorie=categorie,
        maturite=maturite,
        tag=tag,
    )

    return {
        "total": len(retenues),
        "total_base": len(toutes),
        "items": [
            knowledge_to_dict(note, VAULT_PATH)
            for note in connaissances.trier(retenues, VAULT_PATH)
        ],
        "arborescence": [
            {
                "domaine": branche.domaine,
                "total": branche.total,
                "sujets": [
                    {"sujet": rameau.sujet, "total": rameau.total}
                    for rameau in branche.sujets
                ],
            }
            for branche in connaissances.arborescence(
                toutes,
                VAULT_PATH,
            )
        ],
        "categories": [
            {"libelle": libelle, "valeur": valeur}
            for libelle, valeur in connaissances.compter(
                toutes,
                connaissances.CATEGORIES,
                "categorie",
            )
        ],
        "maturites": [
            {"libelle": libelle, "valeur": valeur}
            for libelle, valeur in connaissances.compter(
                toutes,
                connaissances.MATURITES,
                "maturite",
            )
        ],
        "tags": [
            {"libelle": libelle, "valeur": valeur}
            for libelle, valeur in connaissances.compter_tags(toutes)
        ],
    }


@app.get("/api/knowledge/{note_id}")
def get_connaissance(note_id: str):
    chemin = _ensure_exists(_note_path(note_id))

    try:
        note = vault.read_knowledge(chemin)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error

    corps = vault.read_body(chemin)

    donnees = knowledge_to_dict(note, VAULT_PATH)
    donnees["body"] = corps
    donnees["version"] = version_de(chemin)

    # Les `[[liens]]` sont la navigation propre à la base de
    # connaissances : on les résout ici pour que l'écran puisse les
    # rendre cliquables au lieu de les afficher en italique.
    index = _index_des_notes(repository._collect_all())

    donnees["liens"] = [
        {"cible": cible, **index[normalize(cible)]}
        for cible in lire_liens(corps)
        if normalize(cible) in index
    ]

    donnees["liens_morts"] = [
        cible
        for cible in lire_liens(corps)
        if normalize(cible) not in index
    ]

    return donnees


# =====================================================
# Notes de projet
# =====================================================


@app.get("/api/notes")
def get_notes(project: str | None = None, archivees: bool = False):
    """Les notes de `07-Notes/`, avec leurs points.

    Les points voyagent avec la liste : une note tient en trois
    cases, et obliger à ouvrir une fiche pour en cocher une
    reviendrait à demander plus de gestes que le Vault lui-même.

    Les notes rangées dans `Archives/` sont écartées par défaut,
    comme le reste de ce qui est archivé dans l'application.
    """
    toutes = repository.get_notes()

    retenues = [
        note
        for note in toutes
        if archivees or not note.is_archived
    ]

    if project:
        retenues = [
            note
            for note in retenues
            if same_reference(note.project, project)
        ]

    retenues.sort(key=lambda note: note.name.casefold())

    projets = repository.get_projects()

    return {
        "total": len(retenues),
        "archivees": sum(1 for note in toutes if note.is_archived),
        "items": [
            _note_avec_points(note, projets) for note in retenues
        ],
    }


@app.get("/api/notes/{note_id}")
def get_note(note_id: str):
    chemin = _ensure_exists(_note_path(note_id))

    try:
        note = vault.read_note(chemin)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error

    donnees = _note_avec_points(note)
    donnees["body"] = vault.read_body(chemin)
    donnees["version"] = version_de(chemin)

    return donnees


# =====================================================
# Journal
# =====================================================


@app.get("/api/journal")
def get_journal(limite: int = 60):
    """Les journées du journal, de la plus récente à la plus ancienne.

    Le fichier, lui, est chronologique : on y écrit à la fin, là où
    `Ctrl + Fin` amène le curseur. C'est l'affichage qui inverse,
    parce qu'un écran montre d'abord ce qui vient de se passer.
    """
    service = JournalService(repository)

    try:
        chemin = service.chemin()
        jours = service.jours()
    except JournalError as error:
        raise HTTPException(404, str(error)) from error

    return {
        "note": chemin.stem,
        "id": encode_id(chemin, VAULT_PATH),
        "version": version_de(chemin),
        "total_jours": len(jours),
        "total_lignes": sum(len(jour.lignes) for jour in jours),
        "jours": [
            {
                "titre": jour.titre,
                "date": jour.date.isoformat() if jour.date else None,
                "lignes": list(jour.lignes),
            }
            for jour in jours[: max(1, min(limite, 400))]
        ],
    }


# =====================================================
# Recherche
# =====================================================


@app.get("/api/search")
def search(q: str = Query("", min_length=0)):
    if not q.strip():
        return {
            "query": q,
            "total": 0,
            "projects": [],
            "tasks": [],
            "collaborators": [],
            "knowledge": [],
            "notes": [],
        }

    resultats = repository.search(q)

    return {
        "query": q,
        "total": resultats.total,
        "projects": [
            project_to_dict(projet, VAULT_PATH)
            for projet in resultats.projects
        ],
        "tasks": [
            task_to_dict(task, VAULT_PATH)
            for task in resultats.tasks
        ],
        "collaborators": [
            collaborator_to_dict(collaborateur, VAULT_PATH)
            for collaborateur in resultats.collaborators
        ],
        "knowledge": [
            knowledge_to_dict(note, VAULT_PATH)
            for note in connaissances.trier(
                resultats.knowledge,
                VAULT_PATH,
            )
        ],
        "notes": [
            note_to_dict(note, VAULT_PATH)
            for note in resultats.notes
        ],
    }


@app.get("/api/activity")
def activite(
    limite: int = 60,
    type: str | None = None,
    genre: str | None = None,
    changements: bool = False,
):
    """Fil des changements, agrégé depuis les notes elles-mêmes (§29).

    Rien n'est stocké : chaque note tient son propre `## Historique`,
    on les relit et on les fusionne. Une entrée effacée à la main
    dans Obsidian disparaît d'ici — c'est une vue, pas un journal
    parallèle.
    """
    contenu = repository._collect_all()

    projets = contenu.projects
    taches = contenu.tasks
    collaborateurs = contenu.collaborators

    lots = [
        (taches, "task"),
        (projets, "project"),
        (collaborateurs, "collaborator"),
    ]

    entrees = []

    for notes, type_note in lots:
        if type and type != type_note:
            continue

        for note in notes:
            try:
                corps = vault.read_body(note.path)
            except (OSError, ValueError):
                # Une note illisible ne doit pas vider tout le fil.
                continue

            entrees.extend(
                historique.lire_entrees(
                    corps,
                    note=note.name,
                    type_note=type_note,
                    chemin=note.path,
                )
            )

    if changements:
        # Les comptes rendus rédigés à la main peuvent faire dix
        # lignes chacun : un seul suffit à enterrer vingt vrais
        # changements. Ce filtre ne garde que ce que l'application
        # a écrit elle-même.
        entrees = [e for e in entrees if e.automatique]

    if genre:
        entrees = [e for e in entrees if e.genre == genre]

    fil = historique.fusionner(entrees)

    # Compteurs par genre, calculés avant la troncature : ils servent
    # à peupler les filtres de l'interface.
    par_genre: dict[str, int] = {}
    for entree in fil:
        par_genre[entree.genre] = par_genre.get(entree.genre, 0) + 1

    return {
        "total": len(fil),
        "par_genre": par_genre,
        "items": [
            {
                "quand": entree.quand.isoformat(),
                "date": entree.date.isoformat(),
                "heure": None
                if entree.jour_seul
                else entree.quand.strftime("%H:%M"),
                "texte": entree.texte,
                "note": entree.note,
                "type": entree.type_note,
                "genre": entree.genre,
                "automatique": entree.automatique,
                "id": encode_id(entree.chemin, VAULT_PATH),
            }
            for entree in fil[: max(1, min(limite, 500))]
        ],
    }


@app.get("/api/graph")
def graphe(
    inclure_terminees: bool = False,
    inclure_connaissances: bool = True,
):
    """Relations entre projets, tâches et collaborateurs (§22, §23).

    Deux sortes de liens, tous deux déduits de champs en texte libre :

    - une tâche appartient à un projet quand son champ `project`
      correspond au nom ou au nom de fichier du projet ;
    - une tâche est confiée à quelqu'un quand son champ
      `collaborator` correspond à une fiche.

    La comparaison est celle du Repository — sans accents, sans
    casse, sans ponctuation. C'est elle qui rattache « AI Video
    Editor » au fichier « AI-Powered Video Editor.md », et « parth »
    à « Me + ZIPZOP ».

    Les tâches archivées ne sont jamais dans le graphe : elles sont
    abandonnées, et leurs liens ne décrivent plus rien. Les terminées
    sont écartées par défaut, mais peuvent être demandées — voir ce
    qu'un projet a produit est un usage légitime de cette vue.

    S'y ajoutent deux types de notes et une troisième sorte de lien.

    Les **notes de projet** se rattachent comme les tâches, par leur
    champ `project` — c'est le seul contrôle simple contre la faute
    de frappe qui détache silencieusement une note de son projet.

    Les **connaissances** se relient par leurs `[[liens]]`, qui sont
    leur navigation propre. Ces liens-là sont lus dans le corps des
    notes, pas dans le frontmatter : c'est le seul endroit où ils
    existent. Les fiches classiques ne sont pas dépouillées de la
    sorte — leurs `[[Alice]]` de courtoisie doubleraient les
    rattachements déjà déduits, sans rien apprendre.
    """
    contenu = repository._collect_all()

    projets = contenu.projects
    collaborateurs = contenu.collaborators

    taches = [
        task
        for task in contenu.tasks
        if (task.status or "").casefold() != "archived"
        and (inclure_terminees or task.is_open)
    ]

    noeuds = []
    liens = []

    for projet in projets:
        liees = [task for task in taches if belongs_to(task, projet)]

        noeuds.append(
            {
                "id": encode_id(projet.path, VAULT_PATH),
                "type": "project",
                "nom": projet.name,
                "statut": projet.status,
                "priorite": projet.priority,
                "poids": len(liees),
            }
        )

    for collaborateur in collaborateurs:
        confiees = _tasks_of(collaborateur.name, taches) or _tasks_of(
            collaborateur.filename,
            taches,
        )

        noeuds.append(
            {
                "id": encode_id(collaborateur.path, VAULT_PATH),
                "type": "collaborator",
                "nom": collaborateur.name,
                "statut": collaborateur.status,
                "priorite": None,
                "poids": len(confiees),
            }
        )

    for task in taches:
        identifiant = encode_id(task.path, VAULT_PATH)

        noeuds.append(
            {
                "id": identifiant,
                "type": "task",
                "nom": task.name,
                "statut": task.status,
                "priorite": task.priority,
                "poids": 1,
            }
        )

        for projet in projets:
            if belongs_to(task, projet):
                liens.append(
                    {
                        "de": identifiant,
                        "vers": encode_id(projet.path, VAULT_PATH),
                        "genre": "projet",
                    }
                )

        for collaborateur in collaborateurs:
            porte = same_reference(
                task.collaborator,
                collaborateur.name,
            ) or same_reference(
                task.collaborator,
                collaborateur.filename,
            )

            if porte:
                liens.append(
                    {
                        "de": identifiant,
                        "vers": encode_id(
                            collaborateur.path,
                            VAULT_PATH,
                        ),
                        "genre": "collaborateur",
                    }
                )

    notes = [
        note for note in contenu.notes if not note.is_archived
    ]

    for note in notes:
        identifiant = encode_id(note.path, VAULT_PATH)

        noeuds.append(
            {
                "id": identifiant,
                "type": "note",
                "nom": note.name,
                "statut": None,
                "priorite": None,
                "poids": 1,
            }
        )

        for projet in projets:
            if belongs_to(note, projet):
                liens.append(
                    {
                        "de": identifiant,
                        "vers": encode_id(projet.path, VAULT_PATH),
                        "genre": "projet",
                    }
                )

    savoirs = contenu.knowledge if inclure_connaissances else []

    for savoir in savoirs:
        noeuds.append(
            {
                "id": encode_id(savoir.path, VAULT_PATH),
                "type": "knowledge",
                "nom": savoir.name,
                "statut": savoir.maturite,
                "priorite": None,
                "poids": 1,
            }
        )

    # Les `[[liens]]` vivent dans le corps des notes : il faut les y
    # lire. Un seul passage, sur les seules notes concernées.
    index = _index_des_notes(contenu)

    for porteuse in [*savoirs, *notes]:
        depart = encode_id(porteuse.path, VAULT_PATH)

        try:
            corps = vault.read_body(porteuse.path)
        except (OSError, ValueError):
            # Une note illisible ne doit pas vider tout le graphe.
            continue

        for cible in lire_liens(corps):
            trouvee = index.get(normalize(cible))

            if trouvee is None or trouvee["id"] == depart:
                continue

            liens.append(
                {
                    "de": depart,
                    "vers": trouvee["id"],
                    "genre": "lien",
                }
            )

    # Un lien vers une note écartée de la vue — tâche terminée,
    # connaissance masquée — ne mène nulle part : on le retire plutôt
    # que de dessiner un trait vers le vide.
    presents = {noeud["id"] for noeud in noeuds}

    liens = [
        lien
        for lien in liens
        if lien["de"] in presents and lien["vers"] in presents
    ]

    # Une connaissance pèse ce que pèsent ses liens : c'est ce qui
    # fait ressortir les notes pivots d'un domaine. Une note isolée
    # pèse donc zéro, et c'est exact — annoncer « 1 lien » sur un
    # nœud dessiné en pointillés se contredirait à l'écran.
    degres: dict[str, int] = {}

    for lien in liens:
        degres[lien["de"]] = degres.get(lien["de"], 0) + 1
        degres[lien["vers"]] = degres.get(lien["vers"], 0) + 1

    for noeud in noeuds:
        if noeud["type"] in ("knowledge", "note"):
            noeud["poids"] = degres.get(noeud["id"], 0)

    # Une note sans aucun lien reste dans le graphe : c'est
    # précisément l'information que la vue doit rendre visible.
    relies = {lien["de"] for lien in liens} | {
        lien["vers"] for lien in liens
    }

    return {
        "noeuds": noeuds,
        "liens": liens,
        "isoles": [
            noeud["id"]
            for noeud in noeuds
            if noeud["id"] not in relies
        ],
    }


@app.get("/api/health")
def health():
    return {
        "vault": str(VAULT_PATH),
        "existe": vault.exists(),
        "notes": len(vault.list_markdown_files())
        if vault.exists()
        else 0,
        "surveillance": surveillant.actif,
        "abonnes": surveillant.nombre_abonnes,
    }


# =====================================================
# Flux d'événements (§28)
# =====================================================

# Sans nouvelle, on envoie un commentaire SSE pour garder la
# connexion en vie : certains intermédiaires coupent une réponse
# inactive, et le navigateur reconnecterait pour rien.
BATTEMENT_SECONDES = 25


@app.get("/api/events")
async def evenements(request: Request):
    """Flux SSE : annonce les changements du Vault au navigateur.

    Le message ne porte que les noms des notes touchées. Le client
    redemande ensuite ce dont il a besoin — l'application n'a pas de
    cache, la donnée fraîche est toujours à un appel d'ici.
    """
    file = surveillant.abonner()

    async def flux():
        try:
            yield "retry: 3000\n\n"
            yield _sse({"type": "pret"})

            while True:
                if await request.is_disconnected():
                    break

                try:
                    message = await asyncio.wait_for(
                        file.get(),
                        timeout=BATTEMENT_SECONDES,
                    )
                except asyncio.TimeoutError:
                    yield ": battement\n\n"
                    continue

                yield _sse(message)
        finally:
            surveillant.desabonner(file)

    return StreamingResponse(
        flux(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Désactive la mise en tampon d'un éventuel proxy.
            "X-Accel-Buffering": "no",
        },
    )


def _sse(donnees: dict) -> str:
    return f"data: {json.dumps(donnees, ensure_ascii=False)}\n\n"


# =====================================================
# Frontend
# =====================================================

class StatiquesSansCache(StaticFiles):
    """Sert les fichiers de l'interface sans les laisser en cache.

    L'application est locale : il n'y a rien à gagner à mettre en
    cache `app.js` ou `style.css`, et beaucoup à perdre — après une
    modification du code, le navigateur continuait de servir
    l'ancienne version, y compris après un rechargement.

    `no-cache` autorise la revalidation : le fichier n'est
    retransmis que s'il a changé.
    """

    def is_not_modified(self, response_headers, request_headers) -> bool:
        response_headers["Cache-Control"] = "no-cache"

        return super().is_not_modified(response_headers, request_headers)

    async def get_response(self, path, scope):
        reponse = await super().get_response(path, scope)

        reponse.headers["Cache-Control"] = "no-cache"

        return reponse


# Monté en dernier : les routes /api ci-dessus sont déclarées avant,
# donc prioritaires. Le reste sert l'interface.
app.mount(
    "/static",
    StatiquesSansCache(directory=WEB_DIR / "static"),
    name="static",
)


@app.get("/{chemin:path}")
def index(chemin: str):
    """Toutes les URL non-API renvoient l'application (§31)."""
    return FileResponse(
        WEB_DIR / "index.html",
        headers={"Cache-Control": "no-cache"},
    )
