"""Garde-fous de la couche Vault.

Ces tests vérifient que le bot refuse ce qu'il doit refuser et
qu'il survit aux fichiers mal formés. Ils tournent sur un Vault
temporaire.
"""

from pathlib import Path

import pytest

from core.obsidian.vault import ObsidianVault


# =====================================================
# Protection des chemins
# =====================================================


def test_refuse_fichier_hors_vault(
    temp_vault: ObsidianVault,
    tmp_path: Path,
):
    exterieur = tmp_path.parent / "exterieur.md"
    exterieur.write_text("---\ntype: task\n---\n", encoding="utf-8")

    with pytest.raises(ValueError, match="en dehors du Vault"):
        temp_vault.read_frontmatter(exterieur)


def test_refuse_remontee_par_chemin_relatif(
    temp_vault: ObsidianVault,
):
    piege = temp_vault.path / "05-Tasks" / ".." / ".." / "evasion.md"

    with pytest.raises(ValueError, match="en dehors du Vault"):
        temp_vault.read_frontmatter(piege)


def test_refuse_fichier_non_markdown(
    temp_vault: ObsidianVault,
):
    autre = temp_vault.path / "note.txt"
    autre.write_text("bonjour", encoding="utf-8")

    with pytest.raises(ValueError, match="Markdown"):
        temp_vault.read_frontmatter(autre)


def test_fichier_inexistant(temp_vault: ObsidianVault):
    manquant = temp_vault.path / "05-Tasks" / "Fantome.md"

    with pytest.raises(FileNotFoundError):
        temp_vault.read_frontmatter(manquant)

    assert temp_vault.safe_read_frontmatter(manquant) is None


# =====================================================
# Tolérance aux fichiers mal formés
# =====================================================


def test_fichier_templater_leve_une_erreur_propre(
    temp_vault: ObsidianVault,
):
    """Le template Templater n'est pas du YAML.

    Avant durcissement, PyYAML laissait fuiter une ScannerError.
    """
    template = (
        temp_vault.path
        / "99-Templates"
        / "template-taches.md"
    )

    with pytest.raises(ValueError, match="illisible"):
        temp_vault.read_frontmatter(template)


def test_fichier_templater_ignore_en_mode_tolerant(
    temp_vault: ObsidianVault,
):
    template = (
        temp_vault.path
        / "99-Templates"
        / "template-taches.md"
    )

    assert temp_vault.safe_read_frontmatter(template) is None


def test_fichier_sans_frontmatter(temp_vault: ObsidianVault):
    note = temp_vault.path / "02-Projects" / "Projects.md"

    assert temp_vault.read_frontmatter(note) == {}


def test_parcours_complet_ne_plante_pas(
    temp_vault: ObsidianVault,
):
    """Aucun fichier du Vault ne doit faire tomber un parcours."""
    for file_path in temp_vault.list_markdown_files():
        temp_vault.safe_read_frontmatter(file_path)


# =====================================================
# Données incomplètes
# =====================================================


def test_tache_sans_statut_ni_priorite(
    temp_vault: ObsidianVault,
):
    """Une tâche incomplète ne doit pas lever de KeyError."""
    chemin = (
        temp_vault.path
        / "05-Tasks"
        / "_Inbox"
        / "Tache minimale.md"
    )

    task = temp_vault.read_task(chemin)

    assert task.name == "Tache minimale"
    assert task.status == "unknown"
    assert task.priority is None
    assert task.is_open


def test_mauvais_type_refuse(temp_vault: ObsidianVault):
    projet = (
        temp_vault.path
        / "02-Projects"
        / "Actifs"
        / "Projet Alpha.md"
    )

    with pytest.raises(ValueError, match="n'est pas une tâche"):
        temp_vault.read_task(projet)


# =====================================================
# Normalisation des valeurs
# =====================================================


def test_dates_normalisees_en_chaines(
    temp_vault: ObsidianVault,
):
    """PyYAML renvoie des objets date : on veut des chaînes ISO."""
    chemin = (
        temp_vault.path
        / "05-Tasks"
        / "Actives"
        / "Tache complete.md"
    )

    task = temp_vault.read_task(chemin)

    assert isinstance(task.created, str)
    assert task.created == "2026-08-13T23:04:57+02:00"
    assert task.due == "2026-08-27T23:04:57+02:00"


def test_due_non_date_conserve(temp_vault: ObsidianVault):
    """Le Vault contient des `due: x` : on ne doit pas les perdre."""
    chemin = (
        temp_vault.path
        / "05-Tasks"
        / "En attente"
        / "Tache attente.md"
    )

    task = temp_vault.read_task(chemin)

    assert task.due == "x"
    assert task.created == "2026-08-10"


# =====================================================
# Lecture du corps
# =====================================================


def test_read_body_exclut_le_frontmatter(
    temp_vault: ObsidianVault,
):
    chemin = (
        temp_vault.path
        / "05-Tasks"
        / "Actives"
        / "Tache complete.md"
    )

    body = temp_vault.read_body(chemin)

    assert "type: task" not in body
    assert "# Tache complete" in body
    assert "## Historique" in body


def test_read_body_sans_frontmatter(
    temp_vault: ObsidianVault,
):
    note = temp_vault.path / "02-Projects" / "Projects.md"

    body = temp_vault.read_body(note)

    assert "# Note libre" in body
