"""Routes d'écriture.

Toutes passent par les services du cœur métier, donc par le
`VaultWriter` : édition ligne par ligne, écriture atomique,
relecture, restauration en cas d'anomalie.

Deux règles propres à la web app.

**Rien ne se supprime.** `DELETE` archive : la note passe en
`archived` et rejoint le dossier `Archives`. Le Vault est la source
de vérité, un bouton dans un navigateur ne doit pas pouvoir effacer
un fichier de façon irréversible.

**Les écritures concurrentes sont détectées.** Obsidian est souvent
ouvert pendant que l'application tourne. Chaque note expose une
`version` (sa date de modification) ; si le client la renvoie et
qu'elle a changé entre-temps, l'écriture est refusée avec un 409
plutôt que d'écraser silencieusement ce qui vient d'être tapé dans
Obsidian.
"""

import datetime
import logging
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from core.config import SOURCE_LABEL  # noqa: F401  (réglage exposé)
from core.obsidian.models import Collaborator, Project, Task
from core.obsidian.writer import VaultWriteError
from core.services.collaborators import (
    CollaboratorError,
    CollaboratorService,
)
from core.services.connaissances import CATEGORIES, MATURITES
from core.services.journal import JournalError, JournalService
from core.services.notes import NoteError, NoteService
from core.services.notes_projet import (
    NoteProjetError,
    NoteProjetService,
    points,
)
from core.services.projects import ProjectError, ProjectService
from core.utils.text import normalize
from core.services.tasks import (
    STATUS_FOLDERS,
    TaskError,
    TaskService,
    VALID_PLATFORMS,
    VALID_PRIORITIES,
    VALID_STATUSES,
    DEADLINE_OFFSETS,
)


logger = logging.getLogger(__name__)


router = APIRouter()


# Statut qui remplace la suppression, et son dossier.
ARCHIVE_STATUS = "archived"

# Les collaborateurs n'ont pas de dossier Archives : trois statuts
# seulement, c'est la convention du Vault.
COLLABORATOR_STATUSES = ("active", "waiting", "completed")


# =====================================================
# Accès au contexte
# =====================================================


def _contexte():
    """Objets de l'application, relus à chaque appel.

    `api.app` remplace `vault` et `repository` pendant les tests :
    les lire au moment de l'appel plutôt qu'à l'import garantit que
    les routes travaillent bien sur le Vault temporaire.
    """
    from api import app as module

    return module.vault, module.repository, module.VAULT_PATH


def _services():
    vault, repository, _ = _contexte()

    from core.obsidian.writer import VaultWriter

    writer = VaultWriter(vault)

    taches = TaskService(repository, writer)
    projets = ProjectService(repository, writer)
    collaborateurs = CollaboratorService(repository, writer)

    notes = NoteService(
        repository,
        writer,
        taches,
        projets,
        collaborateurs,
    )

    return taches, projets, collaborateurs, notes


def _service_journal() -> JournalService:
    """Le journal a son propre service : il ne partage rien avec les
    trois fiches, ni tableau à synchroniser, ni historique à tenir."""
    vault, repository, _ = _contexte()

    from core.obsidian.writer import VaultWriter

    return JournalService(repository, VaultWriter(vault))


def _service_notes_projet() -> NoteProjetService:
    vault, repository, _ = _contexte()

    from core.obsidian.writer import VaultWriter

    return NoteProjetService(repository, VaultWriter(vault))


def _resoudre(note_id: str, lecteur):
    """Identifiant → modèle, ou 404."""
    from api.app import _ensure_exists, _note_path

    chemin = _ensure_exists(_note_path(note_id))

    try:
        return lecteur(chemin)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error


def version_de(path: Path) -> float:
    """Date de modification, utilisée comme numéro de version."""
    return round(path.stat().st_mtime, 3)


def _verifier_version(path: Path, version_attendue: float | None) -> None:
    """Refuse d'écrire si la note a bougé depuis sa lecture.

    Sans ce contrôle, enregistrer un formulaire ouvert depuis dix
    minutes écraserait sans prévenir ce qui a été écrit dans
    Obsidian entre-temps.
    """
    if version_attendue is None:
        return

    actuelle = version_de(path)

    # Tolérance d'une seconde : les systèmes de fichiers n'ont pas
    # tous la même résolution sur les dates de modification.
    if abs(actuelle - version_attendue) > 1.0:
        raise HTTPException(
            409,
            "La note a été modifiée ailleurs (probablement dans "
            "Obsidian) depuis son affichage. Recharge la page pour "
            "voir la version actuelle avant de réessayer.",
        )


def inchange(actuel: str | None, demande) -> bool:
    """La valeur demandée est-elle déjà en place ?

    Les services refusent de « changer » un champ vers sa valeur
    actuelle : venant d'une commande Discord, la remarque était
    utile. Depuis un formulaire web, elle est nuisible — le
    navigateur renvoie tous les champs, y compris ceux que
    l'utilisateur n'a pas touchés, et une seule valeur inchangée
    ferait échouer l'enregistrement complet.

    Ces champs-là sont donc simplement sautés.
    """
    if demande is None:
        return actuel is None

    return (actuel or "").strip().casefold() == str(
        demande
    ).strip().casefold()


def _erreurs(fonction):
    """Traduit les exceptions du cœur métier en réponses HTTP."""
    try:
        return fonction()
    except (
        TaskError,
        ProjectError,
        CollaboratorError,
        NoteError,
        NoteProjetError,
        JournalError,
    ) as error:
        raise HTTPException(400, str(error)) from error
    except VaultWriteError as error:
        raise HTTPException(500, str(error)) from error


# =====================================================
# Métadonnées des formulaires
# =====================================================


@router.get("/api/meta")
def meta():
    """Valeurs acceptées, pour que le frontend ne les invente pas."""
    _, repository, _ = _contexte()

    contenu = repository._collect_all()

    projects = contenu.projects
    tasks = contenu.tasks
    collaborators = contenu.collaborators

    return {
        "statuts": list(VALID_STATUSES),
        "statuts_collaborateur": list(COLLABORATOR_STATUSES),
        "priorites": list(VALID_PRIORITIES),
        "plateformes": list(VALID_PLATFORMS),
        "delais": list(DEADLINE_OFFSETS),
        "dossiers": STATUS_FOLDERS,
        # Axes de la base de connaissances. L'interface ne les
        # invente pas : ils viennent du template Templater, et les
        # deux doivent proposer exactement les mêmes valeurs.
        "categories": list(CATEGORIES),
        "maturites": list(MATURITES),
        "projets": sorted(projet.name for projet in projects),
        "collaborateurs": sorted(
            collaborateur.name for collaborateur in collaborators
        ),
        # Valeurs déjà présentes dans les tâches : le champ est
        # libre, autant proposer ce qui existe.
        "projets_cites": sorted(
            {task.project for task in tasks if task.project}
        ),
        "collaborateurs_cites": sorted(
            {task.collaborator for task in tasks if task.collaborator}
        ),
    }


# =====================================================
# Tâches
# =====================================================


@router.post("/api/tasks", status_code=201)
def creer_tache(corps: dict = Body(...)):
    from api.schemas import encode_id, task_to_dict

    taches, _, _, _ = _services()
    _, _, vault_path = _contexte()

    titre = (corps.get("title") or "").strip()

    if not titre:
        raise HTTPException(400, "Le nom de la tâche est obligatoire.")

    def action():
        return taches.create_task(
            title=titre,
            status=corps.get("status", "active"),
            priority=corps.get("priority", "medium"),
            platform=corps.get("platform", "Autre"),
            project=corps.get("project", "") or "",
            collaborator=corps.get("collaborator", "Moi") or "Moi",
            deadline_label=corps.get("deadline", "7j"),
            objectif=corps.get("objectif", "") or "",
            dossier=corps.get("dossier"),
        )

    tache = _erreurs(action)

    donnees = task_to_dict(tache, vault_path)
    donnees["version"] = version_de(tache.path)

    logger.info("Tâche créée via l'API : %s", tache.name)

    return donnees


@router.post("/api/tasks/capture", status_code=201)
def capturer(corps: dict = Body(...)):
    """Capture rapide : un titre, rien d'autre à décider (§19)."""
    from api.schemas import task_to_dict

    taches, _, _, _ = _services()
    _, _, vault_path = _contexte()

    titre = (corps.get("title") or "").strip()

    if not titre:
        raise HTTPException(400, "Le nom de la tâche est obligatoire.")

    tache = _erreurs(
        lambda: taches.capture(titre, corps.get("detail", "") or "")
    )

    donnees = task_to_dict(tache, vault_path)
    donnees["version"] = version_de(tache.path)

    return donnees


# Champs modifiables par PATCH, et le service qui s'en charge.
CHAMPS_LIBRES_TACHE = (
    "platform",
    "project",
    "collaborator",
)


@router.patch("/api/tasks/{note_id}")
def modifier_tache(note_id: str, corps: dict = Body(...)):
    from api.schemas import task_to_dict

    vault, repository, vault_path = _contexte()
    taches, _, _, _ = _services()

    tache: Task = _resoudre(note_id, vault.read_task)

    _verifier_version(tache.path, corps.get("version"))

    avertissements: list[str] = []
    chemin = tache.path

    def rafraichir() -> Task:
        return vault.read_task(chemin)

    # L'ordre compte : le changement de statut déplace le fichier,
    # donc il passe en dernier pour que les autres écritures visent
    # encore le bon chemin.
    if "priority" in corps and not inchange(
        tache.priority,
        corps["priority"],
    ):
        resultat = _erreurs(
            lambda: taches.change_priority(
                rafraichir(),
                corps["priority"],
            )
        )
        avertissements += resultat.warnings

    for champ in CHAMPS_LIBRES_TACHE:
        if champ not in corps:
            continue

        if inchange(getattr(tache, champ, None), corps[champ]):
            continue

        resultat = _erreurs(
            lambda champ=champ: taches.set_field(
                rafraichir(),
                champ,
                corps[champ] or "",
            )
        )
        avertissements += resultat.warnings

    if "deadline" in corps and not inchange(
        tache.deadline,
        corps["deadline"],
    ):
        resultat = _erreurs(
            lambda: taches.set_deadline(
                rafraichir(),
                corps["deadline"],
            )
        )
        avertissements += resultat.warnings

    # `due_date` vient du calendrier : une date précise, dont le
    # libellé de délai est déduit. `deadline` fait l'inverse.
    if "due_date" in corps and corps["due_date"]:
        resultat = _erreurs(
            lambda: taches.set_due_date(
                rafraichir(),
                corps["due_date"],
            )
        )
        avertissements += resultat.warnings

    if "status" in corps and not inchange(
        tache.status,
        corps["status"],
    ):
        resultat = _erreurs(
            lambda: taches.change_status(
                rafraichir(),
                corps["status"],
            )
        )
        avertissements += resultat.warnings
        chemin = resultat.task.path

    finale = vault.read_task(chemin)

    donnees = task_to_dict(finale, vault_path)
    donnees["version"] = version_de(chemin)
    donnees["avertissements"] = avertissements

    return donnees


@router.delete("/api/tasks/{note_id}")
def archiver_tache(note_id: str, version: float | None = None):
    """Archive la tâche. Ne supprime jamais le fichier."""
    from api.schemas import task_to_dict

    vault, _, vault_path = _contexte()
    taches, _, _, _ = _services()

    tache: Task = _resoudre(note_id, vault.read_task)

    _verifier_version(tache.path, version)

    if tache.status == ARCHIVE_STATUS:
        raise HTTPException(400, "Cette tâche est déjà archivée.")

    resultat = _erreurs(
        lambda: taches.change_status(tache, ARCHIVE_STATUS)
    )

    logger.info("Tâche archivée via l'API : %s", tache.name)

    donnees = task_to_dict(resultat.task, vault_path)
    donnees["version"] = version_de(resultat.task.path)
    donnees["archivee"] = True

    return donnees


# =====================================================
# Projets
# =====================================================


@router.post("/api/projects", status_code=201)
def creer_projet(corps: dict = Body(...)):
    from api.schemas import project_to_dict

    _, projets, _, _ = _services()
    _, _, vault_path = _contexte()

    nom = (corps.get("name") or "").strip()

    if not nom:
        raise HTTPException(400, "Le nom du projet est obligatoire.")

    projet = _erreurs(
        lambda: projets.create_project(
            name=nom,
            status=corps.get("status", "active"),
            priority=corps.get("priority", "medium"),
            category=corps.get("category", "") or "",
            deadline=corps.get("deadline", "") or "",
            repository=corps.get("repository", "") or "",
        )
    )

    donnees = project_to_dict(projet, vault_path)
    donnees["version"] = version_de(projet.path)

    logger.info("Projet créé via l'API : %s", projet.name)

    return donnees


CHAMPS_LIBRES_PROJET = ("category", "deadline", "repository")


@router.patch("/api/projects/{note_id}")
def modifier_projet(note_id: str, corps: dict = Body(...)):
    from api.schemas import project_to_dict

    vault, _, vault_path = _contexte()
    _, projets, _, _ = _services()

    projet: Project = _resoudre(note_id, vault.read_project)

    _verifier_version(projet.path, corps.get("version"))

    avertissements: list[str] = []
    chemin = projet.path

    def rafraichir() -> Project:
        return vault.read_project(chemin)

    if "priority" in corps and not inchange(
        projet.priority,
        corps["priority"],
    ):
        resultat = _erreurs(
            lambda: projets.change_priority(
                rafraichir(),
                corps["priority"],
            )
        )
        avertissements += resultat.warnings

    for champ in CHAMPS_LIBRES_PROJET:
        if champ not in corps:
            continue

        if inchange(getattr(projet, champ, None), corps[champ]):
            continue

        resultat = _erreurs(
            lambda champ=champ: projets.set_field(
                rafraichir(),
                champ,
                corps[champ] or "",
            )
        )
        avertissements += resultat.warnings

    if "status" in corps and not inchange(
        projet.status,
        corps["status"],
    ):
        resultat = _erreurs(
            lambda: projets.change_status(
                rafraichir(),
                corps["status"],
            )
        )
        avertissements += resultat.warnings
        chemin = resultat.project.path

    finale = vault.read_project(chemin)

    donnees = project_to_dict(finale, vault_path)
    donnees["version"] = version_de(chemin)
    donnees["avertissements"] = avertissements

    return donnees


@router.delete("/api/projects/{note_id}")
def archiver_projet(note_id: str, version: float | None = None):
    """Archive le projet. Ne supprime jamais le fichier."""
    from api.schemas import project_to_dict

    vault, _, vault_path = _contexte()
    _, projets, _, _ = _services()

    projet: Project = _resoudre(note_id, vault.read_project)

    _verifier_version(projet.path, version)

    if projet.status == ARCHIVE_STATUS:
        raise HTTPException(400, "Ce projet est déjà archivé.")

    resultat = _erreurs(
        lambda: projets.change_status(projet, ARCHIVE_STATUS)
    )

    logger.info("Projet archivé via l'API : %s", projet.name)

    donnees = project_to_dict(resultat.project, vault_path)
    donnees["version"] = version_de(resultat.project.path)
    donnees["archivee"] = True

    return donnees


# =====================================================
# Collaborateurs
# =====================================================


@router.post("/api/collaborators", status_code=201)
def creer_collaborateur(corps: dict = Body(...)):
    from api.schemas import collaborator_to_dict

    _, _, collaborateurs, _ = _services()
    _, _, vault_path = _contexte()

    nom = (corps.get("name") or "").strip()

    if not nom:
        raise HTTPException(400, "Le nom est obligatoire.")

    fiche = _erreurs(
        lambda: collaborateurs.create_collaborator(
            name=nom,
            status=corps.get("status", "active"),
            role=corps.get("role", "") or "",
            company=corps.get("company", "") or "",
            discord=corps.get("discord", "") or "",
            email=corps.get("email", "") or "",
            github=corps.get("github", "") or "",
        )
    )

    donnees = collaborator_to_dict(fiche, vault_path)
    donnees["version"] = version_de(fiche.path)

    return donnees


CHAMPS_LIBRES_COLLABORATEUR = (
    "role",
    "company",
    "discord",
    "email",
    "github",
    "website",
    "timezone",
)


@router.patch("/api/collaborators/{note_id}")
def modifier_collaborateur(note_id: str, corps: dict = Body(...)):
    from api.schemas import collaborator_to_dict

    vault, _, vault_path = _contexte()
    _, _, collaborateurs, _ = _services()

    fiche: Collaborator = _resoudre(note_id, vault.read_collaborator)

    _verifier_version(fiche.path, corps.get("version"))

    avertissements: list[str] = []
    chemin = fiche.path

    def rafraichir() -> Collaborator:
        return vault.read_collaborator(chemin)

    for champ in CHAMPS_LIBRES_COLLABORATEUR:
        if champ not in corps:
            continue

        if inchange(getattr(fiche, champ, None), corps[champ]):
            continue

        resultat = _erreurs(
            lambda champ=champ: collaborateurs.set_field(
                rafraichir(),
                champ,
                corps[champ] or "",
            )
        )
        avertissements += resultat.warnings

    if "status" in corps and not inchange(
        fiche.status,
        corps["status"],
    ):
        if corps["status"] not in COLLABORATOR_STATUSES:
            raise HTTPException(
                400,
                "Un collaborateur n'a que trois statuts : "
                + ", ".join(COLLABORATOR_STATUSES)
                + ".",
            )

        resultat = _erreurs(
            lambda: collaborateurs.change_status(
                rafraichir(),
                corps["status"],
            )
        )
        avertissements += resultat.warnings
        chemin = resultat.collaborator.path

    finale = vault.read_collaborator(chemin)

    donnees = collaborator_to_dict(finale, vault_path)
    donnees["version"] = version_de(chemin)
    donnees["avertissements"] = avertissements

    return donnees


# =====================================================
# Notes libres
# =====================================================

TYPES_DE_NOTE = {
    "task": "task",
    "tasks": "task",
    "project": "project",
    "projects": "project",
    "collaborator": "collab",
    "collaborators": "collab",
}


@router.post("/api/{genre}/{note_id}/notes", status_code=201)
def ajouter_note(genre: str, note_id: str, corps: dict = Body(...)):
    """Ajoute un texte sous « ## Notes » de la fiche visée.

    L'historique n'est pas touché : il est réservé au journal
    automatique, comme dans le Vault.
    """
    vault, _, _ = _contexte()
    _, _, _, notes = _services()

    kind = TYPES_DE_NOTE.get(genre)

    if kind is None:
        raise HTTPException(404, f"Type inconnu : {genre}")

    texte = (corps.get("text") or "").strip()

    if not texte:
        raise HTTPException(400, "Le texte de la note est vide.")

    lecteurs = {
        "task": vault.read_task,
        "project": vault.read_project,
        "collab": vault.read_collaborator,
    }

    cible = _resoudre(note_id, lecteurs[kind])

    _verifier_version(cible.path, corps.get("version"))

    # `author` s'ajoute à la signature, qui mentionne déjà la source :
    # le renseigner par défaut donnerait « depuis la web app — depuis
    # la web app ».
    resultat = _erreurs(
        lambda: notes.add_note(
            kind,
            cible,
            texte,
            author=corps.get("author") or "",
        )
    )

    return {
        "ok": True,
        "cible": getattr(resultat, "name", cible.name),
        "version": version_de(cible.path),
    }


# =====================================================
# Journal
# =====================================================


@router.post("/api/journal", status_code=201)
def capturer_dans_le_journal(corps: dict = Body(...)):
    """Ajoute une ligne à la journée en cours (§19, capture rapide).

    Aucun champ à choisir, aucun dossier à décider : c'est tout
    l'intérêt du journal, et l'API ne demande donc qu'un texte. La
    journée est ouverte à la fin du fichier si elle n'existe pas
    encore, comme le fait le gabarit dans Obsidian.
    """
    texte = (corps.get("text") or "").strip()

    if not texte:
        raise HTTPException(400, "La ligne est vide.")

    service = _service_journal()

    ligne = _erreurs(lambda: service.capturer(texte))

    logger.info("Ligne ajoutée au journal via l'API.")

    return {
        "ok": True,
        "ligne": ligne,
        "jour": datetime.date.today().isoformat(),
    }


# =====================================================
# Points d'une note de projet
# =====================================================


@router.patch("/api/notes/{note_id}/points/{index}")
def basculer_un_point(
    note_id: str,
    index: int,
    corps: dict = Body(...),
):
    """Coche ou décoche un point d'une note.

    Le client renvoie le libellé qu'il affichait. S'il ne correspond
    plus, on répond 409 plutôt que de cocher la mauvaise ligne : une
    note réorganisée dans Obsidian décale ses points, et rien ne le
    signalerait autrement.
    """
    from api.app import _note_avec_points

    vault, _, _ = _contexte()

    note = _resoudre(note_id, vault.read_note)

    _verifier_version(note.path, corps.get("version"))

    cases = points(vault.read_body(note.path))

    if not 0 <= index < len(cases):
        raise HTTPException(
            404,
            f"Cette note n'a pas de point n°{index + 1} : "
            f"elle en compte {len(cases)}.",
        )

    attendu = corps.get("texte")

    if attendu is not None and normalize(cases[index].texte) != normalize(
        attendu
    ):
        raise HTTPException(
            409,
            "Ce point ne dit plus la même chose qu'à l'affichage "
            f"(« {cases[index].texte} »). Recharge la page pour voir "
            "la version actuelle avant de réessayer.",
        )

    cochee = bool(corps.get("cochee", True))

    service = _service_notes_projet()

    _, avertissements = _erreurs(
        lambda: service.basculer(
            note,
            index,
            cochee,
            texte_attendu=attendu,
        )
    )

    donnees = _note_avec_points(vault.read_note(note.path))
    donnees["version"] = version_de(note.path)
    donnees["avertissements"] = avertissements

    return donnees
