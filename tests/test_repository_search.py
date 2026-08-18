"""Filtres, recherche ciblée et recherche transversale."""

from core.obsidian.repository import (
    ObsidianRepository,
    count_projects,
    count_tasks,
    priority_rank,
    sort_tasks,
)
from core.obsidian.writer import VaultWriter
from core.services.tasks import TaskService
from core.utils.text import contains, normalize


# =====================================================
# Utilitaire de texte
# =====================================================


def test_normalisation_accents_et_casse():
    assert normalize("Créer bot Discord") == "creer bot discord"
    assert normalize("  Terminées  ") == "terminees"
    assert normalize(None) == ""


def test_contains_ignore_accents():
    assert contains("Créer bot discord + serv", "creer bot")
    assert contains("Tâche terminée", "TERMINEE")
    assert not contains("Projet Alpha", "beta")
    assert not contains("Projet Alpha", "")


# =====================================================
# Listes et filtres
# =====================================================


def test_get_tasks(temp_repository: ObsidianRepository):
    tasks = temp_repository.get_tasks()

    assert len(tasks) == 5


def test_get_open_tasks_exclut_terminees(
    temp_repository: ObsidianRepository,
):
    open_tasks = temp_repository.get_open_tasks()

    names = [task.name for task in open_tasks]

    assert "Tache terminee" not in names
    assert "Tache complete" in names
    assert all(task.is_open for task in open_tasks)


def test_get_open_tasks_trie_par_priorite(
    temp_repository: ObsidianRepository,
):
    open_tasks = temp_repository.get_open_tasks()

    priorities = [task.priority for task in open_tasks]

    # critical, puis high, puis low, puis la tâche sans priorité
    assert priorities == [
        "critical",
        "high",
        "low",
        None,
    ]


def test_get_tasks_by_status(
    temp_repository: ObsidianRepository,
):
    actives = temp_repository.get_tasks_by_status("active")

    assert len(actives) == 2
    assert all(task.status == "active" for task in actives)


def test_get_projects_by_status(
    temp_repository: ObsidianRepository,
):
    assert len(temp_repository.get_projects_by_status("active")) == 1
    assert temp_repository.get_projects_by_status("archived") == []


# =====================================================
# Recherche ciblée
# =====================================================


def test_find_task_exact(temp_repository: ObsidianRepository):
    task = temp_repository.find_task("Tache complete")

    assert task is not None
    assert task.priority == "critical"


def test_find_task_partiel(temp_repository: ObsidianRepository):
    task = temp_repository.find_task("minimale")

    assert task is not None
    assert task.name == "Tache minimale"


def test_find_task_sans_accents(
    temp_repository: ObsidianRepository,
):
    task = temp_repository.find_task("creer bot")

    assert task is not None
    assert task.name == "Créer bot Discord"


def test_find_task_ambigu_renvoie_none(
    temp_repository: ObsidianRepository,
):
    """Face à plusieurs candidats, ne rien renvoyer.

    Mieux vaut demander de préciser que d'agir sur la mauvaise
    tâche — ce qui compte quand la commande écrira dans le Vault.
    """
    assert temp_repository.find_task("tache") is None

    candidats = temp_repository.find_matching_tasks("tache")

    assert len(candidats) > 1


def test_find_task_introuvable(
    temp_repository: ObsidianRepository,
):
    assert temp_repository.find_task("inexistante") is None


def test_find_project_par_nom_et_par_fichier(
    temp_repository: ObsidianRepository,
):
    assert temp_repository.find_project("Projet Alpha") is not None
    assert temp_repository.find_project("alpha") is not None


def test_find_collaborator(
    temp_repository: ObsidianRepository,
):
    collaborator = temp_repository.find_collaborator("alice")

    assert collaborator is not None
    assert collaborator.role == "Developpeuse"


def test_find_collaborator_by_discord(
    temp_repository: ObsidianRepository,
):
    collaborator = temp_repository.find_collaborator_by_discord(
        "alice#0001"
    )

    assert collaborator is not None
    assert collaborator.name == "Alice"


def test_tasks_for_project(
    temp_repository: ObsidianRepository,
):
    project = temp_repository.find_project("Projet Alpha")

    assert project is not None

    tasks = temp_repository.get_tasks_for_project(project)

    names = [task.name for task in tasks]

    assert "Tache complete" in names
    assert "Créer bot Discord" in names
    assert "Tache attente" not in names


def test_normalisation_ponctuation():
    """Les variations de saisie du vrai Vault doivent se rejoindre."""
    assert normalize("AI-powered video editor") == normalize(
        "AI-Powered Video Editor"
    )
    assert normalize("DB templates web") == normalize(
        "DB_templates-web"
    )
    assert normalize("Créer bot discord + serv") == (
        "creer bot discord serv"
    )


# =====================================================
# Recherche transversale
# =====================================================


def test_search_trouve_dans_les_trois_types(
    temp_repository: ObsidianRepository,
):
    results = temp_repository.search("alpha")

    assert [p.name for p in results.projects] == ["Projet Alpha"]
    assert [t.name for t in results.tasks] != []
    assert results.total > 0
    assert not results.is_empty


def test_search_sur_collaborateur(
    temp_repository: ObsidianRepository,
):
    results = temp_repository.search("developpeuse")

    assert [c.name for c in results.collaborators] == ["Alice"]


def test_search_sur_plateforme(
    temp_repository: ObsidianRepository,
):
    results = temp_repository.search("discord")

    assert [t.name for t in results.tasks] == ["Créer bot Discord"]


def test_search_vide(temp_repository: ObsidianRepository):
    results = temp_repository.search("zzzzz")

    assert results.is_empty
    assert results.total == 0


def test_search_ne_plante_pas_sur_fichier_illisible(
    temp_repository: ObsidianRepository,
):
    """Le Vault de test contient un template Templater non-YAML."""
    results = temp_repository.search("task")

    assert isinstance(results.total, int)


# =====================================================
# Tri
# =====================================================


def test_priority_rank():
    assert priority_rank("critical") < priority_rank("high")
    assert priority_rank("high") < priority_rank("medium")
    assert priority_rank("medium") < priority_rank("low")
    assert priority_rank(None) > priority_rank("low")
    assert priority_rank("inconnue") > priority_rank("low")


def test_sort_tasks_priorite_puis_echeance(
    temp_repository: ObsidianRepository,
):
    tasks = sort_tasks(temp_repository.get_tasks())

    assert tasks[0].priority == "critical"
    assert tasks[-1].priority is None


# =====================================================
# Compteurs
# =====================================================


def test_compteurs_du_vault_de_test(temp_repository):
    stats = count_tasks(temp_repository.get_tasks())

    assert stats.total == 5

    # Terminée et archivée exclues ; la tâche sans statut compte
    # comme ouverte, le bot ne doit pas la perdre de vue.
    assert stats.open == 4
    assert stats.waiting == 1
    assert stats.completed == 1
    assert stats.archived == 0


def test_urgentes_seulement_parmi_les_ouvertes(temp_repository):
    """Une tâche critique déjà terminée n'alerte plus."""
    stats = count_tasks(temp_repository.get_tasks())

    # « Tache complete » (critical) et « Créer bot Discord » (high).
    assert stats.urgent == 2

    service = TaskService(
        temp_repository,
        VaultWriter(temp_repository.vault),
    )

    service.change_status("Tache complete", "completed")

    apres = count_tasks(temp_repository.get_tasks())

    assert apres.urgent == 1
    assert apres.open == 3
    assert apres.completed == 2


def test_compteurs_sur_liste_vide():
    stats = count_tasks([])

    assert stats.total == 0
    assert stats.open == 0
    assert stats.urgent == 0


# =====================================================
# Vue d'ensemble
# =====================================================


def test_compteurs_de_projets(temp_repository):
    stats = count_projects(temp_repository.get_projects())

    assert stats.total == 1
    assert stats.active == 1
    assert stats.waiting == 0
    assert stats.completed == 0


def test_projet_au_statut_inconnu_compte_dans_le_total():
    """Un statut hors nomenclature ne doit pas disparaître."""
    from pathlib import Path

    from core.obsidian.models import Project

    projets = [
        Project(
            path=Path("/tmp/X.md"),
            type="project",
            status="bizarre",
            name="X",
            category=None,
            priority=None,
            created=None,
            deadline=None,
            repository=None,
        )
    ]

    stats = count_projects(projets)

    assert stats.total == 1
    assert stats.active == 0


def test_workspace_reunit_les_deux_familles(temp_repository):
    workspace = temp_repository.workspace()

    assert workspace.projects.active == 1
    assert workspace.tasks.open == 4
    assert workspace.tasks.urgent == 2


def test_le_compteur_urgent_correspond_a_la_liste(temp_repository):
    """Annoncer « 2 urgentes » puis en lister trois serait un bug."""
    workspace = temp_repository.workspace()

    assert workspace.tasks.urgent == len(workspace.urgent)


def test_urgentes_triees_par_priorite(temp_repository):
    workspace = temp_repository.workspace()

    priorites = [task.priority for task in workspace.urgent]

    assert priorites == ["critical", "high"]


def test_une_urgente_terminee_sort_de_la_liste(temp_repository):
    service = TaskService(
        temp_repository,
        VaultWriter(temp_repository.vault),
    )

    service.change_status("Tache complete", "completed")

    workspace = temp_repository.workspace()

    assert workspace.tasks.urgent == 1
    assert [task.name for task in workspace.urgent] == [
        "Créer bot Discord"
    ]
