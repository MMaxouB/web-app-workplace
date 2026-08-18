"""Logique métier des projets, sur Vault temporaire."""

import datetime

import pytest

from core.obsidian.repository import ObsidianRepository
from core.obsidian.vault import ObsidianVault
from core.obsidian.writer import VaultWriter
from core.services.projects import (
    STATUS_FOLDERS,
    ProjectError,
    ProjectService,
    build_project_content,
    display_value,
)


@pytest.fixture
def service(
    temp_vault: ObsidianVault,
    temp_repository: ObsidianRepository,
) -> ProjectService:
    return ProjectService(temp_repository, VaultWriter(temp_vault))


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
# Libellés du tableau
# =====================================================


def test_display_value_statut_en_francais():
    """Les fiches projet affichent « Actif », pas « active »."""
    assert display_value("status", "active") == "Actif"
    assert display_value("status", "waiting") == "En attente"
    assert display_value("status", "completed") == "Terminé"
    assert display_value("status", "archived") == "Archivé"


def test_display_value_priorite_capitalisee():
    assert display_value("priority", "high") == "High"
    assert display_value("category", "software") == "Software"


def test_display_value_autre_champ_inchange():
    assert display_value("deadline", "2026-09-01") == "2026-09-01"


# =====================================================
# Format produit
# =====================================================


def test_contenu_reproduit_le_template():
    contenu = build_project_content(
        name="Mon Projet",
        status="active",
        category="software",
        priority="high",
        deadline="2026-12-01",
        repository="https://example.invalid/repo",
        now=MOMENT,
    )

    assert contenu.startswith("---\ntype: project\n")
    assert "name: Mon Projet\n" in contenu
    assert "created: 2026-08-14\n" in contenu

    for section in (
        "# Mon Projet",
        "## Informations",
        "## Description",
        "## Objectif",
        "## Collaborateurs",
        "## Responsabilités",
        "## Technologies",
        "## Repository",
        "## Roadmap",
        "## Décisions importantes",
        "## Problèmes / Risques",
        "## Notes",
        "## Historique",
    ):
        assert section in contenu, f"section absente : {section}"


def test_contenu_utilise_les_libelles_lisibles():
    contenu = build_project_content(
        name="Mon Projet",
        status="active",
        category="software",
        priority="high",
        deadline="",
        repository="",
        now=MOMENT,
    )

    assert "| Statut    | Actif |" in contenu
    assert "| Priorité  | High |" in contenu
    assert "| Deadline  | — |" in contenu


# =====================================================
# Création
# =====================================================


def test_creation(service: ProjectService, temp_vault: ObsidianVault):
    project = service.create_project(
        name="Nouveau Projet",
        category="software",
        priority="high",
        now=MOMENT,
    )

    assert project.status == "active"
    assert project.priority == "high"
    assert project.path.parent == (
        temp_vault.path / STATUS_FOLDERS["active"]
    )


def test_creation_refuse_doublon(service: ProjectService):
    with pytest.raises(ProjectError, match="existe déjà"):
        service.create_project(name="Projet Alpha", now=MOMENT)


def test_creation_valide_la_priorite(service: ProjectService):
    with pytest.raises(ProjectError, match="Priorité invalide"):
        service.create_project(name="X", priority="urgente")


# =====================================================
# Changement de statut
# =====================================================


def test_change_status_deplace(
    service: ProjectService,
    temp_vault: ObsidianVault,
):
    update = service.change_status("Projet Alpha", "completed")

    assert update.project.status == "completed"
    assert update.project.path.parent == (
        temp_vault.path / STATUS_FOLDERS["completed"]
    )


def test_change_status_refuse_si_identique(
    service: ProjectService,
):
    with pytest.raises(ProjectError, match="déjà au statut"):
        service.change_status("Projet Alpha", "active")


def test_change_status_projet_introuvable(
    service: ProjectService,
):
    with pytest.raises(ProjectError, match="Aucun projet"):
        service.change_status("inexistant", "completed")


def test_change_status_preserve_le_contenu(
    service: ProjectService,
):
    update = service.change_status("Projet Alpha", "waiting")

    contenu = update.project.path.read_text(encoding="utf-8")

    assert "# Projet Alpha" in contenu
    assert "## Description" in contenu
    assert "repository: https://example.invalid/alpha" in contenu


# =====================================================
# Historique groupé
# =====================================================


def test_historique_groupe_sous_une_date(
    service: ProjectService,
):
    """Deux modifications le même jour partagent le sous-titre."""
    service.change_priority("Projet Alpha", "low")

    update = service.change_priority("Projet Alpha", "critical")

    contenu = update.project.path.read_text(encoding="utf-8")

    aujourd_hui = datetime.date.today().isoformat()

    assert contenu.count(f"### {aujourd_hui}") == 1
    assert contenu.count("Priorité passée") == 2


def test_historique_conserve_les_anciennes_entrees(
    service: ProjectService,
):
    update = service.change_priority("Projet Alpha", "low")

    contenu = update.project.path.read_text(encoding="utf-8")

    assert "### 2026-08-01" in contenu
    assert "- Projet créé." in contenu


# =====================================================
# Champs libres
# =====================================================


def test_set_field(service: ProjectService):
    update = service.set_field(
        "Projet Alpha",
        "category",
        "cybersecurity",
    )

    assert update.project.category == "cybersecurity"


def test_set_field_refuse_champ_protege(service: ProjectService):
    with pytest.raises(ProjectError, match="non modifiable"):
        service.set_field("Projet Alpha", "status", "completed")

    with pytest.raises(ProjectError, match="non modifiable"):
        service.set_field("Projet Alpha", "type", "task")


# =====================================================
# Synchronisation du tableau des fiches projet
# =====================================================


def test_change_status_synchronise_le_tableau(
    service: ProjectService,
):
    update = service.change_status("Projet Alpha", "completed")

    contenu = update.project.path.read_text(encoding="utf-8")

    lignes = [
        ligne
        for ligne in contenu.splitlines()
        if ligne.startswith("| Statut")
    ]

    assert lignes == ["| Statut    | Terminé     |"]


def test_change_priority_synchronise_le_tableau(
    service: ProjectService,
):
    update = service.change_priority("Projet Alpha", "low")

    contenu = update.project.path.read_text(encoding="utf-8")

    assert "| Priorité  | Low" in contenu


def test_set_field_synchronise_la_categorie(
    service: ProjectService,
):
    update = service.set_field(
        "Projet Alpha",
        "category",
        "cybersecurity",
    )

    contenu = update.project.path.read_text(encoding="utf-8")

    assert "| Catégorie | Cybersecurity" in contenu


def test_tableau_reste_aligne(service: ProjectService):
    projet = service.resolve_project("Projet Alpha")

    avant = [
        len(ligne)
        for ligne in projet.path.read_text(
            encoding="utf-8"
        ).splitlines()
        if ligne.startswith("| ")
    ]

    update = service.change_status("Projet Alpha", "waiting")

    apres = [
        len(ligne)
        for ligne in update.project.path.read_text(
            encoding="utf-8"
        ).splitlines()
        if ligne.startswith("| ")
    ]

    assert avant == apres


def test_aucun_avertissement_sur_fiche_complete(
    service: ProjectService,
):
    update = service.change_priority("Projet Alpha", "low")

    assert update.warnings == []


# =====================================================
# Lien avec le salon Discord
# =====================================================

SALON = 1399887766554433221
MESSAGE = 1400111222333444555


def test_link_panel_ecrit_les_deux_champs(service, temp_repository):
    update = service.link_panel("Projet Alpha", SALON, MESSAGE)

    assert update.project.discord_channel_id == str(SALON)
    assert update.project.discord_panel_message == str(MESSAGE)

    relu = temp_repository.find_project("Projet Alpha")

    assert relu.discord_channel_id == str(SALON)


def test_link_panel_ajoute_les_cles_absentes(service, temp_vault_path):
    """Les fiches existantes n'ont pas ces clés : il faut les créer."""
    fiche = temp_vault_path / "02-Projects/Actifs/Projet Alpha.md"

    avant = fiche.read_text(encoding="utf-8")

    assert "discord_channel_id" not in avant

    service.link_panel("Projet Alpha", SALON, MESSAGE)

    apres = fiche.read_text(encoding="utf-8")

    assert f"discord_channel_id: {SALON}" in apres
    assert f"discord_panel_message: {MESSAGE}" in apres


def test_link_panel_ne_touche_a_rien_d_autre(service, temp_vault_path):
    """Le reste de la fiche doit rester identique au caractère près."""
    fiche = temp_vault_path / "02-Projects/Actifs/Projet Alpha.md"

    avant = fiche.read_text(encoding="utf-8")

    service.link_panel("Projet Alpha", SALON, MESSAGE)

    apres = fiche.read_text(encoding="utf-8")

    # Seuls les ajouts attendus séparent les deux versions.
    ajouts = [
        ligne
        for ligne in apres.splitlines()
        if ligne not in avant.splitlines()
    ]

    assert f"discord_channel_id: {SALON}" in ajouts
    assert f"discord_panel_message: {MESSAGE}" in ajouts

    # Le corps est intact : description, tableau, sections.
    for marqueur in (
        "## Description",
        "Un projet de test.",
        "| Statut    | Actif       |",
        "repository: https://example.invalid/alpha",
    ):
        assert marqueur in apres


def test_link_panel_consigne_le_rattachement(service, temp_vault_path):
    service.link_panel("Projet Alpha", SALON, MESSAGE)

    fiche = temp_vault_path / "02-Projects/Actifs/Projet Alpha.md"

    historique = fiche.read_text(encoding="utf-8").split(
        "## Historique"
    )[1]

    assert "Panneau installé" in historique
    assert str(SALON) in historique


def test_reposter_le_panneau_ne_pollue_pas_l_historique(
    service,
    temp_vault_path,
):
    """Un panneau reposté change d'identifiant, sans nouvel événement."""
    service.link_panel("Projet Alpha", SALON, MESSAGE)

    fiche = temp_vault_path / "02-Projects/Actifs/Projet Alpha.md"

    service.link_panel("Projet Alpha", SALON, MESSAGE + 1)

    historique = fiche.read_text(encoding="utf-8").split(
        "## Historique"
    )[1]

    assert historique.count("Panneau installé") == 1

    relu = service.repository.find_project("Projet Alpha")

    assert relu.discord_panel_message == str(MESSAGE + 1)


def test_changer_de_salon_est_consigne(service, temp_vault_path):
    service.link_panel("Projet Alpha", SALON, MESSAGE)
    service.link_panel("Projet Alpha", SALON + 7, MESSAGE)

    historique = (
        temp_vault_path / "02-Projects/Actifs/Projet Alpha.md"
    ).read_text(encoding="utf-8").split("## Historique")[1]

    assert historique.count("Panneau installé") == 2


def test_unlink_panel_oublie_le_message_pas_le_salon(service):
    service.link_panel("Projet Alpha", SALON, MESSAGE)

    update = service.unlink_panel("Projet Alpha")

    assert update.project.discord_panel_message in (None, "")
    assert update.project.discord_channel_id == str(SALON)


def test_le_lien_n_est_pas_modifiable_a_la_main(service):
    """Ces champs sont écrits par le bot, jamais saisis."""
    with pytest.raises(ProjectError, match="non modifiable"):
        service.set_field(
            "Projet Alpha",
            "discord_channel_id",
            "123",
        )


def test_projet_sans_panneau_a_des_champs_vides(temp_repository):
    """Les fiches existantes restent valides sans ces clés."""
    project = temp_repository.find_project("Projet Alpha")

    assert project.discord_channel_id is None
    assert project.discord_panel_message is None
