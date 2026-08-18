"""Logique métier des tâches, sur Vault temporaire."""

import datetime

import pytest

from core.obsidian.repository import ObsidianRepository
from core.obsidian.vault import ObsidianVault
from core.obsidian.writer import VaultWriter
from core.services.tasks import (
    STATUS_FOLDERS,
    TaskError,
    TaskService,
    add_one_month,
    build_task_content,
    compute_due,
    sanitize_filename,
)


@pytest.fixture
def service(
    temp_vault: ObsidianVault,
    temp_repository: ObsidianRepository,
) -> TaskService:
    return TaskService(temp_repository, VaultWriter(temp_vault))


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
# Utilitaires
# =====================================================


def test_sanitize_filename():
    assert sanitize_filename("Tâche normale") == "Tâche normale"
    assert sanitize_filename("a/b:c*d?") == "abcd"
    assert sanitize_filename("  espaces   multiples  ") == (
        "espaces multiples"
    )


def test_sanitize_filename_conserve_les_caracteres_du_vault():
    """Le Vault contient « Créer bot discord + serv »."""
    assert (
        sanitize_filename("Créer bot discord + serv")
        == "Créer bot discord + serv"
    )
    assert (
        sanitize_filename("Si temps, création comptes $$")
        == "Si temps, création comptes $$"
    )


def test_sanitize_filename_vide():
    with pytest.raises(TaskError):
        sanitize_filename("///")


def test_compute_due():
    assert compute_due("24h", MOMENT) == MOMENT + datetime.timedelta(
        hours=24
    )
    assert compute_due("14j", MOMENT) == MOMENT + datetime.timedelta(
        days=14
    )


def test_compute_due_un_mois():
    assert compute_due("1m", MOMENT).month == 9
    assert compute_due("1m", MOMENT).day == 14


def test_compute_due_delai_inconnu():
    with pytest.raises(TaskError, match="Délai inconnu"):
        compute_due("2 semaines", MOMENT)


def test_add_one_month_fin_de_mois():
    """31 janvier + 1 mois ne doit pas déborder sur mars."""
    janvier = datetime.datetime(2026, 1, 31, 12, 0)

    resultat = add_one_month(janvier)

    assert (resultat.year, resultat.month, resultat.day) == (
        2026,
        2,
        28,
    )


def test_add_one_month_decembre():
    decembre = datetime.datetime(2026, 12, 15, 12, 0)

    resultat = add_one_month(decembre)

    assert (resultat.year, resultat.month) == (2027, 1)


# =====================================================
# Format produit
# =====================================================


def test_contenu_reproduit_le_template():
    contenu = build_task_content(
        title="Ma tâche",
        status="active",
        priority="high",
        platform="Code",
        project="Projet Alpha",
        collaborator="Moi",
        deadline_label="7j",
        now=MOMENT,
    )

    assert contenu.startswith("---\ntype: task\n")
    assert "status: active\n" in contenu
    assert 'platform: "Code"\n' in contenu
    assert "created: 2026-08-14T20:30:00+02:00\n" in contenu
    assert 'deadline: "7j"\n' in contenu
    assert "due: 2026-08-21T20:30:00+02:00\n" in contenu
    assert "completed:\n" in contenu

    for section in (
        "# Ma tâche",
        "## Informations",
        "## Objectif",
        "## Checklist",
        "## Résultat attendu",
        "## Ressources",
        "## Notes",
        "## Historique",
    ):
        assert section in contenu, f"section absente : {section}"


def test_contenu_lisible_par_le_vault(
    service: TaskService,
    temp_vault: ObsidianVault,
):
    task = service.create_task(
        title="Relecture",
        priority="critical",
        platform="Code",
        project="Projet Alpha",
        now=MOMENT,
    )

    assert task.status == "active"
    assert task.priority == "critical"
    assert task.due == "2026-08-21T20:30:00+02:00"


# =====================================================
# Création
# =====================================================


def test_creation_range_dans_le_bon_dossier(
    service: TaskService,
    temp_vault: ObsidianVault,
):
    task = service.create_task(
        title="Tâche en attente",
        status="waiting",
        now=MOMENT,
    )

    attendu = temp_vault.path / STATUS_FOLDERS["waiting"]

    assert task.path.parent == attendu


def test_creation_refuse_doublon(service: TaskService):
    service.create_task(title="Unique", now=MOMENT)

    with pytest.raises(TaskError, match="existe déjà"):
        service.create_task(title="Unique", now=MOMENT)


def test_creation_valide_les_valeurs(service: TaskService):
    with pytest.raises(TaskError, match="Statut invalide"):
        service.create_task(title="X", status="n_importe_quoi")

    with pytest.raises(TaskError, match="Priorité invalide"):
        service.create_task(title="X", priority="urgente")

    with pytest.raises(TaskError, match="Plateforme inconnue"):
        service.create_task(title="X", platform="Twitter")


def test_creation_nettoie_le_nom(
    service: TaskService,
    temp_vault: ObsidianVault,
):
    task = service.create_task(
        title="Fichier/interdit: oui?",
        now=MOMENT,
    )

    assert "/" not in task.path.name
    assert task.path.exists()


# =====================================================
# Changement de statut
# =====================================================


def test_change_status_deplace_le_fichier(
    service: TaskService,
    temp_vault: ObsidianVault,
):
    task = service.change_status("Tache complete", "completed").task

    assert task.status == "completed"
    assert task.path.parent == (
        temp_vault.path / STATUS_FOLDERS["completed"]
    )

    ancien = (
        temp_vault.path
        / "05-Tasks"
        / "Actives"
        / "Tache complete.md"
    )

    assert not ancien.exists()


def test_change_status_date_la_completion(
    service: TaskService,
):
    task = service.change_status("Tache complete", "completed").task

    assert task.completed == datetime.date.today().isoformat()


def test_change_status_preserve_le_contenu(
    service: TaskService,
):
    task = service.change_status("Tache complete", "archived").task

    contenu = task.path.read_text(encoding="utf-8")

    assert "# Tache complete" in contenu
    assert "## Historique" in contenu
    assert "due: 2026-08-27T23:04:57+02:00" in contenu
    assert 'platform: "Code"' in contenu


def test_change_status_refuse_statut_invalide(
    service: TaskService,
):
    with pytest.raises(TaskError, match="Statut invalide"):
        service.change_status("Tache complete", "fini")


def test_change_status_refuse_si_deja_au_statut(
    service: TaskService,
):
    with pytest.raises(TaskError, match="déjà au statut"):
        service.change_status("Tache complete", "active")


def test_change_status_tache_introuvable(service: TaskService):
    with pytest.raises(TaskError, match="Aucune tâche"):
        service.change_status("inexistante", "completed")


def test_change_status_refuse_si_ambigu(
    service: TaskService,
    temp_vault: ObsidianVault,
):
    """Face à plusieurs candidates, ne rien modifier."""
    avant = {
        chemin: chemin.read_text(encoding="utf-8")
        for chemin in temp_vault.path.rglob("*.md")
    }

    with pytest.raises(TaskError, match="Plusieurs tâches"):
        service.change_status("tache", "completed")

    for chemin, contenu in avant.items():
        assert chemin.read_text(encoding="utf-8") == contenu


# =====================================================
# Changement de priorité
# =====================================================


def test_change_priority(service: TaskService):
    task = service.change_priority("Tache attente", "critical").task

    assert task.priority == "critical"


def test_change_priority_ne_deplace_pas(
    service: TaskService,
    temp_vault: ObsidianVault,
):
    avant = service.resolve_task("Tache attente").path

    task = service.change_priority("Tache attente", "high").task

    assert task.path == avant


def test_change_priority_refuse_valeur_invalide(
    service: TaskService,
):
    with pytest.raises(TaskError, match="Priorité invalide"):
        service.change_priority("Tache attente", "urgente")


def test_change_priority_refuse_si_identique(
    service: TaskService,
):
    with pytest.raises(TaskError, match="déjà en priorité"):
        service.change_priority("Tache attente", "low")


# =====================================================
# Champs libres
# =====================================================


def test_set_field(service: TaskService):
    task = service.set_field("Tache attente", "project", "Projet Z").task

    assert task.project == "Projet Z"


def test_set_field_refuse_champ_protege(service: TaskService):
    """On ne contourne pas change_status par set_field."""
    with pytest.raises(TaskError, match="non modifiable"):
        service.set_field("Tache attente", "status", "completed")

    with pytest.raises(TaskError, match="non modifiable"):
        service.set_field("Tache attente", "type", "project")


def test_set_field_valide_la_plateforme(service: TaskService):
    with pytest.raises(TaskError, match="Plateforme inconnue"):
        service.set_field("Tache attente", "platform", "Twitter")


# =====================================================
# Synchronisation du tableau et de l'historique
# =====================================================


def test_change_status_synchronise_le_tableau(
    service: TaskService,
):
    update = service.change_status("Tache complete", "completed")

    contenu = update.task.path.read_text(encoding="utf-8")

    lignes_tableau = [
        ligne
        for ligne in contenu.splitlines()
        if ligne.startswith("| Statut")
    ]

    assert lignes_tableau == [
        "| Statut        | `completed`               |"
    ]


def test_change_priority_synchronise_le_tableau(
    service: TaskService,
):
    update = service.change_priority("Tache complete", "low")

    contenu = update.task.path.read_text(encoding="utf-8")

    assert "| Priorité      | `low`" in contenu


def test_change_status_ecrit_dans_l_historique(
    service: TaskService,
):
    update = service.change_status("Tache complete", "waiting")

    contenu = update.task.path.read_text(encoding="utf-8")

    assert "Statut passé de `active` à `waiting`" in contenu
    assert "depuis la web app" in contenu


def test_historique_en_tete_de_section(
    service: TaskService,
):
    """La nouvelle entrée passe avant les anciennes."""
    update = service.change_priority("Tache complete", "low")

    contenu = update.task.path.read_text(encoding="utf-8")

    nouvelle = contenu.index("Priorité passée")
    ancienne = contenu.index("Tâche créée")

    assert nouvelle < ancienne


def test_set_field_synchronise_et_historise(
    service: TaskService,
):
    update = service.set_field(
        "Tache complete",
        "platform",
        "Discord",
    )

    contenu = update.task.path.read_text(encoding="utf-8")

    assert "| Plateforme    | Discord" in contenu
    assert "Champ `platform`" in contenu


def test_note_sans_tableau_ni_historique_avertit(
    service: TaskService,
):
    """L'opération réussit quand même : le frontmatter fait foi."""
    update = service.change_priority("Tache attente", "high")

    assert update.task.priority == "high"
    assert len(update.warnings) == 2

    joint = " ".join(update.warnings)

    assert "tableau" in joint
    assert "Historique" in joint


def test_avertissements_vides_quand_tout_est_present(
    service: TaskService,
):
    update = service.change_priority("Tache complete", "low")

    assert update.warnings == []
