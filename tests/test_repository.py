"""Contrôles du Repository sur le VRAI Vault.

Lecture seule. Comme test_vault.py, ces tests vérifient la
cohérence de ce que le Repository renvoie, sans supposer qu'une
note précise se trouve à un endroit précis — le Vault bouge.
"""

import pytest

from core.config import VAULT_PATH
from core.obsidian.repository import ObsidianRepository, sort_tasks
from core.obsidian.vault import ObsidianVault


# Dossier attendu pour chaque couple (type, statut).
DOSSIERS = {
    "task": {
        "active": "05-Tasks/Actives",
        "waiting": "05-Tasks/En attente",
        "completed": "05-Tasks/Terminées",
        "archived": "05-Tasks/Archives",
    },
    "project": {
        "active": "02-Projects/Actifs",
        "waiting": "02-Projects/En attente",
        "completed": "02-Projects/Terminés",
        "archived": "02-Projects/Archives",
    },
    "collaborator": {
        "active": "01-Collaborateurs/Actifs",
        "waiting": "01-Collaborateurs/En attente",
        "completed": "01-Collaborateurs/Terminés",
    },
}


@pytest.fixture
def repository() -> ObsidianRepository:
    return ObsidianRepository(ObsidianVault(VAULT_PATH))


# =====================================================
# Cohérence des données
# =====================================================


def test_statuts_valides(repository: ObsidianRepository):
    """Un statut hors liste casserait le rangement automatique."""
    fautifs = []

    for type_fiche, fiches in (
        ("task", repository.get_tasks()),
        ("project", repository.get_projects()),
        ("collaborator", repository.get_collaborators()),
    ):
        for fiche in fiches:
            if fiche.status not in DOSSIERS[type_fiche]:
                fautifs.append(
                    f"{fiche.path.name} : status={fiche.status!r}"
                )

    assert not fautifs, "statuts invalides :\n" + "\n".join(fautifs)


def test_fiches_rangees_selon_leur_statut(
    repository: ObsidianRepository,
):
    """Le dossier doit correspondre au statut du frontmatter."""
    fautifs = []

    for type_fiche, fiches in (
        ("task", repository.get_tasks()),
        ("project", repository.get_projects()),
        ("collaborator", repository.get_collaborators()),
    ):
        for fiche in fiches:
            attendu = DOSSIERS[type_fiche].get(fiche.status)

            if attendu is None:
                continue

            reel = str(fiche.path.parent.relative_to(VAULT_PATH))

            # `_Inbox` est une exception voulue : une capture rapide
            # est « active » dès sa création, mais reste dans l'Inbox
            # tant que son projet et sa priorité n'ont pas été
            # choisis. C'est ce décalage qui signale qu'elle est à
            # trier — voir Task.is_inbox.
            if reel.endswith("_Inbox"):
                continue

            if reel != attendu:
                fautifs.append(
                    f"{fiche.path.name} : {reel} "
                    f"(attendu {attendu})"
                )

    assert not fautifs, "fiches mal rangées :\n" + "\n".join(fautifs)


def test_pseudos_discord_uniques(
    repository: ObsidianRepository,
):
    """Deux fiches au même pseudo rendraient la recherche ambiguë."""
    vus = {}

    for collaborator in repository.get_collaborators():
        if not collaborator.discord:
            continue

        pseudo = collaborator.discord.casefold()

        assert pseudo not in vus, (
            f"pseudo Discord en double : {collaborator.discord} "
            f"({vus.get(pseudo)} et {collaborator.name})"
        )

        vus[pseudo] = collaborator.name


# =====================================================
# Comportement du Repository
# =====================================================


def test_filtrage_par_statut(repository: ObsidianRepository):
    for status in ("active", "waiting", "completed", "archived"):
        for task in repository.get_tasks_by_status(status):
            assert task.status == status


def test_taches_ouvertes(repository: ObsidianRepository):
    open_tasks = repository.get_open_tasks()

    assert all(task.is_open for task in open_tasks)
    assert all(
        task.status not in ("completed", "archived")
        for task in open_tasks
    )


def test_tri_stable(repository: ObsidianRepository):
    tasks = repository.get_tasks()

    assert sort_tasks(tasks) == sort_tasks(sort_tasks(tasks))


def test_recherche_retrouve_une_fiche_existante(
    repository: ObsidianRepository,
):
    """On cherche une fiche réelle, quelle qu'elle soit."""
    tasks = repository.get_tasks()

    if not tasks:
        pytest.skip("aucune tâche dans le Vault")

    cible = tasks[0]

    assert repository.find_task(cible.name) is not None
    assert cible.name in [
        task.name
        for task in repository.search(cible.name).tasks
    ]


def test_recherche_par_pseudo_discord(
    repository: ObsidianRepository,
):
    avec_discord = [
        collaborator
        for collaborator in repository.get_collaborators()
        if collaborator.discord
    ]

    if not avec_discord:
        pytest.skip("aucun collaborateur avec pseudo Discord")

    cible = avec_discord[0]

    trouve = repository.find_collaborator_by_discord(cible.discord)

    assert trouve is not None
    assert trouve.name == cible.name


def test_rattachement_des_taches_aux_projets(
    repository: ObsidianRepository,
):
    """Une tâche rattachée doit citer le projet correspondant."""
    for project in repository.get_projects():
        for task in repository.get_tasks_for_project(project):
            assert task.project, (
                f"{task.name} rattachée à {project.name} sans "
                "champ project"
            )
