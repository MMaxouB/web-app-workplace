"""Durcissement : ce que le bot doit refuser d'écrire.

Les messages Discord sont du texte libre. Ces tests vérifient
qu'un contenu hostile ou maladroit ne peut ni corrompre le
frontmatter, ni fabriquer de fausses sections.
"""

import datetime
from pathlib import Path

import pytest

from core.obsidian.repository import ObsidianRepository
from core.obsidian.vault import ObsidianVault
from core.obsidian.writer import VaultWriter, flatten, format_value
from core.services.collaborators import CollaboratorService
from core.services.notes import NoteService, format_note
from core.services.projects import ProjectService
from core.services.tasks import TaskService


@pytest.fixture
def writer(temp_vault: ObsidianVault) -> VaultWriter:
    return VaultWriter(temp_vault)


@pytest.fixture
def tache(temp_vault: ObsidianVault) -> Path:
    return (
        temp_vault.path
        / "05-Tasks"
        / "Actives"
        / "Tache complete.md"
    )


@pytest.fixture
def note_service(
    temp_vault: ObsidianVault,
    temp_repository: ObsidianRepository,
) -> NoteService:
    w = VaultWriter(temp_vault)

    return NoteService(
        temp_repository,
        w,
        TaskService(temp_repository, w),
        ProjectService(temp_repository, w),
        CollaboratorService(temp_repository, w),
    )


MOMENT = datetime.datetime(2026, 8, 14, 20, 30)


# =====================================================
# Aplatissement des valeurs
# =====================================================


def test_flatten_retours_a_la_ligne():
    assert flatten("foo\nbar") == "foo bar"
    assert flatten("foo\r\nbar") == "foo bar"


def test_flatten_caracteres_de_controle():
    assert flatten("foo\x00\x07bar") == "foobar"


def test_flatten_espaces_multiples():
    assert flatten("  foo   bar  ") == "foo bar"


# =====================================================
# Injection dans le frontmatter
# =====================================================


def test_injection_de_cle_impossible(
    writer: VaultWriter,
    tache: Path,
    temp_vault: ObsidianVault,
):
    """Le grand classique : glisser une clé via un retour ligne."""
    writer.set_frontmatter_field(
        tache,
        "project",
        "Projet X\nstatus: archived",
    )

    data = temp_vault.read_frontmatter(tache)

    assert data["status"] == "active"
    assert data["project"] == "Projet X status: archived"

    lignes = tache.read_text(encoding="utf-8").splitlines()

    assert lignes.count("status: archived") == 0


def test_injection_de_delimiteur_impossible(
    writer: VaultWriter,
    tache: Path,
    temp_vault: ObsidianVault,
):
    """Un « --- » collé ne doit pas fermer le frontmatter."""
    writer.set_frontmatter_field(
        tache,
        "project",
        "Fin\n---\n# Faux titre",
    )

    data = temp_vault.read_frontmatter(tache)

    assert data["type"] == "task"
    assert "# Faux titre" not in data["project"].split()[0]

    task = temp_vault.read_task(tache)

    assert task.status == "active"


def test_valeur_avec_deux_points_reste_lisible(
    writer: VaultWriter,
    tache: Path,
    temp_vault: ObsidianVault,
):
    writer.set_frontmatter_field(
        tache,
        "project",
        "Refonte : espace de travail",
    )

    data = temp_vault.read_frontmatter(tache)

    assert data["project"] == "Refonte : espace de travail"


def test_format_value_neutralise_les_sauts_de_ligne():
    assert "\n" not in format_value("a\nb")
    assert format_value("a\nb") == "a b"


# =====================================================
# Restauration après vérification
# =====================================================


def test_restauration_si_verification_echoue(
    writer: VaultWriter,
    tache: Path,
    monkeypatch,
):
    """Un désaccord entre écriture et relecture restaure le fichier."""
    contenu_avant = tache.read_text(encoding="utf-8")

    original = writer._assert_field

    def verification_impossible(data, key, value):
        raise Exception("désaccord simulé")

    monkeypatch.setattr(
        writer,
        "_assert_field",
        verification_impossible,
    )

    with pytest.raises(Exception):
        writer.set_frontmatter_field(tache, "status", "completed")

    assert tache.read_text(encoding="utf-8") == contenu_avant

    monkeypatch.setattr(writer, "_assert_field", original)


# =====================================================
# Fausses sections via les notes
# =====================================================


def test_note_multiligne_ne_cree_pas_de_section(
    note_service: NoteService,
):
    """Un « ## Historique » collé ne doit pas devenir un vrai titre."""
    result = note_service.add_note(
        "projet",
        "Projet Alpha",
        "Compte rendu\n## Historique\n- fausse entrée",
        now=MOMENT,
    )

    contenu = result.path.read_text(encoding="utf-8")

    lignes = contenu.splitlines()

    # Une seule vraie section Historique
    assert lignes.count("## Historique") == 1

    # Le faux titre est indenté, donc inerte
    assert "  ## Historique" in contenu


def test_note_multiligne_reste_une_puce(
    note_service: NoteService,
):
    resultat = format_note("ligne un\nligne deux", MOMENT)

    assert resultat.startswith("- ligne un")
    assert "\n  ligne deux" in resultat


def test_note_vide_apres_nettoyage(note_service: NoteService):
    with pytest.raises(Exception):
        note_service.add_note("projet", "Projet Alpha", "\n\n\n")


def test_note_preserve_le_frontmatter(
    note_service: NoteService,
):
    result = note_service.add_note(
        "tache",
        "Tache complete",
        "---\ntype: project\n---",
        now=MOMENT,
    )

    contenu = result.path.read_text(encoding="utf-8")

    assert contenu.startswith("---\ntype: task\n")

    lignes = contenu.splitlines()

    assert lignes[0] == "---"
    assert lignes.count("---") == 2


# =====================================================
# Chemins
# =====================================================


def test_symlink_vers_l_exterieur_refuse(
    writer: VaultWriter,
    temp_vault: ObsidianVault,
    tmp_path: Path,
):
    """Un lien symbolique ne doit pas servir d'échappatoire."""
    exterieur = tmp_path.parent / "cible-externe.md"
    exterieur.write_text("---\ntype: task\n---\n", encoding="utf-8")

    lien = temp_vault.path / "05-Tasks" / "lien.md"

    try:
        lien.symlink_to(exterieur)
    except (OSError, NotImplementedError):
        pytest.skip("liens symboliques indisponibles")

    with pytest.raises(ValueError, match="en dehors du Vault"):
        writer.set_frontmatter_field(lien, "status", "completed")

    assert "type: task" in exterieur.read_text(encoding="utf-8")
    assert "status: completed" not in exterieur.read_text(
        encoding="utf-8"
    )
