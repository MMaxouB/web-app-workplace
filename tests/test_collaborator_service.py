"""Logique métier des collaborateurs, sur Vault temporaire."""

import datetime

import pytest

from core.obsidian.repository import ObsidianRepository
from core.obsidian.vault import ObsidianVault
from core.obsidian.writer import VaultWriter
from core.services.collaborators import (
    STATUS_FOLDERS,
    CollaboratorError,
    CollaboratorService,
    build_collaborator_content,
)


@pytest.fixture
def service(
    temp_vault: ObsidianVault,
    temp_repository: ObsidianRepository,
) -> CollaboratorService:
    return CollaboratorService(
        temp_repository,
        VaultWriter(temp_vault),
    )


MOMENT = datetime.datetime(
    2026,
    8,
    14,
    20,
    30,
    0,
    tzinfo=datetime.timezone(datetime.timedelta(hours=2)),
)


# =====================================================
# Format produit
# =====================================================


def test_contenu_reproduit_le_template():
    contenu = build_collaborator_content(
        name="Bob",
        status="active",
        role="Designer",
        company="Studio",
        discord="bob#0002",
        email="bob@example.invalid",
        github="bobdev",
        website="",
        timezone="Europe/Paris",
        now=MOMENT,
    )

    assert contenu.startswith("---\ntype: collaborator\n")
    assert "name: Bob\n" in contenu
    assert "joined: 2026-08-14\n" in contenu

    for section in (
        "# Bob",
        "## Informations",
        "## Contacts",
        "## Projets",
        "## Responsabilités",
        "## Compétences",
        "## Disponibilité",
        "## Notes",
        "## Historique",
    ):
        assert section in contenu, f"section absente : {section}"


def test_contenu_utilise_les_valeurs_brutes():
    """Les fiches collaborateur n'affichent pas « Actif »."""
    contenu = build_collaborator_content(
        name="Bob",
        status="active",
        role="",
        company="",
        discord="",
        email="",
        github="",
        website="",
        timezone="",
        now=MOMENT,
    )

    assert "| Statut         | active |" in contenu
    assert "Actif" not in contenu


# =====================================================
# Création
# =====================================================


def test_creation(
    service: CollaboratorService,
    temp_vault: ObsidianVault,
):
    collaborator = service.create_collaborator(
        name="Bob",
        role="Designer",
        discord="bob#0002",
        now=MOMENT,
    )

    assert collaborator.name == "Bob"
    assert collaborator.role == "Designer"
    assert collaborator.path.parent == (
        temp_vault.path / STATUS_FOLDERS["active"]
    )


def test_creation_refuse_doublon(service: CollaboratorService):
    with pytest.raises(CollaboratorError, match="existe déjà"):
        service.create_collaborator(name="Alice", now=MOMENT)


def test_creation_refuse_pseudo_discord_deja_pris(
    service: CollaboratorService,
):
    """Deux fiches avec le même Discord rendraient la recherche fausse."""
    with pytest.raises(CollaboratorError, match="déjà associé"):
        service.create_collaborator(
            name="Faux Alice",
            discord="alice#0001",
            now=MOMENT,
        )


def test_creation_statut_invalide(service: CollaboratorService):
    with pytest.raises(CollaboratorError, match="Statut invalide"):
        service.create_collaborator(name="Bob", status="archived")


# =====================================================
# Résolution
# =====================================================


def test_resolution_par_nom(service: CollaboratorService):
    assert service.resolve_collaborator("alice").name == "Alice"


def test_resolution_par_pseudo_discord(
    service: CollaboratorService,
):
    collaborator = service.resolve_collaborator("alice#0001")

    assert collaborator.name == "Alice"


def test_resolution_introuvable(service: CollaboratorService):
    with pytest.raises(CollaboratorError, match="Aucun collaborateur"):
        service.resolve_collaborator("personne")


# =====================================================
# Modifications
# =====================================================


def test_change_status_deplace(
    service: CollaboratorService,
    temp_vault: ObsidianVault,
):
    update = service.change_status("Alice", "waiting")

    assert update.collaborator.status == "waiting"
    assert update.collaborator.path.parent == (
        temp_vault.path / STATUS_FOLDERS["waiting"]
    )


def test_change_status_synchronise_le_tableau(
    service: CollaboratorService,
):
    update = service.change_status("Alice", "completed")

    contenu = update.collaborator.path.read_text(encoding="utf-8")

    assert "| Statut         | completed" in contenu


def test_set_field_contacts(service: CollaboratorService):
    """Le tableau « Contacts » doit être visé correctement."""
    update = service.set_field("Alice", "github", "alice-dev")

    assert update.collaborator.github == "alice-dev"

    contenu = update.collaborator.path.read_text(encoding="utf-8")

    assert "| GitHub     | alice-dev" in contenu


def test_set_field_refuse_champ_protege(
    service: CollaboratorService,
):
    with pytest.raises(CollaboratorError, match="non modifiable"):
        service.set_field("Alice", "status", "completed")

    with pytest.raises(CollaboratorError, match="non modifiable"):
        service.set_field("Alice", "type", "task")


def test_modification_ecrit_dans_l_historique(
    service: CollaboratorService,
):
    update = service.set_field("Alice", "role", "Lead")

    contenu = update.collaborator.path.read_text(encoding="utf-8")

    assert "Champ `role`" in contenu
    assert "Lead" in contenu
