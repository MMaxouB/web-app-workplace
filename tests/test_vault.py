"""Contrôles de bon fonctionnement sur le VRAI Vault.

Lecture seule, et volontairement peu exigeants : le Vault évolue
au fil du travail, une note change de dossier ou de nom. Ces
tests vérifient donc que le Vault reste *lisible*, pas qu'il
contienne telle donnée à tel endroit.

Les garanties de comportement sont couvertes par les tests sur
Vault temporaire (voir conftest.py).
"""

import pytest

from core.config import VAULT_PATH
from core.obsidian.repository import ObsidianRepository
from core.obsidian.vault import ObsidianVault


TYPES_CONNUS = ("task", "project", "collaborator")

# Types présents dans le Vault que l'application ne lit pas encore.
# Ils sont légitimes — leurs conventions sont écrites dans
# 03-Documentation — mais rien ne les affiche pour l'instant. Les
# retirer de cette liste au fur et à mesure qu'ils sont branchés :
# le test redeviendra alors un vrai garde-fou pour eux.
TYPES_PAS_ENCORE_LUS = ("documentation", "knowledge", "note", "journal")


@pytest.fixture
def vault() -> ObsidianVault:
    return ObsidianVault(VAULT_PATH)


@pytest.fixture
def repository(vault: ObsidianVault) -> ObsidianRepository:
    return ObsidianRepository(vault)


def test_vault_exists(vault: ObsidianVault):
    assert vault.exists()


def test_vault_contains_markdown_files(vault: ObsidianVault):
    files = vault.list_markdown_files()

    assert files
    assert all(file.suffix == ".md" for file in files)


def test_aucun_fichier_ne_fait_planter_la_lecture(
    vault: ObsidianVault,
):
    """Un fichier illisible doit être ignoré, pas propager d'erreur."""
    for file_path in vault.list_markdown_files():
        vault.safe_read_frontmatter(file_path)


def test_toutes_les_fiches_se_construisent(
    vault: ObsidianVault,
    repository: ObsidianRepository,
):
    """Chaque note typée doit produire un modèle exploitable."""
    for project in repository.get_projects():
        assert project.name
        assert project.status

    for collaborator in repository.get_collaborators():
        assert collaborator.name
        assert collaborator.status

    for task in repository.get_tasks():
        assert task.name
        assert task.status


def test_les_dates_sont_normalisees(
    repository: ObsidianRepository,
):
    """PyYAML renvoie des objets date : les modèles veulent des chaînes."""
    for task in repository.get_tasks():
        for valeur in (task.created, task.due, task.completed):
            assert valeur is None or isinstance(valeur, str)


def test_les_templates_sont_exclus(
    repository: ObsidianRepository,
):
    """99-Templates ne doit jamais apparaître dans les résultats."""
    fiches = (
        repository.get_projects()
        + repository.get_collaborators()
        + repository.get_tasks()
    )

    for fiche in fiches:
        assert "99-Templates" not in fiche.path.parts


def test_lecture_d_une_fiche_par_son_type(
    vault: ObsidianVault,
    repository: ObsidianRepository,
):
    """Relire une fiche depuis son chemin donne le même résultat.

    On passe par le Repository plutôt que par un chemin codé en
    dur : le test survit aux déplacements de fichiers.
    """
    projects = repository.get_projects()

    if not projects:
        pytest.skip("aucun projet dans le Vault")

    project = projects[0]

    assert vault.read_project(project.path).name == project.name


def test_types_reconnus_uniquement(vault: ObsidianVault):
    """Un type inattendu signalerait une convention non gérée."""
    types_vus = set()

    for file_path in vault.list_markdown_files():
        if "99-Templates" in file_path.parts:
            continue

        data = vault.safe_read_frontmatter(file_path)

        if data and data.get("type"):
            types_vus.add(str(data["type"]))

    inconnus = types_vus - set(TYPES_CONNUS) - set(TYPES_PAS_ENCORE_LUS)

    assert not inconnus, (
        f"types non gérés par le bot : {sorted(inconnus)}"
    )
